"""Read-only edition discovery. Reasons are metadata, never generated claims."""

import re
import time

from sqlalchemy import select

from app.config import settings
from app.models.books import Book
from app.models.book_sources import BookSource
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion, KnowledgeChunk
from app.services import book_service
from app.services.embedding_service import create_embeddings, get_embedding_profile
from app.services.lexical_retrieval import LexicalIndex
from app.services.rag_retrieval import retrieve, reciprocal_rank_fusion, source_rows, remaining
from app.services.vector_store import ChromaVectorStore


def public_book(book):
    data = book.model_dump(include={"id", "title", "author", "isbn", "publisher",
        "publication_year", "category", "available_copies", "total_copies", "is_active", "source"})
    return {**data, "match_reasons": [], "sources": [], "channels": []}


def topic_query(query):
    # Remove request wording, not subject words; the original query still goes to vectors.
    return re.sub(r"推荐|一些|相关的?|帮我|找|图书|书籍|的书|书$", " ", query).strip() or query


def refresh_books(db, books):
    """Checkpoint evidence is historical; publication and inventory are checked on every view."""
    db.rollback()
    refreshed = []
    for old in books:
        book = db.scalar(select(Book).where(Book.id == old["id"], Book.is_active.is_(True)))
        if book is None:
            continue
        current = public_book(book_service.book_response(db, book))
        current["channels"] = old.get("channels", [])
        current["match_reasons"] = old.get("match_reasons", [])
        for source in old.get("sources", []):
            valid = db.scalar(select(KnowledgeChunk.id).join(KnowledgeVersion,
                KnowledgeChunk.version_id == KnowledgeVersion.id).join(KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeVersion.document_id).join(BookSource,
                BookSource.knowledge_document_id == KnowledgeDocument.id).where(
                    BookSource.book_id == book.id, KnowledgeChunk.id == source["chunk_id"],
                    KnowledgeDocument.id == source["document_id"], KnowledgeDocument.status == "published",
                    KnowledgeDocument.active_version_id == KnowledgeVersion.id, KnowledgeVersion.status == "ready"))
            if valid is not None:
                current["sources"].append(source)
        refreshed.append(current)
    return refreshed


def discover_books(db, keyword, page=1, *, mode="auto", deadline=None,
                   config=None, embeddings=None, store=None):
    config = config or settings
    deadline = deadline if deadline is not None else time.monotonic() + 12
    remaining(deadline)
    total, exact = book_service.list_books_page(db, page, 6, keyword=keyword, is_active=True)
    if mode == "exact" or (mode == "auto" and total):
        books = []
        for book in exact:
            item = public_book(book)
            item["match_reasons"] = [f"{label}：{getattr(book, field)}" for field, label in
                [("title", "书名"), ("author", "作者"), ("isbn", "ISBN")]
                if keyword.casefold() in str(getattr(book, field) or "").casefold()]
            item["channels"] = ["exact"]
            books.append(item)
        return {"total": total, "books": books, "retrieval": {"mode": "exact", "status": "ok", "degraded": []}}

    started = time.monotonic()
    records = db.execute(select(Book, BookSource).outerjoin(BookSource, BookSource.book_id == Book.id)
        .where(Book.is_active.is_(True)).order_by(Book.id)).all()
    metadata = {}
    documents = {}
    for book, source in records:
        subjects = (source.metadata_json.get("subjects", []) if source else [])
        metadata[book.id] = {"category": book.category, "subjects": subjects}
        if source and source.knowledge_document_id:
            documents[source.knowledge_document_id] = book.id
    query = topic_query(keyword)
    lanes = []
    for field in ("category", "subjects"):
        index = LexicalIndex([{"id": str(identifier), "title": "", "text":
            " ".join(meta[field]) if isinstance(meta[field], list) else meta[field]}
            for identifier, meta in metadata.items()])
        hits = index.search(query, 100)
        lanes.append((field, [hit for hit in hits if hit["strong_match"]]))
    evidence = {}
    degraded = []
    rerank_status = "disabled"
    if not getattr(config, "RAG_ENABLED", False):
        degraded.append("knowledge_disabled")
    elif documents:
        try:
            profile = get_embedding_profile()
            if embeddings is None:
                try:
                    embeddings = create_embeddings(timeout=min(4, remaining(deadline)), max_retries=0)
                except Exception:
                    # The scoped retrieval still runs the lexical lane without an adapter.
                    embeddings = None
            store = store if store is not None else ChromaVectorStore(timeout=min(2, remaining(deadline) / 3))
            result = retrieve(db, [query], profile, config=config, embeddings=embeddings,
                store=store, deadline=deadline, document_ids=list(documents), allow_vector_fallback=True,
                strategy="hybrid_rerank" if getattr(config, "RERANK_ENABLED", False) else "hybrid")
            degraded.extend(result.degraded)
            rerank_status = result.rerank_status
            if rerank_status == "fallback":
                degraded.append("rerank_unavailable")
            db.rollback()
            published = source_rows(db, [r["id"] for r in result.rows], profile["fingerprint"], list(documents))
            ranked_books = []
            for row in result.rows:
                if row["id"] not in published:
                    continue
                chunk, version, document = published[row["id"]]
                book_id = documents[document.id]
                ranked_books.append({"id": str(book_id)})
                sources = evidence.setdefault(book_id, [])
                if len(sources) < 3:
                    sources.append({"book_id": book_id, "chunk_id": chunk.id, "document_id": document.id,
                        "title": document.title, "version": version.version_number, "page": chunk.page,
                        "section": chunk.section, "excerpt": chunk.text[:600], "channels": row["channels"]})
            lanes.append(("knowledge", ranked_books))
        except Exception:
            degraded.append("knowledge_unavailable")
    rows = reciprocal_rank_fusion(lanes, getattr(config, "RAG_RRF_K", 60))
    books = []
    for row in rows:
        identifier = int(row["id"])
        meta = metadata[identifier]
        reasons = []
        if "category" in row["channels"]:
            reasons.append("分类：" + meta["category"])
        if "subjects" in row["channels"]:
            reasons.append("主题标签：" + "、".join(meta["subjects"][:12]))
        books.append({"id": identifier, "match_reasons": reasons, "channels": row["channels"],
                      "sources": evidence.get(identifier, [])})
    # Refresh before pagination so withdrawn books cannot occupy a page slot.
    books = refresh_books(db, books)
    return {"total": len(books), "books": books[(page - 1) * 6:page * 6], "retrieval": {
        "mode": "topic", "status": "degraded" if degraded else "ok", "degraded": degraded,
        "rerank_status": rerank_status, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}}
