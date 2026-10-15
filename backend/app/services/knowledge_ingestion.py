"""Durable SQL jobs, conditional leases and idempotent version-scoped vector writes."""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeJob, KnowledgeVersion
from app.services.embedding_service import DashScopeEmbeddings, get_embedding_profile
from app.services.knowledge_parser import parse_document
from app.services.knowledge_service import private_path
from app.services.vector_store import ChromaVectorStore


SAFE_FAILURE = "任务处理失败，请检查文档格式、向量服务和索引服务配置后重试"


def _claim(db: Session):
    now = datetime.now()
    # Exhausted workers that crashed cannot remain 'running' forever.
    exhausted = db.scalars(select(KnowledgeJob).where(
        KnowledgeJob.status == "running", KnowledgeJob.lease_expires_at <= now,
        KnowledgeJob.attempts >= settings.KNOWLEDGE_JOB_MAX_ATTEMPTS,
    )).all()
    for job in exhausted:
        job.status, job.error_message, job.lease_token = "failed", SAFE_FAILURE, None
        if job.kind == "index":
            version = db.get(KnowledgeVersion, job.version_id)
            if version:
                version.status, version.error_message = "failed", SAFE_FAILURE
    db.commit()
    eligible = or_(
        and_(KnowledgeJob.status == "queued", KnowledgeJob.next_attempt_at <= now),
        and_(KnowledgeJob.status == "running", KnowledgeJob.lease_expires_at <= now),
    )
    for identifier in db.scalars(select(KnowledgeJob.id).where(
        eligible, KnowledgeJob.attempts < settings.KNOWLEDGE_JOB_MAX_ATTEMPTS
    ).order_by(KnowledgeJob.id).limit(20)).all():
        token = uuid4().hex
        result = db.execute(update(KnowledgeJob).where(KnowledgeJob.id == identifier, eligible).values(
            status="running", lease_token=token, lease_expires_at=now + timedelta(seconds=settings.KNOWLEDGE_JOB_LEASE_SECONDS),
            attempts=KnowledgeJob.attempts + 1,
        ).execution_options(synchronize_session=False))
        db.commit()
        if result.rowcount:
            db.expire_all()
            return identifier, token
    return None


def _renew(db: Session, identifier: int, token: str) -> bool:
    # Call only between committed phases. Never commit stale, unvalidated ORM writes.
    db.rollback()
    result = db.execute(update(KnowledgeJob).where(
        KnowledgeJob.id == identifier, KnowledgeJob.status == "running", KnowledgeJob.lease_token == token,
        KnowledgeJob.lease_expires_at > datetime.now(),
    ).values(lease_expires_at=datetime.now() + timedelta(seconds=settings.KNOWLEDGE_JOB_LEASE_SECONDS)))
    db.commit()
    db.expire_all()
    return result.rowcount == 1


def _guard(db: Session, identifier: int, token: str):
    # Hold this row lock only during SQL writes, never during cloud/vector requests.
    job = db.scalar(select(KnowledgeJob).where(KnowledgeJob.id == identifier)
                    .with_for_update().execution_options(populate_existing=True))
    if not job or job.status != "running" or job.lease_token != token or job.lease_expires_at <= datetime.now():
        db.rollback()
        return None
    return job


def process_next_job(db: Session, *, embeddings=None, store=None) -> bool:
    claimed = _claim(db)
    if claimed is None:
        return False
    identifier, token = claimed
    store = store or ChromaVectorStore()
    completed_chunks = None
    try:
        job = db.get(KnowledgeJob, identifier)
        version = db.get(KnowledgeVersion, job.version_id)
        doc = db.get(KnowledgeDocument, version.document_id)
        if job.kind == "delete":
            store.delete_version(version.collection_name, version.id)
            if not _renew(db, identifier, token):
                return True
            private_path(version.storage_name).unlink(missing_ok=True)
        elif doc.status != "deleted":
            if embeddings is None:
                if get_embedding_profile()["fingerprint"] != version.embedding_profile:
                    raise ValueError("embedding profile changed")
                embeddings = DashScopeEmbeddings()
            if _guard(db, identifier, token) is None:
                return True
            version.status = "indexing"
            version.error_message = None
            db.commit()
            parsed = parse_document(
                private_path(version.storage_name), chunk_size=version.chunk_size,
                chunk_overlap=version.chunk_overlap, max_chars=settings.KNOWLEDGE_MAX_CHARS,
                max_pages=settings.KNOWLEDGE_MAX_PAGES,
            )
            if not _renew(db, identifier, token):
                return True
            if _guard(db, identifier, token) is None:
                return True
            # A version's file/parser configuration stays stable across task retries.
            existing = {chunk.chunk_index: chunk for chunk in db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == version.id))}
            for index, piece in enumerate(parsed):
                chunk = existing.get(index)
                if chunk is None:
                    chunk = KnowledgeChunk(version_id=version.id, chunk_index=index, vector_id=f"v{version.id}:c{index}", text=piece.text)
                    db.add(chunk)
                chunk.text, chunk.page, chunk.section = piece.text, piece.page, (piece.section or "")[:500] or None
            for index, chunk in existing.items():
                if index >= len(parsed):
                    db.delete(chunk)
            db.commit()
            # Clear leftovers from partial attempts before writing stable vector IDs.
            store.delete_version(version.collection_name, version.id)
            chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == version.id).order_by(KnowledgeChunk.chunk_index)).all()
            for offset in range(0, len(chunks), 10):
                if not _renew(db, identifier, token):
                    return True
                doc = db.get(KnowledgeDocument, version.document_id)
                if doc.status == "deleted":
                    break
                batch = chunks[offset:offset + 10]
                vectors = embeddings.embed_documents([chunk.text for chunk in batch])
                if not _renew(db, identifier, token):
                    return True
                store.upsert(version.collection_name, [chunk.vector_id for chunk in batch],
                             [chunk.text for chunk in batch], vectors,
                             [{"version_id": str(version.id), "chunk_id": str(chunk.id)} for chunk in batch])
            if not _renew(db, identifier, token):
                return True
            if db.get(KnowledgeDocument, version.document_id).status == "deleted":
                store.delete_version(version.collection_name, version.id)
            else:
                completed_chunks = len(chunks)
        else:
            # A crashed old worker may have written after a concurrent delete job.
            # Every recovered deleted index task cleans the version again.
            store.delete_version(version.collection_name, version.id)
        if not _renew(db, identifier, token):
            return True
        job = _guard(db, identifier, token)
        if job is None:
            return True
        if completed_chunks is not None:
            # Lock the document to serialize readiness with disable/delete/upload.
            doc = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == version.document_id).with_for_update().execution_options(populate_existing=True))
            if doc.status != "deleted":
                version.status, version.chunk_count, version.error_message = "ready", completed_chunks, None
        job.status, job.lease_token, job.lease_expires_at, job.error_message = "done", None, None, None
        db.commit()
    except Exception:
        db.rollback()
        if _renew(db, identifier, token):
            job = _guard(db, identifier, token)
            if job is None:
                return True
            # Automatic retries are delayed; administrators can retry a failed version immediately.
            job.status = "queued" if job.attempts < settings.KNOWLEDGE_JOB_MAX_ATTEMPTS else "failed"
            job.error_message = SAFE_FAILURE
            job.next_attempt_at = datetime.now() + timedelta(seconds=min(30 * 2 ** job.attempts, 300))
            job.lease_token, job.lease_expires_at = None, None
            if job.kind == "index":
                version = db.get(KnowledgeVersion, job.version_id)
                version.status, version.error_message = "failed", SAFE_FAILURE
            db.commit()
    return True
