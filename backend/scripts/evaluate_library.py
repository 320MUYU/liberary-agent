"""Source-pinned RAG and unified-chat evaluation, with a separate human review stage."""

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.library_corpus import load_manifest, read_snapshot
from scripts.evaluate_rag import _valid_citations
from scripts.evaluate_retrieval import evaluate as evaluate_retrieval


def compact(value):
    return re.sub(r"\s+", "", value).casefold()


def validate_suite(suite, manifest, snapshot_root):
    if (not isinstance(suite, dict) or suite.get("schema_version") != 1
            or suite.get("synthetic") is not False or suite.get("corpus_key") != manifest.corpus_key
            or suite.get("split") not in {"calibration", "validation"}
            or suite.get("annotation_author") not in {"agent_assisted", "human"}
            or suite.get("annotation_review") not in {"pending_human", "human_reviewed"}):
        raise ValueError("评测集必须声明真实来源、分组和标注审核状态")
    if suite.get("source_hashes") != {source.key: source.sha256 for source in manifest.sources}:
        raise ValueError("评测集必须固定到当前来源清单的全部快照哈希")
    texts = {source.key: compact(read_snapshot(source, snapshot_root)) for source in manifest.sources}
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集需要非空 cases")
    seen = set()
    for case in cases:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"].strip()
                or case["id"] in seen or not isinstance(case.get("question"), str)
                or not 1 <= len(case["question"].strip()) <= 1000 or type(case.get("answerable")) is not bool
                or not isinstance(case.get("fact_group"), str) or not case["fact_group"].strip()
                or not isinstance(case.get("category"), str)):
            raise ValueError("用例需要唯一编号、问题、分类、事实组及布尔 answerable")
        seen.add(case["id"])
        expected, facts, evidence = (case.get(key) for key in ("expected_source_keys", "expected_facts", "evidence"))
        if (not isinstance(expected, list) or any(key not in texts for key in expected)
                or len(set(expected)) != len(expected) or not isinstance(facts, list)
                or any(not isinstance(fact, str) or not fact.strip() for fact in facts)
                or not isinstance(evidence, list)):
            raise ValueError("预期来源、事实及原文证据无效")
        if case["answerable"]:
            if not expected or not facts or not evidence:
                raise ValueError("有答案用例必须提供来源、预期事实和原文证据")
            covered = set()
            for item in evidence:
                if (not isinstance(item, dict) or item.get("source_key") not in expected
                        or not isinstance(item.get("quote"), str) or not item["quote"].strip()
                        or compact(item["quote"]) not in texts[item["source_key"]]):
                    raise ValueError("标注证据必须能在固定版本的来源快照中逐字核对")
                covered.add(item["source_key"])
            if covered != set(expected):
                raise ValueError("每个预期来源都需要原文证据")
            groups = case.get("expected_source_groups", [[key] for key in expected])
            if (not isinstance(groups, list) or not groups
                    or any(not isinstance(group, list) or not group or any(key not in expected for key in group) for group in groups)
                    or set(key for group in groups for key in group) != set(expected)):
                raise ValueError("可替代证据组必须完整覆盖预期来源")
        elif expected or facts or evidence or not case.get("abstention_reason"):
            raise ValueError("无答案用例须说明原因，不能捏造来源和标准事实")
        if (not isinstance(case.get("prelude", []), list) or len(case.get("prelude", [])) > 3
                or any(not isinstance(value, str) or not 1 <= len(value) <= 1000 for value in case.get("prelude", []))):
            raise ValueError("追问前序问题最多三条，每条不超过1000字")
    return suite


def validate_splits(first, second):
    if (first["corpus_key"] != second["corpus_key"] or first["source_hashes"] != second["source_hashes"]
            or {first["split"], second["split"]} != {"calibration", "validation"}):
        raise ValueError("调参集与验证集必须来自同一固定语料且分组不同")
    for field in ("id", "question", "fact_group"):
        left = {compact(case[field]) for case in first["cases"]}
        right = {compact(case[field]) for case in second["cases"]}
        if left & right:
            raise ValueError("调参集与验证集存在编号、问题或主要事实组重叠")


