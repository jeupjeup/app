"""T7: build_index_document, build_embedding_texts."""

from __future__ import annotations

from typing import Any

import pytest

from jupjup.domain.models import ContentBundle, SeedRecord
from jupjup.index.document import (
    BODY_MAX,
    HardFilter,
    build_embedding_texts,
    build_index_document_from_bundle,
    chunk_text,
    text_hash,
)
from jupjup.text.lexicon import Lexicon
from tests.conftest import KST


def _bundle(**kw: Any) -> ContentBundle:
    d: dict[str, Any] = {
        "id": "c_alice_0001",
        "user_id": "u_alice",
        "platform": "instagram",
        "content_type": "post",
        "title": "성수 어니언 신메뉴",
        "author": "@onion",
        "saved_at": "2026-09-12T21:13:00+09:00",
        "original_status": "available",
        "user_note": "주말에 가보기",
        "snapshot": {"text": "성수동 어니언 가을 시즌 신메뉴", "ocr_text": "메뉴판 팡도르 7000"},
        "summary": {"text": "AI 요약", "version": 2, "source": "ai"},
        "tags": [
            {"name": "성수동", "source": "ai"},
            {"name": "빵집", "source": "ai"},
            {"name": "카페", "source": "ai"},
            {"name": "카페", "source": "user"},
            {"name": "주말데이트", "source": "user"},
        ],
        "hidden_tags": ["빵집"],
        "detail_tags": {
            "schema_version": 1,
            "topics": ["디저트"],
            "keywords": ["팡도르"],
            "purpose": ["데이트"],
            "locations": [{"name": "성수동", "region": "서울 성동구"}],
            "entities": [{"type": "place", "name": "어니언 성수", "aliases": ["onion"]}],
            "academic": {"authors": ["김지훈"], "venue": "학회지"},
            "media": {"channel": "채널A"},
            "attributes": {"mood": "조용함"},
        },
    }
    d.update(kw)
    return SeedRecord.model_validate(d).to_bundle()


def test_fields_and_hidden_tags_excluded() -> None:
    doc = build_index_document_from_bundle(_bundle())
    assert doc.fields["title"] == "성수 어니언 신메뉴"
    assert doc.fields["tags_user"] == "카페 주말데이트"
    assert doc.fields["tags_ai"] == "성수동"  # 빵집(숨김), 카페(사용자 태그와 중복) 제외
    assert "빵집" not in " ".join(doc.fields.values()).replace("팡도르", "")
    assert doc.fields["user_note"] == "주말에 가보기"
    assert doc.fields["author"] == "@onion"
    assert doc.fields["ocr"] == "메뉴판 팡도르 7000"
    for term in [
        "디저트",
        "팡도르",
        "데이트",
        "성수동",
        "서울 성동구",
        "어니언 성수",
        "onion",
        "김지훈",
        "학회지",
        "채널A",
        "조용함",
    ]:
        assert term in doc.fields["detail"], term


def test_user_summary_preferred() -> None:
    b = _bundle(summaries=[{"text": "사용자가 고친 요약", "source": "user", "version": 1}])
    assert build_index_document_from_bundle(b).fields["summary"] == "사용자가 고친 요약"


def test_user_patch_applied_to_detail() -> None:
    b = _bundle(detail_tags_user_patch={"purpose": None, "topics": ["브런치"]})
    detail = build_index_document_from_bundle(b).fields["detail"]
    assert "브런치" in detail and "데이트" not in detail


def test_deleted_original_still_indexed() -> None:
    doc = build_index_document_from_bundle(_bundle(original_status="deleted"))
    assert doc.original_status == "deleted" and doc.fields["body"]


def test_missing_parts() -> None:
    b = _bundle(title=None, snapshot=None, summary=None, tags=[], detail_tags=None, user_note=None, author=None)
    doc = build_index_document_from_bundle(b)
    assert all(v == "" for v in doc.fields.values())
    texts = build_embedding_texts(doc)
    assert [t.kind for t in texts] == ["doc"]


def test_body_cut() -> None:
    doc = build_index_document_from_bundle(_bundle(snapshot={"text": "가" * 5000}))
    assert len(doc.fields["body"]) == BODY_MAX


def test_embedding_doc_text(lexicon: Lexicon) -> None:
    doc = build_index_document_from_bundle(_bundle())
    texts = build_embedding_texts(doc, lexicon=lexicon)
    d = texts[0]
    assert d.kind == "doc" and d.chunk_index == 0
    assert "성수 어니언 신메뉴" in d.text and "AI 요약" in d.text and "태그: 카페 주말데이트 성수동" in d.text
    assert "유형: 게시물 플랫폼: 인스타그램" in d.text
    assert d.text_hash == text_hash(d.text)
    assert [t.kind for t in texts[1:]] == ["chunk"]
    assert "메뉴판 팡도르" in texts[1].text  # 본문 + OCR


@pytest.mark.parametrize(
    ("n", "expected_chunks"),
    [(0, 0), (1, 1), (400, 1), (401, 2), (720, 2), (721, 3), (3000, 8)],
)
def test_chunk_boundaries(n: int, expected_chunks: int) -> None:
    text = "".join(chr(0xAC00 + (i % 100)) for i in range(n))
    chunks = chunk_text(text, 400, 80, 8)
    assert len(chunks) == expected_chunks
    if chunks:
        assert chunks[0] == text[:400]
        assert all(len(c) <= 400 for c in chunks)
    if len(chunks) >= 2:
        assert chunks[1].startswith(text[320:400])  # 겹침 80자
    if chunks and n <= 400 + 320 * 7:
        assert "".join(c[:320] for c in chunks[:-1]) + chunks[-1] == text


def test_chunk_invalid_args() -> None:
    with pytest.raises(ValueError):
        chunk_text("abc", 100, 100)


def test_hard_filter() -> None:
    from datetime import datetime

    doc = build_index_document_from_bundle(_bundle()).meta()
    assert HardFilter().accepts(doc)
    assert HardFilter(platforms={"instagram"}).accepts(doc)
    assert not HardFilter(platforms={"youtube"}).accepts(doc)
    assert not HardFilter(content_types={"video"}).accepts(doc)
    assert HardFilter(saved_from=datetime(2026, 9, 12, tzinfo=KST), saved_to=datetime(2026, 9, 13, tzinfo=KST)).accepts(
        doc
    )
    assert not HardFilter(saved_to=datetime(2026, 9, 12, 21, 13, tzinfo=KST)).accepts(doc)  # 끝은 제외
    assert HardFilter(saved_from=datetime(2026, 9, 12, 21, 13, tzinfo=KST)).accepts(doc)  # 시작은 포함
