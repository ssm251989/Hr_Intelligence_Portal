"""Per-tenant policy retrieval for HR Copilot (docs/HRMS_COMPLETE_SPEC.txt Part 12 B).

Documents HR uploads (and published KB articles) are chunked into `knowledge_chunks`,
tenant-scoped by RLS like every other table -- the index IS per-tenant by construction.
Ranking is BM25 over the chunks that share a query term: this installation's Postgres has
no pgvector extension available (see app/models/intelligence.py). `search()` is the only
reader, so moving to vector similarity later changes this file only.
"""

import math
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.intelligence import KnowledgeChunk, KnowledgeDocument
from app.platform.tenancy.context import TenantContext

_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "for", "and", "or", "on", "my", "i", "me", "what", "how", "do", "does", "can", "with", "at", "be", "it", "this", "that"}
CHUNK_CHARS = 900
_K1, _B = 1.4, 0.75


def tokens(text_value: str) -> list[str]:
    return [t for t in (m.group(0).lower() for m in _TOKEN.finditer(text_value or "")) if len(t) > 1 and t not in _STOP]


def chunk_text(body: str) -> list[tuple[Optional[str], str]]:
    """Paragraph-packed chunks of ~CHUNK_CHARS; a markdown-ish heading line starts a new
    chunk and is kept as that chunk's heading (shown in citations)."""
    chunks: list[tuple[Optional[str], str]] = []
    heading, buffer = None, []

    def _flush():
        text_value = "\n".join(buffer).strip()
        if text_value:
            chunks.append((heading, text_value))

    for para in re.split(r"\n\s*\n", body or ""):
        para = para.strip()
        if not para:
            continue
        first_line = para.splitlines()[0]
        if first_line.startswith("#") or (len(first_line) < 80 and first_line.isupper()):
            _flush()
            buffer = []
            heading = first_line.lstrip("# ").strip()
            para = "\n".join(para.splitlines()[1:]).strip()
            if not para:
                continue
        if sum(len(p) for p in buffer) + len(para) > CHUNK_CHARS and buffer:
            _flush()
            buffer = []
        buffer.append(para)
    _flush()
    return chunks


def ingest(db: Session, tenant: TenantContext, *, title: str, body: str, language: str = "en", source: str = "upload",
           source_ref: Optional[str] = None, audience_role_names: Optional[list[str]] = None, uploaded_by: Optional[str] = None) -> KnowledgeDocument:
    if not body or not body.strip():
        raise ValueError("document has no text")
    document = KnowledgeDocument(tenant_id=tenant.tenant_id, title=title, language=language, source=source, source_ref=source_ref,
                                 audience_role_names=audience_role_names or [], uploaded_by=uploaded_by)
    db.add(document)
    db.flush()
    for i, (heading, text_value) in enumerate(chunk_text(body)):
        db.add(KnowledgeChunk(tenant_id=tenant.tenant_id, document_id=document.id, ordinal=i, heading=heading, body=text_value))
    db.commit()
    db.refresh(document)
    return document


def reindex_kb_article(db: Session, tenant: TenantContext, article) -> Optional[KnowledgeDocument]:
    """Keeps a published KB article's copy in the index current (retire old copy, add new)."""
    for old in db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.source == "kb_article",
                                                   KnowledgeDocument.source_ref == str(article.id), KnowledgeDocument.status == "active").all():
        old.status = "retired"
    db.commit()
    if article.status != "published":
        return None
    return ingest(db, tenant, title=article.title, body=article.body, source="kb_article", source_ref=str(article.id))


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    document_title: str
    heading: Optional[str]
    text: str
    score: float


def search(db: Session, tenant: TenantContext, query_text: str, *, role_names: list[str], language: Optional[str] = None, k: int = 4) -> list[Hit]:
    terms = list(dict.fromkeys(tokens(query_text)))[:12]
    if not terms:
        return []
    docs = {d.id: d for d in db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant.tenant_id, KnowledgeDocument.status == "active").all()
            if not d.audience_role_names or set(d.audience_role_names) & set(role_names)}
    if not docs:
        return []
    candidates = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.tenant_id == tenant.tenant_id, KnowledgeChunk.document_id.in_(list(docs)))
        .filter(or_(*[KnowledgeChunk.body.ilike(f"%{t}%") for t in terms], *[KnowledgeChunk.heading.ilike(f"%{t}%") for t in terms]))
        .limit(400)
        .all()
    )
    if not candidates:
        return []
    total_chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.tenant_id == tenant.tenant_id, KnowledgeChunk.document_id.in_(list(docs))).count() or 1
    tokenised = {c.id: tokens(f"{c.heading or ''} {c.heading or ''} {c.body}") for c in candidates}
    avg_len = sum(len(v) for v in tokenised.values()) / len(tokenised)
    doc_freq = {t: sum(1 for v in tokenised.values() if t in v) for t in terms}
    hits = []
    for chunk in candidates:
        words = tokenised[chunk.id]
        score = 0.0
        for t in terms:
            tf = words.count(t)
            if not tf:
                continue
            idf = math.log(1 + (total_chunks - doc_freq[t] + 0.5) / (doc_freq[t] + 0.5))
            score += idf * tf * (_K1 + 1) / (tf + _K1 * (1 - _B + _B * len(words) / avg_len))
        if language and docs[chunk.document_id].language == language:
            score *= 1.1  # prefer the user's own language when both exist
        if score > 0:
            doc = docs[chunk.document_id]
            hits.append(Hit(str(chunk.id), str(doc.id), doc.title, chunk.heading, chunk.body, round(score, 4)))
    return sorted(hits, key=lambda h: h.score, reverse=True)[:k]


def confidence(hits: list[Hit], query_text: str) -> float:
    """0-1: share of the query's terms the best chunk actually contains (a crude but honest
    'did we find this?' signal; low -> hand over to a human)."""
    if not hits:
        return 0.0
    terms = set(tokens(query_text))
    if not terms:
        return 0.0
    best = set(tokens(f"{hits[0].heading or ''} {hits[0].text}"))
    return round(len(terms & best) / len(terms), 2)