def validate_bindings(suite, report):
    if (report.get("applied") is not True or report.get("corpus_key") != suite["corpus_key"]
            or report.get("scope") != "external_reference"):
        raise ValueError("需要对应语料的真实入库报告")
    records = report.get("records", [])
    bound = {row["key"]: row for row in records}
    if len(bound) != len(records) or set(bound) != set(suite["source_hashes"]):
        raise ValueError("入库报告来源不完整或重复")
    for key, row in bound.items():
        if (row.get("snapshot_sha256") != suite["source_hashes"][key]
                or any(type(row.get(field)) is not int or row[field] < 1 for field in ("document_id", "version_id", "version_number"))
                or row.get("version_status") != "ready" or row.get("document_status") != "published"
                or row.get("active_version_id") != row["version_id"]):
            raise ValueError("来源未发布、版本不一致或快照不匹配")
    return bound


def extract_conversation_answer(view, request_id):
    turn = next((row for row in view.get("turns", []) if row.get("request_id") == request_id), None)
    if turn is None:
        raise ValueError("requested_turn_missing")
    if turn.get("reply"):
        return turn["reply"], {"task_types": [], "workflow_id": turn.get("workflow_id")}
    task = next((row for row in view.get("tasks", []) if row.get("workflow_id") == turn.get("workflow_id")), None)
    if task is None:
        raise ValueError("requested_task_missing")
    steps = task.get("steps", [])
    trace = {"workflow_id": task["workflow_id"], "task_types": [step.get("spec", {}).get("task_type") for step in steps],
             "task_status": task.get("status")}
    results = [step["result"] for step in steps if (step.get("result") or {}).get("retrieval_status") is not None]
    if len(results) != 1:
        raise ValueError("unexpected_interaction_or_answer_count")
    return results[0], trace


def make_record(case, answer, bound, previews, latency_ms, *, error=None, trace=None):
    sources = answer.get("sources") or []
    cited = {int(value) for value in re.findall(r"\[([1-9][0-9]{0,2})\]", answer.get("content", ""))}
    used = [source for source in sources if source.get("number") in cited]
    expected = {bound[key]["document_id"] for key in case["expected_source_keys"]}
    actual = {source.get("document_id") for source in used}
    groups = case.get("expected_source_groups", [[key] for key in case["expected_source_keys"]])
    coverage = sum(bool({bound[key]["document_id"] for key in group} & actual) for group in groups) / len(groups) if groups else None
    preview_by_id = {row["chunk_id"]: row for row in previews}
    pinned = {row["document_id"]: row["version_number"] for row in bound.values()}
    previews_valid = bool(used) and all(
        source.get("chunk_id") in preview_by_id
        and preview_by_id[source["chunk_id"]].get("document_id") == source.get("document_id")
        and preview_by_id[source["chunk_id"]].get("version") == source.get("version")
        and (source.get("document_id") not in pinned or source.get("version") == pinned[source["document_id"]])
        for source in used
    )
    used_chunks = {source.get("chunk_id") for source in used}
    supported_keys = {item["source_key"] for item in case["evidence"] if any(
        row["chunk_id"] in used_chunks and row.get("document_id") == bound[item["source_key"]]["document_id"]
        and compact(item["quote"]) in compact(row.get("text", "")) for row in previews)}
    quote_coverage = sum(bool(set(group) & supported_keys) for group in groups) / len(groups) if groups else None
    citation_valid = _valid_citations(answer) and len({row.get("number") for row in sources}) == len(sources)
    abstained = (not error and answer.get("retrieval_status") in {"no_match", "insufficient_evidence"}
                 and not sources and bool(answer.get("content", "").strip()))
    passed = not error and (abstained if not case["answerable"] else (
        answer.get("retrieval_status") == "matched" and citation_valid and previews_valid
        and coverage == 1 and quote_coverage == 1))
    return {"id": case["id"], "case_id": case["id"], "category": case["category"], "question": case["question"],
        "prelude": case.get("prelude", []), "answerable": case["answerable"],
        "expected_facts": case["expected_facts"], "expected_evidence": case["evidence"],
        "expected_document_ids": sorted(expected), "cited_document_ids": sorted(value for value in actual if type(value) is int),
        "expected_source_groups": groups,
        "expected_source_coverage": coverage, "evidence_quote_coverage": quote_coverage,
        "citation_valid": citation_valid, "previews_valid": previews_valid, "abstained": bool(abstained),
        "contract_pass": bool(passed), "latency_ms": round(latency_ms, 2), "error": error,
        "answer": answer, "previews": previews, "trace": trace or {}, "review": {"status": "pending_human"}}


