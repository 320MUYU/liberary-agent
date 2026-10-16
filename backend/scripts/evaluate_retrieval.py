"""Compare real administrator retrieval paths without invoking answer generation.

Explicit --live and a local JWT are required. Synthetic reports are labelled and
require --allow-synthetic. This command never uploads or publishes documents.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from scripts.evaluate_rag import calculate_retrieval_metrics


def validate_dataset(dataset, allow_synthetic=False):
    if not isinstance(dataset, dict) or type(dataset.get("synthetic")) is not bool:
        raise ValueError("评测集必须显式标记 synthetic 为 true 或 false")
    if dataset.get("synthetic") and not allow_synthetic:
        raise ValueError("合成语料需要显式指定 --allow-synthetic")
    if not isinstance(dataset.get("cases"), list) or not dataset["cases"]:
        raise ValueError("评测集需要非空 cases")
    seen = set()
    for case in dataset["cases"]:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str)
                or case["id"] in seen or not isinstance(case.get("question"), str)
                or not 1 <= len(case["question"].strip()) <= 1000
                or not isinstance(case.get("expected_document_ids"), list)
                or any(type(value) is not int or value < 1 for value in case["expected_document_ids"])):
            raise ValueError("用例需要唯一 id、有效问题和正整数 expected_document_ids")
        seen.add(case["id"])


def evaluate(dataset, search):
    report = {"mode": "live_retrieval", "synthetic": bool(dataset.get("synthetic")),
              "label_granularity": "document", "strategies": {},
              "scope": "检索指标按标注的文档计算；不衡量生成回答的正确性。无答案误召回表示仍返回候选证据，不等同于模型编造回答。"}
    for strategy in ("vector", "hybrid", "hybrid_rerank"):
        candidates, selected, statuses = [], [], []
        for case in dataset["cases"]:
            started = time.monotonic()
            error, data = None, {}
            try:
                response = search({"query": case["question"], "strategy": strategy, "limit": 4})
                if response.get("code") != 200:
                    raise ValueError("service error")
                data = response["data"]
                candidate_ids = [row["document_id"] for row in data["candidates"]]
                selected_ids = [row["document_id"] for row in data["results"]]
            except Exception:
                error, candidate_ids, selected_ids = "request_failed", [], []
            record = {"id": case["id"], "expected_ids": case["expected_document_ids"],
                      "latency_ms": round((time.monotonic() - started) * 1000, 2), "error": error}
            candidates.append({**record, "ranked_ids": candidate_ids})
            selected.append({**record, "ranked_ids": selected_ids})
            statuses.append(data.get("rerank_status"))
        report["strategies"][strategy] = {
            "candidate_metrics": calculate_retrieval_metrics(candidates, k=20),
            "final_metrics": calculate_retrieval_metrics(selected, k=4),
            "rerank_applied": statuses.count("applied"), "rerank_fallbacks": statuses.count("fallback"),
            "records": selected,
        }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if not args.live:
            raise ValueError("调用真实服务需要 --live")
        parsed = urlsplit(args.api_base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("API 地址无效")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("远程 API 必须使用 HTTPS")
        token = os.environ.get("RAG_EVAL_TOKEN", "")
        if not token:
            raise ValueError("请在本地环境变量 RAG_EVAL_TOKEN 中设置管理员登录凭证")
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        validate_dataset(dataset, args.allow_synthetic)
        with httpx.Client(timeout=65, trust_env=False, headers={"Authorization": f"Bearer {token}"}) as client:
            report = evaluate(dataset, lambda payload: client.post(
                args.api_base_url.rstrip("/") + "/api/admin/knowledge/search", json=payload).json())
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return int(any(item["final_metrics"]["errors"] for item in report["strategies"].values()))
    except (ValueError, OSError):
        print("评测未运行：请检查本地数据集、管理员凭证、API 地址及 --live/--allow-synthetic 参数。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
