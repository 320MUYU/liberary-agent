"""Chinese lexical recall. The SQL corpus, not this rebuildable cache, is durable."""

import logging
import re
import threading
import unicodedata
from weakref import WeakKeyDictionary

import jieba
from rank_bm25 import BM25L
from sqlalchemy import select

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion


jieba.setLogLevel(logging.WARNING)
_tokenizer = jieba.Tokenizer()
_stopwords = frozenset("的 了 呢 吗 啊 是 在 有 和 与 及 或 请 请问 我 你 我们 这个 那个 什么 怎么 如何 哪里 多少 多久 可以 能 是否 要 就 才".split())
_cache = WeakKeyDictionary()
_cache_lock = threading.RLock()


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    words = list(_tokenizer.cut_for_search(text, HMM=False))
    # Retain identifiers such as R-204 as a complete term as well as their parts.
    words += re.findall(r"[a-z0-9]+(?:[-_.][a-z0-9]+)+", text)
    return [word for word in words if word not in _stopwords
            and re.search(r"[a-z0-9\u3400-\u9fff]", word)]


class LexicalIndex:
    def __init__(self, documents: list[dict]):
        self.documents = documents
        self.tokens = [tokenize("\n".join([item["title"], item.get("section") or "", item["text"]]))
                       for item in documents]
        # BM25L keeps positive IDF in tiny corpora (including a single document).
        self.bm25 = BM25L(self.tokens) if self.tokens and any(self.tokens) else None

    def search(self, query: str, limit: int) -> list[dict]:
        words = list(dict.fromkeys(tokenize(query)))
        if not words or self.bm25 is None:
            return []
        scores = self.bm25.get_scores(words)
        rows = []
        for item, tokens, score in zip(self.documents, self.tokens, scores):
            overlap = set(words).intersection(tokens)
            if score <= 0 or not overlap:
                continue
            # A single punctuation-free character is too weak as independent evidence.
            strong = any(len(word) > 1 or word.isdigit() for word in overlap)
            rows.append({"id": item["id"], "bm25_score": float(score),
                         "coverage": len(overlap) / len(words), "strong_match": strong})
        return sorted(rows, key=lambda row: (-row["bm25_score"], row["id"]))[:limit]


def published_manifest(db, fingerprint: str, document_ids=None):
    return tuple(db.execute(select(
        KnowledgeVersion.id, KnowledgeVersion.chunk_count, KnowledgeDocument.title,
    ).join(KnowledgeDocument, KnowledgeVersion.document_id == KnowledgeDocument.id).where(
        KnowledgeDocument.status == "published",
        *([KnowledgeDocument.id.in_(document_ids)] if document_ids is not None else []),
        KnowledgeDocument.active_version_id == KnowledgeVersion.id,
        KnowledgeVersion.status == "ready",
        KnowledgeVersion.embedding_profile == fingerprint,
    ).order_by(KnowledgeVersion.id)).tuples().all())


def get_index(db, fingerprint: str, manifest) -> LexicalIndex:
    key = (fingerprint, manifest)
    engine = db.get_bind()
    with _cache_lock:
        cached = _cache.get(engine)
        if cached and cached[0] == key:
            return cached[1]
    version_ids = [item[0] for item in manifest]
    titles = {item[0]: item[2] for item in manifest}
    documents = []
    if version_ids:
        # Select scalars, never keep sessions or ORM objects in the shared cache.
        for row in db.execute(select(KnowledgeChunk.vector_id, KnowledgeChunk.version_id,
                                     KnowledgeChunk.text, KnowledgeChunk.section).where(
                                         KnowledgeChunk.version_id.in_(version_ids))):
            documents.append({"id": row.vector_id, "title": titles[row.version_id],
                              "text": row.text, "section": row.section})
    index = LexicalIndex(documents)
    with _cache_lock:
        _cache[engine] = (key, index)
    return index
