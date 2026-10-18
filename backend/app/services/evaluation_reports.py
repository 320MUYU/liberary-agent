"""Pure report identity, validation and human-review statistics shared with the CLI."""

import copy
import hashlib
import json
import math
import re
import statistics


def validate_report(report):
    """Check content binding and return a fresh, entirely pending review copy."""
    if not isinstance(report, dict):
        raise ValueError("报告必须是 JSON 对象")
    rows = report.get("results")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError("报告需要 1 至 5000 条回答")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("回答条目必须是对象")
        case_id = row.get("id")
        if (not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", case_id)
                or case_id.casefold() in seen):
            raise ValueError("题号须以字母或数字开头，可含 . _ : -，最多200字且忽略大小写后唯一")
        seen.add(case_id.casefold())
        if (not isinstance(row.get("question"), str) or not row["question"].strip()
                or type(row.get("answerable")) is not bool
                or type(row.get("contract_pass")) is not bool
                or type(row.get("citation_valid")) is not bool
                or type(row.get("abstained")) is not bool
                or not isinstance(row.get("answer"), dict)
                or not isinstance(row["answer"].get("content", ""), str)
                or "error" not in row or "expected_source_coverage" not in row
                or row.get("error") is not None and not isinstance(row["error"], str)):
            raise ValueError("回答、问题和自动评测字段无效")
        for field in ("prelude", "expected_facts"):
            values = row.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise ValueError("前序问题与预期事实必须为文本列表")
        for values in (row.get("previews", []), row.get("expected_evidence", []),
                       row["answer"].get("sources", [])):
            if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
                raise ValueError("证据与来源必须为对象列表")
        latency, coverage = row.get("latency_ms"), row.get("expected_source_coverage")
        if (type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0
                or coverage is not None and (type(coverage) not in (int, float)
                    or not math.isfinite(coverage) or not 0 <= coverage <= 1)):
            raise ValueError("耗时和来源覆盖率无效")
    try:
        encoded = json.dumps(report, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("报告不能超过10MB")
        identity = report_identity(report)
    except (TypeError, OverflowError) as exc:
        raise ValueError("报告不是有效的 JSON") from exc
    if report.get("report_id") != identity:
        raise ValueError("报告标识与回答或证据不匹配，内容可能已变更")
    clean = copy.deepcopy(report)
    for row in clean["results"]:
        row["review"] = {"status": "pending_human"}
    clean["metrics"] = summarize(clean["results"])
    clean["review_status"] = "pending_human"
    return clean


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


