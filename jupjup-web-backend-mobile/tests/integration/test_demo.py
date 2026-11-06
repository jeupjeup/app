"""dev 전용 웹 데모: 단일 페이지와 SearchService 연결."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from jupjup.config import Settings
from jupjup.container import AppContainer
from jupjup.demo import create_demo_app
from jupjup.demo.app import _demo_settings

NOW = "2026-10-15T12:00:00+09:00"


def test_demo_page_is_self_contained(golden_container: AppContainer) -> None:
    with TestClient(create_demo_app(container=golden_container)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "줍줍저장소" in html
    assert 'placeholder="기억나는 대로 말해보세요."' in html
    assert "u_alice" in html and "u_bob" in html and "u_carol" in html
    assert "2026-10-15T12:00+09:00" in html
    assert html.count('class="chip"') == 5
    assert "prefers-color-scheme: dark" in html and "@media (max-width: 760px)" in html
    assert "data.empty_state?.suggestions" in html
    assert "data.applied_relaxations" in html
    assert "item.relaxed" in html
    assert "data.browse" in html and "둘러보기 결과" in html
    assert "<link" not in html and "<script src=" not in html and "https://" not in html


@pytest.mark.parametrize("mode", ["recorded", "live"])
def test_demo_accepts_recorded_and_live_containers(golden_container: AppContainer, mode: str) -> None:
    settings = Settings(env="test", mode=mode)  # type: ignore[arg-type]
    alternate = replace(golden_container, settings=settings)
    with TestClient(create_demo_app(container=alternate)) as client:
        assert client.get("/").status_code == 200


@pytest.mark.parametrize("mode", ["mock", "recorded", "live"])
def test_demo_page_shows_server_runtime_mode(golden_container: AppContainer, mode: str) -> None:
    settings = Settings(env="test", mode=mode)  # type: ignore[arg-type]
    alternate = replace(golden_container, settings=settings)

    with TestClient(create_demo_app(container=alternate)) as client:
        html = client.get("/").text

    assert f"로컬 검색 데모 · {mode}" in html
    assert "로컬 검색 데모 · Mock" not in html


def test_live_demo_records_only_under_var() -> None:
    settings = _demo_settings(Settings(env="test", mode="live"))
    assert settings.embedding_recording_path is not None
    assert settings.embedding_recording_path.parent.name == "recordings"
    assert settings.embedding_recording_path.parent.parent.name == "var"
    assert settings.embedding_recording_path != settings.recordings_dir / "embeddings.bge-m3.jsonl"


def test_demo_search_returns_understanding_and_results(golden_container: AppContainer) -> None:
    with TestClient(create_demo_app(container=golden_container)) as client:
        response = client.post(
            "/demo/search",
            json={
                "query": "지난달 인스타에서 본 성수동 카페",
                "user_id": "u_alice",
                "now": NOW,
            },
        )
    assert response.status_code == 200, response.text
    data = response.json()
    understanding = data["understanding"]
    assert understanding["intent"] == "lookup"
    assert understanding["time_range"]["expression"] == "지난달"
    assert understanding["time_range"]["start"].startswith("2026-09-01")
    assert understanding["time_window"]["start"].startswith("2026-08-25")
    assert understanding["platforms"] == [{"value": "instagram", "label": "인스타그램", "strength": "hard"}]
    assert understanding["keywords"] == ["성수동", "카페"]
    assert understanding["semantic_query"] == "성수동 카페"
    top = data["results"][0]
    assert top["content_id"] == "c_alice_0001"
    assert top["platform_label"] == "인스타그램" and top["content_type_label"] == "게시물"
    assert top["summary"] and top["tags"] and top["reasons"] and top["score"] > 0
    assert data["timing_ms"]["total"] >= 0


def test_demo_empty_state(container_factory: Callable[..., AppContainer]) -> None:
    empty_container = container_factory()
    with TestClient(create_demo_app(container=empty_container)) as client:
        response = client.post(
            "/demo/search",
            json={"query": "성수동 카페", "user_id": "u_alice", "now": NOW},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["results"] == []
    assert data["empty_state"]["message"] == "다른 표현으로 다시 찾아볼까요?"
    assert data["empty_state"]["reason"] == "no_relevant_match"
    assert data["empty_state"]["suggestions"][0]["type"] == "rephrase"
    assert data["applied_relaxations"] == []


def test_demo_relevance_empty_state(golden_container: AppContainer) -> None:
    with TestClient(create_demo_app(container=golden_container)) as client:
        response = client.post(
            "/demo/search",
            json={"query": "양자역학 외계행성 세미나", "user_id": "u_alice", "now": NOW},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["results"] == []
    assert data["empty_state"]["message"] == "다른 표현으로 다시 찾아볼까요?"


def test_demo_marks_filter_only_browse(golden_container: AppContainer) -> None:
    with TestClient(create_demo_app(container=golden_container)) as client:
        response = client.post(
            "/demo/search",
            json={"query": "유튜브 영상", "user_id": "u_alice", "now": NOW},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["browse"] is True
    assert data["understanding"]["intent"] == "browse"
    assert data["results"]
    assert all(item["reasons"][0]["type"] == "browse" for item in data["results"])


def test_demo_empty_state_shows_suggestions_and_relaxations(container_factory: Callable[..., AppContainer]) -> None:
    empty_container = container_factory()
    with TestClient(create_demo_app(container=empty_container)) as client:
        response = client.post(
            "/demo/search",
            json={
                "query": "지난달 인스타에서 본 성수동 카페",
                "user_id": "u_alice",
                "now": NOW,
            },
        )
    data = response.json()
    assert data["empty_state"]["reason"] == "no_relevant_match"
    assert [suggestion["type"] for suggestion in data["empty_state"]["suggestions"]] == [
        "drop_filter",
        "drop_filter",
        "rephrase",
    ]
    assert data["applied_relaxations"] == []