def summarize(records):
    average = lambda values: round(statistics.mean(values), 4) if values else None
    positive = [row for row in records if row["answerable"]]
    negative = [row for row in records if not row["answerable"]]
    matched = [row for row in records if row["answer"].get("retrieval_status") == "matched"]
    reviewed = [row for row in records if row.get("review", {}).get("status") == "reviewed"]
    latencies = sorted(row["latency_ms"] for row in records)
    return {"total": len(records), "errors": sum(bool(row["error"]) for row in records),
        "contract_passed": sum(row["contract_pass"] for row in records),
        "contract_pass_rate": average([row["contract_pass"] for row in records]),
        "cited_expected_source_coverage": average([row["expected_source_coverage"] for row in positive]),
        "citation_validity_rate": average([row["citation_valid"] for row in matched]),
        "abstention_expected": len(negative), "abstention_rate": average([row["abstained"] for row in negative]),
        "latency_mean_ms": average(latencies),
        "latency_p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
        "human_reviewed": len(reviewed), "human_review_coverage": len(reviewed) / len(records) if records else 0,
        "answer_accuracy": average([row["review"]["answer_correct"] for row in reviewed]),
        "citation_support_rate": average([row["review"]["citations_support"] for row in reviewed])}


def report_identity(report):
    content = copy.deepcopy(report)
    for key in ("report_id", "metrics", "review_status", "automatic_gate_pass"):
        content.pop(key, None)
    for row in content.get("results", []):
        row.pop("review", None)
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def apply_reviews(report, reviews):
    if reviews.get("report_id") != report.get("report_id") or report_identity(report) != report["report_id"]:
        raise ValueError("审核表与本次回答报告不匹配")
    records = {row["id"]: row for row in report["results"]}
    seen = set()
    for item in reviews.get("cases", []):
        if (item.get("id") not in records or item["id"] in seen or not isinstance(item.get("reviewer"), str)
                or not item["reviewer"].strip() or type(item.get("answer_correct")) is not bool
                or type(item.get("citations_support")) is not bool):
            raise ValueError("人工审核须指定唯一题号、审核人及明确的正确性判断")
        if records[item["id"]]["error"] and item["answer_correct"]:
            raise ValueError("服务错误不能审核为正确回答")
        seen.add(item["id"])
    for item in reviews.get("cases", []):
        records[item["id"]]["review"] = {"status": "reviewed", **{key: item.get(key) for key in (
            "reviewer", "answer_correct", "citations_support", "notes")}}
    report["metrics"] = summarize(report["results"])
    report["review_status"] = "reviewed" if report["metrics"]["human_review_coverage"] == 1 else "pending_human"
    return report


def request(client, url, payload=None):
    response = client.get(url) if payload is None else client.post(url, json=payload)
    response.raise_for_status()
    envelope = response.json()
    if envelope.get("code") != 200:
        raise ValueError(f"business_{envelope.get('code', 'unknown')}")
    return envelope["data"]


def answer_case(client, base, case, entrypoint):
    history, prelude_trace = [], []
    if entrypoint == "knowledge":
        for question in [*case.get("prelude", []), case["question"]]:
            history.append({"role": "user", "content": question})
            answer = request(client, base + "/api/ai/chat", {"mode": "knowledge", "messages": history})
            history.append({"role": "assistant", "content": answer["content"]})
        return answer, {"entrypoint": entrypoint}
    conversation_id = str(uuid4())
    request(client, base + "/api/conversations", {"request_id": conversation_id})
    path = base + "/api/conversations/" + conversation_id
    for question in [*case.get("prelude", []), case["question"]]:
        request_id = str(uuid4())
        view = request(client, path + "/messages", {"request_id": request_id, "text": question, "hint": "auto"})
        turn = next((row for row in view.get("turns", []) if row["request_id"] == request_id), {})
        task_id = turn.get("workflow_id")
        for _ in range(4):
            task = next((row for row in view.get("tasks", []) if row["workflow_id"] == task_id), {})
            if task.get("status") not in {"ready", "planning"}:
                break
            view = request(client, path + "/tasks/" + task_id + "/retry", {})
        try:
            answer, trace = extract_conversation_answer(view, request_id)
        except ValueError:
            if question != case["question"]:
                prelude_trace.append({"request_id": request_id, "status": "no_direct_answer"})
                continue
            raise
        prelude_trace.append({"request_id": request_id, **trace})
    return answer, {"entrypoint": entrypoint, "conversation_id": conversation_id, "turns": prelude_trace, **trace}


