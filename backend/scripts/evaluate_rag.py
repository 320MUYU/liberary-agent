"""Deterministic offline RAG regression; --live explicitly calls a running API.

Offline mode uses an isolated in-memory database and injected adapters. It never
uploads fixture documents or invokes DeepSeek, embedding APIs or Chroma.
"""

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BACKEND_DIR / "tests" / "fixtures" / "rag_evaluation.json"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

STATUSES = {"matched", "no_match", "insufficient_evidence"}
OFFLINE_SCOPE = "合成语料及确定性假模型仅验证流程回归，不代表真实嵌入向量检索质量、DeepSeek回答质量或提示注入防护效果。"


def load_dataset(path: Path) -> dict:
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("评估集必须包含非空 cases 列表")
    identifiers = set()
    for case in cases:
        if (
            not isinstance(case, dict) or not isinstance(case.get("id"), str)
            or case["id"] in identifiers or not isinstance(case.get("question"), str)
            or not case["question"].strip() or case.get("expected_status") not in STATUSES
        ):
            raise ValueError("评估用例需要唯一 id、question 和合法 expected_status")
        identifiers.add(case["id"])
    return dataset


def _valid_citations(answer: dict) -> bool:
    sources = answer.get("sources") or []
    if answer.get("retrieval_status") != "matched":
        return not sources
    allowed = {source.get("number") for source in sources}
    tokens = re.findall(r"\[[0-9][^\]\n]*\]|【[0-9][^】\n]*】|［[0-9][^］\n]*］", answer.get("content", ""))
    return bool(tokens and sources) and all(
        re.fullmatch(r"\[[1-9][0-9]{0,2}\]", token)
        and int(token[1:-1]) in allowed
        for token in tokens
    )


def _record(case: dict, answer: dict, expected_ids: list[int], latency_ms: float, error=None) -> dict:
    status = answer.get("retrieval_status", "error")
    sources = answer.get("sources") or []
    return {
        "id": case["id"], "category": case.get("category", "custom"),
        "expected_status": case["expected_status"], "actual_status": status,
        "expected_document_ids": expected_ids,
        "actual_document_ids": sorted({source["document_id"] for source in sources}),
        "citation_valid": _valid_citations(answer),
        "refused": status == "no_match" and not sources and bool(answer.get("content", "").strip()),
        "latency_ms": round(latency_ms, 3), "error": error,
    }


def calculate_retrieval_metrics(records: list[dict], k: int = 10) -> dict:
    """Measure ranked retrieval independently of generation and citation validation.

    IDs must use the same granularity (chunk or document) on both sides. Duplicate
    results never fill rank slots. Service errors are misses, not correct refusals.
    """
    if type(k) is not int or k < 1:
        raise ValueError("k 必须为正整数")
    recalls, hits, reciprocal_ranks, false_positives = [], [], [], []
    for record in records:
        expected = set(record["expected_ids"])
        ranked = list(dict.fromkeys(record["ranked_ids"]))[:k] if not record.get("error") else []
        if expected:
            matches = expected.intersection(ranked)
            recalls.append(len(matches) / len(expected))
            hits.append(bool(matches))
            reciprocal_ranks.append(next((1 / rank for rank, identifier in enumerate(ranked, 1)
                                          if identifier in expected), 0))
        elif not record.get("error"):
            false_positives.append(bool(ranked))
    latencies = sorted(record["latency_ms"] for record in records)
    average = lambda values: round(statistics.mean(values), 4) if values else None
    return {
        "total": len(records), "k": k,
        "errors": sum(bool(record.get("error")) for record in records),
        "recall_at_k": average(recalls), "hit_at_k": average(hits),
        "mrr_at_k": average(reciprocal_ranks),
        "no_answer_false_positive_rate": average(false_positives),
        "latency_mean_ms": average(latencies),
        "latency_p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
    }


