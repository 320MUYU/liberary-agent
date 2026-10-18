"""Capture eight selected public HUST library articles; no login, OCR, or crawling."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import httpx

BASE_URL = "https://lib.hust.edu.cn"
SOURCES = (
    ("entry-rules", 1419, 1413, "entry"),
    ("campus-card", 1423, 1387, "entry"),
    ("loan-permissions", 1426, 1387, "borrowing"),
    ("borrowing-service", 1424, 1387, "borrowing"),
    ("book-reservations", 1428, 1387, "borrowing"),
    ("renewals", 1427, 1387, "return"),
    ("seat-network-rules", 1449, 1399, "space"),
    ("seat-management", 1448, 1399, "space"),
)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.row = [], []
        self.cell = None
        self.in_table = False
        self.table_row = 0
        self.skipping = 0
        self.images = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skipping += 1
        if self.skipping:
            return
        if tag == "img":
            self.images += 1
        elif tag == "table":
            self.in_table, self.table_row = True, 0
            self.parts.append("\n\n")
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []
        elif self.cell is not None:
            if tag in {"p", "div", "br"}:
                self.cell.append(" ")
        elif re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "li", "br"} and not self.in_table:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skipping = max(0, self.skipping - 1)
            return
        if self.skipping:
            return
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.parts.append("| " + " | ".join(self.row) + " |\n")
            if self.table_row == 0:
                self.parts.append("| " + " | ".join("---" for _ in self.row) + " |\n")
            self.table_row += 1
        elif tag == "table":
            self.in_table = False
            self.parts.append("\n\n")
        elif self.cell is None and not self.in_table and (tag in {"p", "div", "li"} or re.fullmatch(r"h[1-6]", tag)):
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.skipping:
            if self.cell is not None:
                self.cell.append(value)
            elif not self.in_table or value.strip():
                self.parts.append(value)


def normalize_html(content):
    parser = _Text()
    parser.feed(content)
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"(?m)^#{1,6}\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text, parser.images


def source_metadata(item, key, parent_id, category, observed_at, sha256):
    if item.get("status") != 1 or item.get("deleteFlag") != 0:
        raise ValueError("公开来源已撤下，停止采集")
    published = item.get("publishTime")
    return {"key": key, "title": item["title"],
        "url": f"{BASE_URL}/index.html#/rtfDetailsBtnLink?id={item['id']}&pid={parent_id}",
        "snapshot": key + ".md", "sha256": sha256, "observed_at": observed_at,
        "published_at": published[:10] if published else None,
        "effective_at": None, "category": category}


def capture(output_dir, manifest_path):
    output_dir = Path(output_dir)
    raw_root, snapshots = output_dir / "raw", output_dir / "snapshots"
    raw_root.mkdir(parents=True, exist_ok=True)
    snapshots.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    sources, audit = [], []
    with httpx.Client(timeout=25, follow_redirects=False) as client:
        for key, identifier, parent, category in SOURCES:
            url = BASE_URL + f"/api/v1/Index/GetContentInfo?id={identifier}"
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
            item = payload.get("data")
            if payload.get("code") != 200 or not isinstance(item, dict) or item.get("id") != identifier:
                raise ValueError("公开文章响应与请求不一致")
            text, images = normalize_html(item.get("content") or "")
            if len(text.strip()) < 30:
                raise ValueError("来源无足够文字层，不能作为本批次正式文字资料")
            encoded = text.encode("utf-8")
            (raw_root / f"article-{identifier}.json").write_bytes(response.content)
            (snapshots / (key + ".md")).write_bytes(encoded)
            sources.append(source_metadata(item, key, parent, category, observed, hashlib.sha256(encoded).hexdigest()))
            audit.append({"key": key, "article_id": identifier, "fetch_url": url,
                "raw_sha256": hashlib.sha256(response.content).hexdigest(),
                "page_created_at": item.get("createtime"), "page_updated_at": item.get("updatetime"),
                "publication_field": item.get("publishTime"), "omitted_images": images,
                "normalization": "去除HTML排版；保留文字与表格列关系；不识别图片内容"})
    manifest = {"corpus_key": "hust-library", "institution": "华中科技大学图书馆",
                "scope": "external_reference", "sources": sources}
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "capture-report.json").write_text(json.dumps({"observed_at": observed, "sources": audit}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"sources": len(sources), "observed_at": observed, "omitted_images": sum(row["omitted_images"] for row in audit)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.output_dir, args.manifest), ensure_ascii=False))


if __name__ == "__main__":
    main()
