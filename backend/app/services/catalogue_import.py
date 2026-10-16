"""Reviewed edition metadata import. No full text, cloud calls, or stock creation."""

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.books import Book
from app.models.book_sources import BookSource
from app.schemas.book import BookCreateRequest


def canonical_isbn(value):
    if value is not None and not isinstance(value, str):
        raise ValueError("ISBN 必须是字符串")
    isbn = BookCreateRequest.normalize_isbn(value)
    if isbn and len(isbn) == 10:
        prefix = "978" + isbn[:9]
        total = sum(int(digit) * (1 if i % 2 == 0 else 3) for i, digit in enumerate(prefix))
        return prefix + str((-total) % 10)
    return isbn


class CatalogueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^/books/OL[0-9]+M$")
    work_id: str | None = Field(default=None, pattern=r"^/works/OL[0-9]+W$")
    title: str = Field(min_length=1, max_length=255)
    author: str = Field(min_length=1, max_length=255)
    isbn: str | None = None
    publisher: str | None = Field(default=None, max_length=255)
    publication_year: int | None = Field(default=None, ge=1, le=9999, strict=True)
    category: Literal["AI / Agent", "儿童图书", "历史图书"]
    languages: list[str] = Field(default_factory=list, max_length=10)
    subjects: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title", "author", "publisher", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("isbn", mode="before")
    @classmethod
    def validate_isbn(cls, value):
        return canonical_isbn(value)

    @field_validator("subjects", "languages")
    @classmethod
    def bounded_labels(cls, values):
        if any(not value.strip() or len(value) > 160 for value in values):
            raise ValueError("主题或语言字段无效")
        return list(dict.fromkeys(value.strip() for value in values))

    @property
    def fingerprint(self):
        encoded = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def book_values(self):
        return {"title": self.title, "author": self.author, "isbn": self.isbn,
                "publisher": self.publisher, "publication_year": self.publication_year,
                "category": self.category,
                "description": "主题标签：" + "、".join(self.subjects) if self.subjects else None}


def records_from_search(payload: dict, category: str):
    """Keep edition fields together; work-level ISBNs and dates must not leak in."""
    records, rejected = [], []
    for work in payload.get("docs", []):
        try:
            edition = work.get("editions", {}).get("docs", [])[0]
            isbn = None
            for candidate in edition.get("isbn", []):
                try:
                    isbn = canonical_isbn(candidate)
                    if isbn:
                        break
                except ValueError:
                    continue
            dates = edition.get("publish_date", [])
            years = {int(year) for value in dates for year in re.findall(r"\b[12][0-9]{3}\b", value)}
            record = CatalogueRecord(
                source_id=edition["key"], work_id=work.get("key"), title=edition["title"],
                author=" / ".join(work.get("author_name", [])), isbn=isbn,
                publisher=" / ".join(edition.get("publisher", [])) or None,
                publication_year=next(iter(years)) if len(years) == 1 else None,
                category=category, languages=edition.get("language", [])[:10],
                subjects=[v for v in work.get("subject", []) if isinstance(v, str) and 0 < len(v) <= 160][:20],
            )
            records.append(record)
        except (ValueError, KeyError, IndexError, TypeError):
            rejected.append({"work_id": work.get("key"), "reason": "版次、书名或作者字段缺失或无效"})
    return records, rejected


def import_records(db: Session, records: list[CatalogueRecord], *, dry_run=False):
    """Validate the whole batch before writing. Replays preserve administrator edits."""
    seen_sources, seen_isbns = set(), set()
    plans = []
    for item in records:
        if item.source_id in seen_sources or (item.isbn and item.isbn in seen_isbns):
            raise ValueError("批次内存在重复版次或 ISBN")
        seen_sources.add(item.source_id)
        if item.isbn:
            seen_isbns.add(item.isbn)
        source = db.scalar(select(BookSource).where(BookSource.source_id == item.source_id))
        if source:
            if source.fingerprint != item.fingerprint:
                raise ValueError(f"来源数据已变化，需人工核对：{item.source_id}")
            plans.append({"source_id": item.source_id, "book_id": source.book_id, "status": "unchanged"})
            continue
        matches = [item.isbn] if item.isbn else []
        if item.isbn and item.isbn.startswith("978"):
            digits = item.isbn[3:12]
            check = (-sum((10-i) * int(d) for i, d in enumerate(digits))) % 11
            matches.append(digits + ("X" if check == 10 else str(check)))
        if matches and db.scalar(select(Book.id).where(Book.isbn.in_(matches))) is not None:
            raise ValueError(f"ISBN 已有书目，需人工确认来源绑定：{item.isbn}")
        plans.append({"source_id": item.source_id, "book_id": None, "status": "create"})
    if dry_run:
        return plans
    try:
        for item, plan in zip(records, plans):
            if plan["status"] == "unchanged":
                continue
            book = Book(**item.book_values(), is_active=True)
            db.add(book)
            db.flush()
            db.add(BookSource(book_id=book.id, source_id=item.source_id,
                              source_url="https://openlibrary.org" + item.source_id,
                              metadata_json=item.model_dump(), fingerprint=item.fingerprint))
            plan.update(book_id=book.id, status="created")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return plans