def calculate_metrics(records: list[dict]) -> dict:
    expected_retrieval = [record for record in records if record["expected_document_ids"]]
    hits = sum(bool(set(record["expected_document_ids"]) & set(record["actual_document_ids"])) for record in expected_retrieval)
    matched = [record for record in records if record["actual_status"] == "matched"]
    valid_citations = sum(record["citation_valid"] for record in matched)
    no_match = [record for record in records if record["expected_status"] == "no_match"]
    refusals = sum(record.get("refused", record["actual_status"] == "no_match" and not record["actual_document_ids"]) for record in no_match)
    passed = sum(
        record["expected_status"] == record["actual_status"]
        and not record.get("error")
        and (not record["expected_document_ids"] or bool(set(record["expected_document_ids"]) & set(record["actual_document_ids"])))
        and (record["actual_status"] != "matched" or record["citation_valid"])
        for record in records
    )
    latencies = sorted(record["latency_ms"] for record in records)
    return {
        "total": len(records), "passed": passed,
        "errors": sum(bool(record.get("error")) for record in records),
        "status_accuracy": round(sum(record["expected_status"] == record["actual_status"] for record in records) / len(records), 4) if records else None,
        "retrieval_expected": len(expected_retrieval), "retrieval_hits": hits,
        "retrieval_misses": len(expected_retrieval) - hits,
        "retrieval_hit_rate": round(hits / len(expected_retrieval), 4) if expected_retrieval else None,
        "citation_answers": len(matched), "citation_valid_answers": valid_citations,
        "citation_validity_rate": round(valid_citations / len(matched), 4) if matched else None,
        "no_match_expected": len(no_match), "no_match_refusals": refusals,
        "no_match_refusal_rate": round(refusals / len(no_match), 4) if no_match else None,
        "latency_mean_ms": round(statistics.mean(latencies), 3) if latencies else None,
        "latency_p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
    }


class _OfflineEmbeddings:
    def __init__(self, documents):
        self.documents = documents

    def embed_query(self, text):
        # Explicit lexical fake: this is not an approximation of cloud embeddings.
        return [float(sum(keyword in text for keyword in document["keywords"])) for document in self.documents]


class _OfflineStore:
    def __init__(self, vector_ids):
        self.vector_ids = vector_ids

    def query(self, collection, embedding, limit=8, *, version_ids=None):
        rows = [
            {"id": identifier, "distance": 0.1 if score else 0.95, "metadata": {}}
            for identifier, score in zip(self.vector_ids, embedding)
        ]
        return sorted(rows, key=lambda row: row["distance"])[:limit]


class _OfflineModel:
    def __init__(self, override=None):
        self.override = override

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        if "改写" in messages[0].content:
            request = json.loads(messages[-1].content)
            questions = [message["content"] for message in request["history"] if message["role"] == "user"]
            text = " ".join(questions + [request["question"]])[:1000]
        elif self.override is not None:
            text = self.override
        else:
            first = json.loads(messages[1].content.splitlines()[0])
            text = f"测试资料：{first['text'].splitlines()[0]}[{first['number']}]"
        return AIMessage(content=text)


