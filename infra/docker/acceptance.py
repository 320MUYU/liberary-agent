"""Deployed-stack acceptance using dedicated records in the Docker database only."""

import argparse
import base64
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

sys.path.insert(0, "/app")

import httpx

STATE = Path("/app/data/docker-acceptance/state.json")


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def request(client, method, path, token=None, **kwargs):
    response = client.request(method, "/api" + path,
        headers={"Authorization": "Bearer " + token} if token else {}, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if payload["code"] != 200:
        raise RuntimeError(f"{method} {path}: {payload['code']} {payload.get('message')}")
    return payload.get("data")


def tokens(client, state):
    return {role: request(client, "POST", "/auth/login", json={
        "username": state[role], "password": state["password"]})["token"] for role in ("reader", "admin")}


def business(client, state):
    from sqlalchemy.engine import make_url
    from app.config import settings
    if make_url(settings.DATABASE_URL).host != "mysql":
        raise RuntimeError("Acceptance writes are restricted to the Docker database")
    if not state:
        suffix = uuid4().hex[:10]
        state.update(reader="dk_r_" + suffix, admin="dk_a_" + suffix,
            password=secrets.token_urlsafe(18), checks={}, suffix=suffix)
        save(state)
    from app.database import SessionLocal
    from app.models.users import User
    from app.utils.bcrypt import hash_password
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username=state["admin"]).first()
        if admin is None:
            db.add(User(username=state["admin"], password=hash_password(state["password"]),
                name="Docker 部署验收管理员", role="admin", status=1))
            db.commit()
        reader = db.query(User).filter_by(username=state["reader"]).first()
    if reader is None:
        request(client, "POST", "/auth/register", json={"username": state["reader"],
            "password": state["password"], "confirm_password": state["password"], "name": "Docker 部署验收读者"})
    token = tokens(client, state)
    state["checks"]["register_and_login"] = True
    assert request(client, "GET", "/user/info", token["reader"])["username"] == state["reader"]
    assert request(client, "GET", "/books", token["reader"])["total"] > 0
    assert request(client, "GET", "/lab/list", token["reader"])
    state["checks"]["migrated_catalogue_and_spaces"] = True
    assert client.get("/api/admin/tasks/summary", headers={"Authorization": "Bearer " + token["reader"]}).status_code == 403
    assert client.get("/api/books").status_code == 401
    state["checks"]["permissions"] = True
    for path in ("/", "/books", "/assistant", "/admin/knowledge"):
        response = client.get(path)
        assert response.status_code == 200 and '<div id="app">' in response.text
    state["checks"]["nginx_history_fallback"] = True
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=")
    uploaded = request(client, "POST", "/file/upload", token["reader"], files={"file": ("docker.png", png, "image/png")})
    state["upload"] = uploaded["url"]
    assert hashlib.sha256(client.get(state["upload"]).content).digest() == hashlib.sha256(png).digest()
    state["checks"]["uploads_proxy"] = True
    title = "Docker 部署验收 " + state["suffix"]
    state["book_title"] = title
    if "book_id" not in state:
        book = request(client, "POST", "/admin/books", token["admin"], json={"title": title,
            "author": "部署验收", "category": "部署验收", "is_active": True})
        state["book_id"] = book["id"]
        save(state)
    if "copy_id" not in state:
        copy = request(client, "POST", "/admin/book-copies", token["admin"], json={
            "book_id": state["book_id"], "barcode": "DOCKER-" + state["suffix"], "location": "部署验收专用"})
        state["copy_id"] = copy["id"]
        save(state)
    if "loan_id" not in state:
        loan = request(client, "POST", "/loans", token["reader"], json={"book_id": state["book_id"]})
        state["loan_id"] = loan["id"]
        save(state)
        assert loan["status"] == "pending"
        path = f"/admin/loans/{loan['id']}"
        assert request(client, "POST", path + "/confirm-borrow", token["admin"], json={"copy_id": state["copy_id"]})["status"] == "borrowed"
        assert request(client, "POST", f"/loans/{loan['id']}/request-return", token["reader"])["status"] == "return_pending"
        assert request(client, "POST", path + "/confirm-return", token["admin"])["status"] == "returned"
    state["checks"]["borrow_and_return"] = True
    lab_data = {"name": "Docker 验收空间 " + state["suffix"], "code": "DK-" + state["suffix"],
        "building": "部署验收", "floor": "1", "capacity": 4, "category": "研讨室", "status": "available"}
    if "lab_id" not in state:
        state["lab_id"] = request(client, "POST", "/admin/lab", token["admin"], json=lab_data)["id"]
        save(state)
    if "reservation_id" not in state:
        reservation = request(client, "POST", "/reservation", token["reader"], json={
            "lab_id": state["lab_id"], "date": str(date.today() + timedelta(days=3)),
            "start": "14:00", "end": "15:00", "people": 2, "purpose": "Docker 部署验收"})
        state["reservation_id"] = reservation["id"]
        save(state)
        reviewed = request(client, "PUT", f"/admin/reservation/{reservation['id']}/review", token["admin"], json={"status": "approved"})
        assert reviewed["status"] == "approved"
        assert request(client, "PUT", f"/reservation/{reservation['id']}/cancel", token["reader"])["status"] == "cancelled"
    state["checks"]["reservation_review_and_cancel"] = True
    save(state)


