"""Publish edition metadata through the existing private knowledge lifecycle."""

import io

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.books import Book
from app.models.book_sources import BookSource
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion
from app.models.users import User
from app.services.knowledge_service import (
    disable_document, publish_document, retry_version, upload_document,
)


def render_metadata(book: Book, source: BookSource):
    def line(value):
        return " ".join(str(value).split()) if value is not None else "未提供"

    metadata = source.metadata_json
    fields = {
        "书名": book.title, "作者或贡献者（来源署名）": book.author,
        "ISBN": book.isbn, "出版社": book.publisher, "出版年份": book.publication_year,
        "分类": book.category, "语言代码": "、".join(metadata.get("languages", [])) or None,
        "来源主题": "、".join(metadata.get("subjects", [])) or None,
        "书目说明": book.description,
        "来源版次": source.source_url, "本系统书目编号": book.id,
    }
    body = "\n".join(f"{label}：{line(value)}" for label, value in fields.items())
    return (f"# {line(book.title)}\n\n{body}\n\n"
            "资料类型：公开书目元数据，不含图书正文。主题标签不是章节摘要。\n"
            "适读年龄、难度与完整内容：未核实，不依据书名推断。\n"
            "馆藏及库存：本资料不记录库存或可借状态，请查询图书页面的实时馆藏；"
            "外部目录收录不代表本馆持有。\n")


async def sync_book(db: Session, book_id: int, user_id: int, *, publish=False, retry_failed=False):
    admin = db.get(User, user_id)
    if admin is None or admin.role != "admin" or admin.status != 1:
        raise BusinessException("需要有效管理员身份", 403)
    source = db.scalar(select(BookSource).where(BookSource.book_id == book_id).with_for_update())
    book = db.get(Book, book_id)
    if source is None or book is None:
        raise BusinessException("公开书目来源不存在", 404)
    doc = db.get(KnowledgeDocument, source.knowledge_document_id) if source.knowledge_document_id else None
    if doc and doc.status == "deleted":
        raise BusinessException("关联知识文档已删除，请由管理员处理关联关系", 409)
    if not book.is_active:
        if doc:
            disable_document(db, doc.id)
        else:
            db.rollback()
        return {"book_id": book_id, "document_id": doc.id if doc else None, "document_status": "disabled"}
    if doc is None:
        doc = KnowledgeDocument(title=book.title[:200], uploaded_by=user_id)
        db.add(doc)
        db.flush()
        source.knowledge_document_id = doc.id
        # Persist the association first: interrupted uploads reuse this same document.
        db.commit()
    text = render_metadata(book, source)
    doc = await upload_document(db, UploadFile(filename=f"book-{book.id}.md", file=io.BytesIO(text.encode("utf-8"))),
                                book.title[:200], user_id, doc.id)
    version = db.get(KnowledgeVersion, doc.latest_version_id)
    if version.status == "failed" and retry_failed:
        version = retry_version(db, version.id)
    if publish and version.status == "ready":
        doc = publish_document(db, doc.id, version.id)
    return {"book_id": book_id, "document_id": doc.id, "document_status": doc.status,
            "version_id": version.id, "version_status": version.status, "chunks": version.chunk_count}