def run_offline(dataset: dict) -> dict:
    if not dataset.get("synthetic") or not dataset.get("documents"):
        raise ValueError("offline 模式需要明确标注 synthetic 的合成 documents")
    # Only this process's settings bootstrap is affected; no .env is edited.
    test_environment = {
        "DATABASE_URL": "sqlite:///:memory:", "JWT_SECRET_KEY": "offline-evaluation-only",
        "JWT_EXPIRE_HOURS": "24", "JWT_ALGORITHM": "HS256",
    }
    with patch.dict(os.environ, test_environment):
        import app.models
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.database import Base
        from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion
        from app.models.users import User
        from app.schemas.ai import ChatRequest
        from app.services import rag_service

    profile = {"fingerprint": "synthetic-offline-v1", "collection_name": "synthetic_offline"}
    config = SimpleNamespace(
        RAG_ENABLED=True, RAG_CANDIDATES=8, RAG_TOP_K=4, RAG_MAX_DISTANCE=0.6,
        RAG_CONTEXT_CHARS=6000, RAG_HISTORY_CHARS=6000, RAG_QUERY_CHARS=1000,
        RAG_REQUEST_TIMEOUT_SECONDS=60,
    )
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="synthetic-evaluator", password="unused", name="合成测试", role="admin")
            db.add(user)
            db.flush()
            document_ids, vector_ids = {}, []
            for index, sample in enumerate(dataset["documents"], start=1):
                doc = KnowledgeDocument(title=sample["title"], status=sample.get("status", "published"), uploaded_by=user.id)
                db.add(doc)
                db.flush()
                version = KnowledgeVersion(
                    document_id=doc.id, version_number=1,
                    sha256=hashlib.sha256(sample["text"].encode()).hexdigest(),
                    original_name="synthetic.txt", storage_name=f"{index:032x}.txt",
                    size_bytes=len(sample["text"].encode()), status="ready",
                    embedding_profile=profile["fingerprint"], collection_name=profile["collection_name"],
                )
                db.add(version)
                db.flush()
                doc.active_version_id = version.id
                identifier = f"synthetic-{index}"
                db.add(KnowledgeChunk(version_id=version.id, chunk_index=0, text=sample["text"], section="合成测试", vector_id=identifier))
                document_ids[sample["key"]] = doc.id
                vector_ids.append(identifier)
            db.commit()
            records = []
            with patch.object(rag_service, "settings", config), patch.object(rag_service, "get_embedding_profile", return_value=profile):
                for case in dataset["cases"]:
                    expected = [document_ids[key] for key in case.get("expected_sources", [])]
                    started = time.perf_counter()
                    error = None
                    try:
                        request = ChatRequest(mode="knowledge", messages=[*case.get("history", []), {"role": "user", "content": case["question"]}])
                        answer = rag_service.knowledge_chat(
                            request, db, model=_OfflineModel(case.get("model_response")),
                            embeddings=_OfflineEmbeddings(dataset["documents"]), vector_store=_OfflineStore(vector_ids),
                        ).model_dump()
                    except Exception as exc:
                        answer = {}
                        error = type(exc).__name__
                    records.append(_record(case, answer, expected, (time.perf_counter() - started) * 1000, error))
    finally:
        engine.dispose()
    return {"mode": "offline", "synthetic": True, "scope": OFFLINE_SCOPE, "metrics": calculate_metrics(records), "results": records}


def run_live(dataset: dict, api_base_url: str) -> dict:
    if dataset.get("synthetic") is not False:
        raise ValueError("live 模式禁止使用合成评估集，请准备 synthetic=false 的真实规则评估集")
    endpoint = urlsplit(api_base_url)
    if (
        endpoint.scheme not in {"http", "https"} or not endpoint.hostname
        or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
        or (endpoint.scheme == "http" and endpoint.hostname not in {"127.0.0.1", "localhost", "::1"})
    ):
        raise ValueError("API 地址必须是本机 HTTP 或 HTTPS 地址，且不得带凭证和查询参数")
    token = os.environ.get("RAG_EVAL_TOKEN", "").strip()
    if not token:
        raise ValueError("live 模式需要通过环境变量 RAG_EVAL_TOKEN 提供已登录的 JWT")
    import httpx

    records = []
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        for case in dataset["cases"]:
            expected = case.get("expected_document_ids", [])
            if not isinstance(expected, list) or any(type(value) is not int or value <= 0 for value in expected):
                raise ValueError("expected_document_ids 必须是正整数列表")
            started, error, answer = time.perf_counter(), None, {}
            try:
                response = client.post(
                    api_base_url.rstrip("/") + "/api/ai/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"mode": "knowledge", "messages": [*case.get("history", []), {"role": "user", "content": case["question"]}]},
                )
                response.raise_for_status()
                envelope = response.json()
                if envelope.get("code") != 200:
                    error = f"business_{envelope.get('code', 'unknown')}"
                else:
                    answer = envelope["data"]
            except Exception as exc:
                error = type(exc).__name__
            records.append(_record(case, answer, expected, (time.perf_counter() - started) * 1000, error))
    return {"mode": "live", "synthetic": False, "scope": "人工标注的真实文档评估；数字引用有效性不等同事实正确性，答案仍需人工审核。", "metrics": calculate_metrics(records), "results": records}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--live", action="store_true", help="显式发起真实API请求，会产生模型费用；禁止使用默认合成集")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, help="可选：保存不含问题正文与密钥的JSON报告")
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        report = run_live(dataset, args.api_base_url) if args.live else run_offline(dataset)
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0 if report["metrics"]["passed"] == report["metrics"]["total"] else 1
    except (ValueError, OSError, KeyError, TypeError):
        # Do not echo file paths, server responses, JWTs or provider error text.
        print("评估配置无效：请检查文件格式；live 模式需真实、非合成评估集及 RAG_EVAL_TOKEN。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
