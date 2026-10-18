"""Import reviewed public snapshots through the existing knowledge lifecycle.

This module never fetches websites, infers official rules, or changes business
configuration. Validate the whole local batch before writing its first anchor.
"""

from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.common.exceptions import BusinessException
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion
from app.models.library_corpus import LibraryCorpusSource
from app.models.users import User
from app.services.knowledge_service import publish_document, retry_version, upload_document


class CorpusSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    title: str = Field(min_length=1, max_length=150)
    url: str = Field(max_length=2000)
    snapshot: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    published_at: date | None = None
    effective_at: date | None = None
    category: Literal["entry", "hours", "borrowing", "return", "space", "faq", "other"]

    @field_validator("url")
    @classmethod
    def official_url(cls, value):
        endpoint = urlsplit(value)
        if (endpoint.scheme != "https" or endpoint.hostname != "lib.hust.edu.cn"
                or endpoint.username or endpoint.password or endpoint.port not in {None, 443}):
            raise ValueError("来源必须为华中科技大学图书馆官方 HTTPS 页面")
        return value

    @field_validator("observed_at")
    @classmethod
    def zoned_observation(cls, value):
        if value.utcoffset() is None:
            raise ValueError("采集时间必须包含时区")
        return value


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    institution: Literal["华中科技大学图书馆"]
    scope: Literal["external_reference"]
    sources: list[CorpusSource] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_sources(self):
        if len({source.key for source in self.sources}) != len(self.sources):
            raise ValueError("同一清单内来源 key 不得重复")
        if len({source.url for source in self.sources}) != len(self.sources):
            raise ValueError("同一清单内来源 URL 不得重复")
        return self


def load_manifest(path):
    return CorpusManifest.model_validate(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def read_snapshot(source, root):
    root = Path(root).resolve()
    relative = Path(source.snapshot)
    path = (root / relative).resolve()
    if relative.is_absolute() or path == root or root not in path.parents or path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("快照文件必须位于指定目录内，且为 MD 或 TXT")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("单篇参考快照不得超过 2 MiB")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != source.sha256:
        raise ValueError("快照与来源清单的 SHA256 不一致")
    text = content.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("快照正文不能为空")
    return text


def render_reference(manifest, metadata, text):
    return (
        f"# {manifest.institution}｜{metadata['title']}\n\n"
        "资料性质：外部参考资料，不代表本系统办理规则；不代表原馆当前实时服务状态。\n"
        f"适用机构：{manifest.institution}\n官方来源：{metadata['url']}\n"
        f"采集时间：{metadata['observed_at']}\n"
        f"页面标注发布日期：{metadata.get('published_at') or '未注明'}\n"
        f"页面标注生效日期：{metadata.get('effective_at') or '未注明'}\n"
        f"原文快照 SHA256：{metadata['sha256']}\n\n"
        "以下内容按公开页面整理，仅去除网页导航和排版标记；以官方最新说明为准。\n\n"
        f"{text}\n"
    )


def _anchor(db, manifest, source, user_id):
    row = db.scalar(select(LibraryCorpusSource).where(
        LibraryCorpusSource.corpus_key == manifest.corpus_key,
        LibraryCorpusSource.source_key == source.key,
    ).with_for_update())
    if row is None:
        doc = KnowledgeDocument(title=f"{manifest.institution}｜{source.title}", uploaded_by=user_id)
        db.add(doc)
        db.flush()
        row = LibraryCorpusSource(corpus_key=manifest.corpus_key, source_key=source.key,
            document_id=doc.id, institution=manifest.institution, source_url=source.url,
            scope=manifest.scope, metadata_json={})
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.scalar(select(LibraryCorpusSource).where(
                LibraryCorpusSource.corpus_key == manifest.corpus_key,
                LibraryCorpusSource.source_key == source.key,
            ))
            if row is None:
                raise
    return row


async def sync_corpus(db, manifest, snapshot_root, user_id, *, apply=False, publish=False, retry_failed=False):
    if not apply and (publish or retry_failed):
        raise ValueError("发布及重试仅允许在 apply 模式使用")
    manifest = CorpusManifest.model_validate(manifest)
    snapshots = {source.key: read_snapshot(source, snapshot_root) for source in manifest.sources}
    admin = db.get(User, user_id)
    if admin is None or admin.role != "admin" or admin.status != 1:
        raise BusinessException("需要有效管理员身份", 403)
    existing = {row.source_key: row for row in db.scalars(select(LibraryCorpusSource).where(
        LibraryCorpusSource.corpus_key == manifest.corpus_key))} if inspect(db.get_bind()).has_table("library_corpus_sources") else {}
    # Reject conflicts across the entire batch before applying any of it.
    for source in manifest.sources:
        row = existing.get(source.key)
        if row:
            doc = db.get(KnowledgeDocument, row.document_id)
            if row.source_url != source.url or row.institution != manifest.institution or row.scope != manifest.scope:
                raise BusinessException("来源标识已关联不同地址或适用范围，请另建来源标识", 409)
            if doc is None or doc.status == "deleted":
                raise BusinessException("来源关联文档已删除，请由管理员核对", 409)
    records = []
    for source in manifest.sources:
        item = {"key": source.key, "source_url": source.url, "institution": manifest.institution,
                "scope": manifest.scope, "snapshot_sha256": source.sha256}
        if not apply:
            row = existing.get(source.key)
            records.append({**item, "document_id": row.document_id if row else None})
            continue
        row = _anchor(db, manifest, source, user_id)
        if row.source_url != source.url or row.institution != manifest.institution or row.scope != manifest.scope:
            raise BusinessException("来源标识关联冲突，请由管理员核对", 409)
        metadata = source.model_dump(mode="json")
        previous = row.metadata_json or {}
        if all(previous.get(key) == metadata.get(key) for key in ("sha256", "title", "url", "published_at", "effective_at")):
            metadata["observed_at"] = previous["observed_at"]
        text = render_reference(manifest, metadata, snapshots[source.key])
        doc = await upload_document(db, UploadFile(filename=f"{source.key}.md", file=io.BytesIO(text.encode("utf-8"))),
            f"{manifest.institution}｜{source.title}", user_id, row.document_id)
        row.metadata_json = metadata
        db.commit()
        version = db.get(KnowledgeVersion, doc.latest_version_id)
        if version.status == "failed" and retry_failed:
            version = retry_version(db, version.id)
        if publish and version.status == "ready":
            doc = publish_document(db, doc.id, version.id)
        records.append({**item, "document_id": doc.id, "document_status": doc.status,
            "version_id": version.id, "version_number": version.version_number,
            "version_status": version.status, "version_sha256": version.sha256,
            "active_version_id": doc.active_version_id, "chunks": version.chunk_count})
    return {"applied": apply, "corpus_key": manifest.corpus_key, "scope": manifest.scope, "records": records}