def check_publication(client, base, bound):
    docs = {row["id"]: row for row in request(client, base + "/api/admin/knowledge/documents")}
    for row in bound.values():
        doc = docs.get(row["document_id"], {})
        version = next((item for item in doc.get("versions", []) if item["id"] == row["version_id"]), {})
        if (doc.get("status") != "published" or doc.get("active_version_id") != row["version_id"]
                or version.get("status") != "ready" or version.get("version_number") != row["version_number"]):
            raise ValueError("publication_changed_or_missing")


def run_live(suite, bindings, client, base, *, entrypoint="conversation", retrieval=False, progress=None):
    bound = validate_bindings(suite, bindings)
    check_publication(client, base, bound)
    report = {"mode": "official_source_live", "synthetic": False, "split": suite["split"],
        "corpus_key": suite["corpus_key"], "source_hashes": suite["source_hashes"],
        "annotation_author": suite["annotation_author"], "annotation_review": suite["annotation_review"],
        "dataset_sha256": hashlib.sha256(json.dumps(suite, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "bindings": bindings["records"], "results": [], "publication_consistent": True,
        "scope": "真实官方来源上的自动流程与证据覆盖评测；题目为项目自建，不代表真实用户分布或馆方人工验收。"}
    if retrieval:
        mapped = {"synthetic": False, "cases": [{"id": case["id"],
            "question": case.get("retrieval_query", case["question"]),
            "expected_document_ids": [bound[key]["document_id"] for key in case["expected_source_keys"]]}
            for case in suite["cases"]]}
        report["retrieval"] = evaluate_retrieval(mapped, lambda payload: {
            "code": 200, "data": request(client, base + "/api/admin/knowledge/search", payload)})
        if progress:progress({"stage": "retrieval_complete"})
    consecutive_errors = 0
    entrypoints = ("knowledge", "conversation") if entrypoint == "both" else (entrypoint,)
    for entry in entrypoints:
        for case in suite["cases"]:
            started, answer, trace, previews, error = time.monotonic(), {}, {}, [], None
            try:
                answer, trace = answer_case(client, base, case, entry)
                for source in answer.get("sources", []):
                    previews.append(request(client, base + "/api/knowledge/sources/" + str(source["chunk_id"])))
            except Exception as exc:
                # Upstream responses, authorization headers and provider messages are never logged.
                error = type(exc).__name__
            row = make_record(case, answer, bound, previews, (time.monotonic() - started) * 1000, error=error, trace=trace)
            row["id"] = case["id"] + ":" + entry
            row["entrypoint"] = entry
            report["results"].append(row)
            if progress:progress({"id": row["id"], "passed": row["contract_pass"], "error": error, "latency_ms": row["latency_ms"]})
            consecutive_errors = consecutive_errors + 1 if error else 0
            if consecutive_errors >= 3:
                break
        if consecutive_errors >= 3:
            break
    report["expected_runs"] = len(suite["cases"]) * len(entrypoints)
    try:
        check_publication(client, base, bound)
    except Exception:
        report["publication_consistent"] = False
    report["metrics"] = summarize(report["results"])
    metrics = report["metrics"]
    report["automatic_gate_pass"] = bool(report["publication_consistent"]
        and len(report["results"]) == report["expected_runs"] and metrics["errors"] == 0
        and (metrics["contract_pass_rate"] or 0) >= 0.9
        and metrics["citation_validity_rate"] in {None, 1}
        and (metrics["abstention_rate"] is None or metrics["abstention_rate"] >= 0.9)
        and (not retrieval or ((report["retrieval"]["strategies"]["hybrid_rerank"]["final_metrics"]["recall_at_k"] or 0) >= 0.9)))
    report["review_status"] = "pending_human"
    report["report_id"] = report_identity(report)
    return report


def write_report(report, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 官方来源知识问答验收", "", f"报告编号：{report['report_id']}",
        f"人工审核状态：{report.get('review_status', 'pending_human')}", "",
        "自动通过仅表示引用、证据覆盖与接口契约满足要求；答案事实正确性仍须逐项审核。", "",
        "```json", json.dumps(report.get("metrics", {}), ensure_ascii=False, indent=2), "```", ""]
    for row in report["results"]:
        lines.extend([f"## {row['id']}", "", row["question"], "", "预期事实：" + "；".join(row["expected_facts"]), "",
            f"自动契约：{row['contract_pass']}；错误类型：{row['error']}", "", "实际回答：", "", row["answer"].get("content", "（无回答）"), ""])
        for preview in row["previews"]:
            lines.extend([f"来源：{preview.get('title', '')} / 文档 {preview['document_id']} / 版本 {preview['version']}", "",
                preview.get("text", ""), ""])
    path.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    template = {"report_id": report["report_id"], "cases": [{"id": row["id"], "reviewer": "",
        "answer_correct": None, "citations_support": None, "notes": ""} for row in report["results"]]}
    path.with_suffix(".reviews-template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "run"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--dataset", type=Path, required=True)
        command.add_argument("--other-split", type=Path)
        command.add_argument("--snapshot-root", type=Path, required=True)
        if name == "run":
            command.add_argument("--live", action="store_true")
            command.add_argument("--bindings", type=Path, required=True)
            command.add_argument("--api-base-url", default="http://127.0.0.1:8000")
            command.add_argument("--entrypoint", choices=("knowledge", "conversation", "both"), default="conversation")
            command.add_argument("--retrieval", action="store_true")
            command.add_argument("--output", type=Path, required=True)
    review = commands.add_parser("review")
    review.add_argument("--report", type=Path, required=True)
    review.add_argument("--reviews", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    read = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        if args.command == "review":
            report = apply_reviews(read(args.report), read(args.reviews))
            write_report(report, args.output)
            print(json.dumps(report["metrics"], ensure_ascii=False))
            return 0
        manifest = load_manifest(args.manifest)
        suite = validate_suite(read(args.dataset), manifest, args.snapshot_root)
        if args.other_split:
            other = validate_suite(read(args.other_split), manifest, args.snapshot_root)
            validate_splits(suite, other)
        if args.command == "check":
            print(json.dumps({"valid": True, "cases": len(suite["cases"]), "split": suite["split"], "annotation_review": suite["annotation_review"]}))
            return 0
        endpoint = urlsplit(args.api_base_url)
        if (not args.live or endpoint.scheme not in {"http", "https"} or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
                or (endpoint.scheme == "http" and endpoint.hostname not in {"127.0.0.1", "localhost", "::1"})):
            raise ValueError("真实调用需要 --live 及本机 HTTP 或 HTTPS API")
        token = os.environ.get("RAG_EVAL_TOKEN", "").strip()
        if not token:
            raise ValueError("需要 RAG_EVAL_TOKEN 管理员令牌")
        import httpx
        with httpx.Client(timeout=120, trust_env=False, follow_redirects=False,
                          headers={"Authorization": "Bearer " + token}) as client:
            report = run_live(suite, read(args.bindings), client, args.api_base_url.rstrip("/"),
                entrypoint=args.entrypoint, retrieval=args.retrieval,
                progress=lambda event: print(json.dumps(event), flush=True))
        write_report(report, args.output)
        print(json.dumps({"automatic_gate_pass": report["automatic_gate_pass"], "review_status": report["review_status"], "metrics": report["metrics"]}))
        return 0 if report["automatic_gate_pass"] else 1
    except (ValueError, OSError, KeyError, TypeError):
        print("评测配置或服务无效：请检查固定语料、分组、入库报告、API 和本地令牌；未生成通过结论。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