def agent_probe(client, state):
    token = tokens(client, state)
    state.setdefault("agent_run_id", str(uuid4()))
    save(state)
    run = request(client, "POST", "/agent/runs", token["reader"], json={
        "request_id": state["agent_run_id"], "query": f"请精确查找书名为《{state['book_title']}》的图书，我要借阅。"})
    assert run["status"] == "select_book", f"Unexpected agent status: {run['status']}"
    assert state["book_id"] in [book["id"] for book in run["books"]]
    path = "/agent/runs/" + state["agent_run_id"]
    selected = request(client, "POST", path + "/select", token["reader"], json={"book_id": state["book_id"]})
    assert selected["status"] == "confirm_borrow"
    decision = {"action_id": selected["action"]["id"], "confirmed": True}
    first = request(client, "POST", path + "/decision", token["reader"], json=decision)
    replay = request(client, "POST", path + "/decision", token["reader"], json=decision)
    assert first["receipt"] == replay["receipt"]
    state["agent_loan_id"] = first["receipt"]["loan_id"]
    request(client, "POST", f"/loans/{state['agent_loan_id']}/cancel", token["reader"])
    state["checks"]["real_model_mcp_confirmation_and_replay"] = True
    save(state)


def live_ai(client, state):
    if not state["checks"].get("real_model_mcp_confirmation_and_replay"):
        agent_probe(client, state)
    token = tokens(client, state)
    answer = request(client, "POST", "/ai/chat", token["reader"], json={"mode": "knowledge", "messages": [
        {"role": "user", "content": "华科入馆须知允许带大件行李或易燃易爆物品吗？"}]})
    state["ai_answer"] = answer
    save(state)
    assert answer["sources"] and answer["retrieval_status"] == "matched"
    state["checks"]["real_rag_with_citations"] = True
    state.setdefault("conversation_id", str(uuid4()))
    conversation = request(client, "POST", "/conversations", token["reader"], json={"request_id": state["conversation_id"]})
    state["conversation_id"] = conversation["conversation_id"]
    save(state)
    request(client, "POST", f"/conversations/{state['conversation_id']}/messages", token["reader"], json={
        "request_id": str(uuid4()), "text": "请用一句话介绍你能帮助我做什么。", "hint": "chat"})
    state["checks"]["unified_conversation"] = True
    save(state)


def recovery(client, state):
    token = tokens(client, state)
    assert client.get(state["upload"]).status_code == 200
    loans = request(client, "GET", "/loans", token["reader"])["items"]
    assert any(loan["id"] == state["loan_id"] and loan["status"] == "returned" for loan in loans)
    reservations = request(client, "GET", "/reservation/mine", token["reader"])
    assert any(item["id"] == state["reservation_id"] and item["status"] == "cancelled" for item in reservations)
    run = request(client, "GET", "/agent/runs/" + state["agent_run_id"], token["reader"])
    assert run["receipt"]["loan_id"] == state["agent_loan_id"]
    conversation = request(client, "GET", "/conversations/" + state["conversation_id"], token["reader"])
    assert conversation["turns"]
    state["checks"]["restart_preserves_sql_files_checkpoints_and_conversations"] = True
    save(state)


def cleanup(state):
    from app.database import SessionLocal
    from app.models.users import User
    from app.models.books import Book
    from app.models.labs import Lab
    with SessionLocal() as db:
        for username in (state["reader"], state["admin"]):
            db.query(User).filter_by(username=username).one().status = 0
        db.get(Book, state["book_id"]).is_active = False
        db.get(Lab, state["lab_id"]).status = "maintenance"
        db.commit()
    state["checks"]["acceptance_records_disabled"] = True
    save(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["business", "live-ai", "recovery", "cleanup"])
    args = parser.parse_args()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    with httpx.Client(base_url="http://web", timeout=180, trust_env=False) as client:
        if args.mode == "cleanup":
            cleanup(state)
        else:
            {"business": business, "live-ai": live_ai, "recovery": recovery}[args.mode](client, state)
    print(json.dumps({"checks": state["checks"], "passed": all(state["checks"].values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
