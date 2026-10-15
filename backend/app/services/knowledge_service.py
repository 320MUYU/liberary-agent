"""Private uploads and SQL-authoritative knowledge publication lifecycle."""

import hashlib
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeJob, KnowledgeVersion
from app.services.embedding_service import get_embedding_profile
from app.services.knowledge_parser import SUPPORTED_SUFFIXES


def private_path(storage_name: str) -> Path:
    # Never trust a database value as a relative/absolute path, even after an import.
    if not re.fullmatch(r"[0-9a-f]{32}\.(txt|md|docx|pdf)", storage_name):
        raise BusinessException("知识文档存储记录无效", 500)
    root = Path(settings.KNOWLEDGE_DIR).resolve()
    path = (root / storage_name).resolve()
    if path.parent != root:
        raise BusinessException("知识文档存储记录无效", 500)
    return path


def _document(db: Session, document_id: int, *, lock=False) -> KnowledgeDocument:
    query = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    if lock:
        query = query.with_for_update()
    doc = db.scalar(query.execution_options(populate_existing=True))
    if doc is None or doc.status == "deleted":
        raise BusinessException("知识文档不存在", 404)
    return doc


def list_documents(db: Session):
    return db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.status != "deleted")
        .options(selectinload(KnowledgeDocument.versions))
        .order_by(KnowledgeDocument.id.desc())
    ).all()


async def upload_document(db: Session, file: UploadFile, title: str, user_id: int, document_id: int | None = None):
    if not settings.RAG_ENABLED:
        raise BusinessException("知识库尚未启用，请联系管理员", 503)
    profile = get_embedding_profile()
    title = title.strip()
    if (not title and document_id is None) or len(title) > 200:
        raise BusinessException("文档标题长度应为 1 至 200 字", 422)
    original_name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES or len(original_name) > 255:
        raise BusinessException("请上传 TXT、MD、DOCX 或带文字层的 PDF，文件名不得超过255字", 422)
    storage_name = f"{uuid4().hex}{suffix}"
    path = private_path(storage_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("xb") as output:
            while block := await file.read(64 * 1024):
                size += len(block)
                if size > settings.KNOWLEDGE_MAX_BYTES:
                    raise BusinessException("知识文档超过大小限制，请拆分后上传", 413)
                digest.update(block)
                output.write(block)
        if size == 0:
            raise BusinessException("上传文件不能为空", 422)
        if document_id is None:
            doc = KnowledgeDocument(title=title, uploaded_by=user_id)
            db.add(doc)
            db.flush()
        else:
            doc = _document(db, document_id, lock=True)
        versions = db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.document_id == doc.id)).all()
        # Same-content retries do not allocate another file/job. A model/profile change
        # deliberately creates a new version and leaves the old publication intact.
        duplicate = next((v for v in versions if v.id == doc.latest_version_id and v.sha256 == digest.hexdigest() and v.embedding_profile == profile["fingerprint"]), None)
        if duplicate is not None:
            path.unlink(missing_ok=True)
            db.commit()
            return doc
        version = KnowledgeVersion(
            document_id=doc.id, version_number=max((v.version_number for v in versions), default=0) + 1,
            original_name=original_name, storage_name=storage_name, sha256=digest.hexdigest(), size_bytes=size,
            embedding_profile=profile["fingerprint"], collection_name=profile["collection_name"],
            chunk_size=settings.RAG_CHUNK_SIZE, chunk_overlap=settings.RAG_CHUNK_OVERLAP,
        )
        db.add(version)
        db.flush()
        doc.latest_version_id = version.id
        if title:
            doc.title = title
        db.add(KnowledgeJob(version_id=version.id))
        db.commit()
        db.expire(doc, ["versions"])
        return doc
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def publish_document(db: Session, document_id: int, version_id: int | None = None):
    doc = _document(db, document_id, lock=True)
    version_id = version_id or doc.latest_version_id
    version = db.get(KnowledgeVersion, version_id) if version_id else None
    if version is None or version.document_id != doc.id or version.id != doc.latest_version_id:
        raise BusinessException("只能发布该文档的最新版本", 409)
    if version.status != "ready":
        raise BusinessException("文档索引尚未就绪，请完成索引后发布", 409)
    doc.active_version_id = version.id
    doc.status = "published"
    db.commit()
    return doc


def disable_document(db: Session, document_id: int):
    doc = _document(db, document_id, lock=True)
    doc.status = "disabled"
    # Retain vectors for reversible re-publication; every read rechecks SQL state.
    db.commit()
    return doc


def retry_version(db: Session, version_id: int):
    version = db.get(KnowledgeVersion, version_id)
    if version is None:
        raise BusinessException("知识文档版本不存在", 404)
    _document(db, version.document_id, lock=True)
    if version.status != "failed":
        raise BusinessException("只能重试索引失败的版本", 409)
    running = db.scalar(select(KnowledgeJob).where(
        KnowledgeJob.version_id == version.id, KnowledgeJob.kind == "index", KnowledgeJob.status == "running",
        KnowledgeJob.lease_expires_at > datetime.now(),
    ))
    if running:
        raise BusinessException("索引任务仍在运行，请稍后重试", 409)
    # Retrying a failed immutable version must use its original embedding space.
    if get_embedding_profile()["fingerprint"] != version.embedding_profile:
        raise BusinessException("向量配置已变更，请重新上传文件以创建新版本", 409)
    for job in db.scalars(select(KnowledgeJob).where(
        KnowledgeJob.version_id == version.id, KnowledgeJob.kind == "index", KnowledgeJob.status.in_(["queued", "running"])
    )):
        job.status = "failed"
        job.lease_token = None
        job.lease_expires_at = None
    version.status = "queued"
    version.error_message = None
    db.add(KnowledgeJob(version_id=version.id))
    db.commit()
    return version


def delete_document(db: Session, document_id: int):
    doc = _document(db, document_id, lock=True)
    doc.status = "deleted"
    doc.active_version_id = None
    for version in db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.document_id == doc.id)):
        db.add(KnowledgeJob(version_id=version.id, kind="delete"))
    db.commit()


def get_source(db: Session, chunk_id: int):
    row = db.execute(
        select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument)
        .join(KnowledgeVersion, KnowledgeChunk.version_id == KnowledgeVersion.id)
        .join(KnowledgeDocument, KnowledgeVersion.document_id == KnowledgeDocument.id)
        .where(KnowledgeChunk.id == chunk_id, KnowledgeDocument.status == "published",
               KnowledgeDocument.active_version_id == KnowledgeVersion.id, KnowledgeVersion.status == "ready")
    ).first()
    if row is None:
        raise BusinessException("该来源已停用或不再是当前发布版本", 404)
    chunk, version, doc = row
    return {"chunk_id": chunk.id, "document_id": doc.id, "version": version.version_number,
            "title": doc.title, "page": chunk.page, "section": chunk.section, "text": chunk.text}
