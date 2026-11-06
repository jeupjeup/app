"""인덱스 문서 빌더 (설계서 5.3.1절, 5.8.5절)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from jupjup.domain.models import (
    Content,
    ContentBundle,
    ContentType,
    DetailTags,
    OriginalStatus,
    Platform,
    Snapshot,
    Summary,
    Tag,
    effective_tags,
)
from jupjup.text.lexicon import Lexicon
from jupjup.text.terms import unique_strings

IndexField = Literal["title", "tags_user", "tags_ai", "detail", "summary", "user_note", "body", "ocr", "author"]
INDEX_FIELDS: tuple[IndexField, ...] = (
    "title",
    "tags_user",
    "tags_ai",
    "detail",
    "summary",
    "user_note",
    "body",
    "ocr",
    "author",
)
BODY_MAX = 4000
OCR_MAX = 2000


class DocMeta(BaseModel):
    content_id: str
    user_id: str
    platform: Platform
    content_type: ContentType
    saved_at: datetime
    original_status: OriginalStatus


class IndexDocument(BaseModel):
    content_id: str
    user_id: str
    platform: Platform
    content_type: ContentType
    saved_at: datetime
    original_status: OriginalStatus
    fields: dict[IndexField, str]
    detail_core: str = ""  # 임베딩 doc 텍스트용 세부 태그 핵심
    tags_display: list[str] = []

    def meta(self) -> DocMeta:
        return DocMeta(
            content_id=self.content_id,
            user_id=self.user_id,
            platform=self.platform,
            content_type=self.content_type,
            saved_at=self.saved_at,
            original_status=self.original_status,
        )


class EmbeddingText(BaseModel):
    kind: Literal["doc", "chunk"]
    chunk_index: int
    text: str
    text_hash: str


class HardFilter(BaseModel):
    platforms: set[str] | None = None
    content_types: set[str] | None = None  # 이미 match_map으로 넓힌 저장물 유형 집합
    saved_from: datetime | None = None  # 포함
    saved_to: datetime | None = None  # 제외 (반열림)

    def accepts(self, doc_meta: DocMeta) -> bool:
        if self.platforms is not None and doc_meta.platform not in self.platforms:
            return False
        if self.content_types is not None and doc_meta.content_type not in self.content_types:
            return False
        if self.saved_from is not None and doc_meta.saved_at < self.saved_from:
            return False
        return not (self.saved_to is not None and doc_meta.saved_at >= self.saved_to)


def _flatten_detail(detail: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """(평탄화 전체, 임베딩용 핵심). 6.4절 평탄화 규칙."""
    if not detail:
        return [], []
    out: list[str] = []
    core: list[str] = []

    def strs(v: Any) -> list[str]:
        return [str(x) for x in v if isinstance(x, str | int | float)] if isinstance(v, list) else []

    for key in ("topics", "keywords", "purpose"):
        vals = strs(detail.get(key))
        out += vals
        if key != "keywords":
            core += vals
    for loc in detail.get("locations") or []:
        if isinstance(loc, dict):
            for k in ("name", "region"):
                if loc.get(k):
                    out.append(str(loc[k]))
            if loc.get("name"):
                core.append(str(loc["name"]))
    for ent in detail.get("entities") or []:
        if isinstance(ent, dict):
            if ent.get("name"):
                out.append(str(ent["name"]))
                core.append(str(ent["name"]))
            out += strs(ent.get("aliases"))
    academic = detail.get("academic") or {}
    if isinstance(academic, dict):
        out += strs(academic.get("authors"))
        for k in ("venue", "field"):
            if academic.get(k):
                out.append(str(academic[k]))
    media = detail.get("media") or {}
    if isinstance(media, dict) and media.get("channel"):
        out.append(str(media["channel"]))
    attrs = detail.get("attributes") or {}
    if isinstance(attrs, dict):
        out += [str(v) for _, v in sorted(attrs.items()) if isinstance(v, str)]
    return out, unique_strings(core)


def build_index_document(
    content: Content,
    snapshot: Snapshot | None,
    summary: Summary | None,
    tags: list[Tag],
    detail_tags: DetailTags | None,
) -> IndexDocument:
    eff = effective_tags(tags, content.hidden_tags)
    detail = detail_tags.effective() if detail_tags is not None else None
    flat, core = _flatten_detail(detail)
    fields: dict[IndexField, str] = {
        "title": content.title or "",
        "tags_user": " ".join(t.name for t in eff if t.source == "user"),
        "tags_ai": " ".join(t.name for t in eff if t.source == "ai"),
        "detail": " ".join(flat),
        "summary": summary.text if summary else "",
        "user_note": content.user_note or "",
        "body": (snapshot.text if snapshot else "")[:BODY_MAX],
        "ocr": ((snapshot.ocr_text or "") if snapshot else "")[:OCR_MAX],
        "author": content.author or "",
    }
    return IndexDocument(
        content_id=content.id,
        user_id=content.user_id,
        platform=content.platform,
        content_type=content.content_type,
        saved_at=content.saved_at,
        original_status=content.original_status,
        fields=fields,
        detail_core=" ".join(core)[:300],
        tags_display=[t.name for t in eff],
    )


def build_index_document_from_bundle(bundle: ContentBundle) -> IndexDocument:
    return build_index_document(bundle.content, bundle.snapshot, bundle.summary, bundle.tags, bundle.detail_tags)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, chunk_chars: int = 400, overlap: int = 80, max_chunks: int = 8) -> list[str]:
    if chunk_chars <= 0 or overlap < 0 or overlap >= chunk_chars:
        raise ValueError("chunk_chars > overlap >= 0 이어야 합니다")
    text = text.strip()
    if not text:
        return []
    step = chunk_chars - overlap
    chunks: list[str] = []
    start = 0
    while start < len(text) and len(chunks) < max_chunks:
        chunks.append(text[start : start + chunk_chars])
        if start + chunk_chars >= len(text):
            break
        start += step
    return chunks


def build_embedding_texts(
    doc: IndexDocument,
    chunk_chars: int = 400,
    overlap: int = 80,
    max_chunks: int = 8,
    lexicon: Lexicon | None = None,
    full_body: str | None = None,
) -> list[EmbeddingText]:
    """doc 벡터 1개 + 본문·OCR 청크 0~N개.

    full_body를 주면 4,000자 컷 전 스냅샷 본문을 청크에 쓴다 (없으면 인덱스 body 필드).
    """
    p_label = lexicon.platform_label(doc.platform) if lexicon else doc.platform
    t_label = lexicon.content_type_label(doc.content_type) if lexicon else doc.content_type
    f = doc.fields
    doc_text = "\n".join(
        part
        for part in (
            f["title"],
            f["summary"],
            f"태그: {' '.join(doc.tags_display)}" if doc.tags_display else "",
            doc.detail_core,
            f"유형: {t_label} 플랫폼: {p_label}",
        )
        if part
    )
    out = [EmbeddingText(kind="doc", chunk_index=0, text=doc_text, text_hash=text_hash(doc_text))]
    body = full_body if full_body is not None else f["body"]
    source = "\n".join(x for x in (body, f["ocr"]) if x)
    for i, chunk in enumerate(chunk_text(source, chunk_chars, overlap, max_chunks)):
        out.append(EmbeddingText(kind="chunk", chunk_index=i, text=chunk, text_hash=text_hash(chunk)))
    return out
