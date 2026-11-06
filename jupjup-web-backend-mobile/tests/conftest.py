from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jupjup.text.lexicon import Lexicon
from jupjup.text.tokenizer import KiwiTokenizer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=KST)  # 목요일 (골든셋 eval now)


@pytest.fixture(scope="session")
def lexicon() -> Lexicon:
    return Lexicon.load(DATA / "lexicon")


@pytest.fixture(scope="session")
def kiwi(lexicon: Lexicon) -> KiwiTokenizer:
    return KiwiTokenizer(lexicon)


@pytest.fixture
def now() -> datetime:
    return NOW


from collections.abc import Callable  # noqa: E402

from jupjup.config import Settings  # noqa: E402
from jupjup.container import AppContainer, build_container  # noqa: E402
from jupjup.storage.db import create_db_engine  # noqa: E402


def make_container(**overrides: object) -> AppContainer:
    settings = Settings(env="test", mode="mock", data_dir=DATA, db_path=":memory:", **overrides)  # type: ignore[arg-type]
    return build_container(settings, engine=create_db_engine(None))


@pytest.fixture
def container_factory() -> Callable[..., AppContainer]:
    return make_container


@pytest.fixture(scope="session")
def golden_container() -> AppContainer:
    """골든 시드를 적재·인덱싱한 컨테이너 (읽기 전용으로만 쓴다)."""
    from jupjup.storage.seed import load_seed_file

    c = make_container()
    rep = load_seed_file(DATA / "golden" / "seeds.jsonl", c.repo, c.indexer, strict=True)
    assert rep.errors == []
    return c


@pytest.fixture(scope="session")
def recorded_golden_container() -> AppContainer:
    """커밋된 bge-m3 녹화본으로 시드와 질의를 재생하는 통합 테스트 컨테이너."""
    from jupjup.storage.seed import load_seed_file

    settings = Settings(env="test", mode="recorded", data_dir=DATA, db_path=":memory:")
    c = build_container(settings, engine=create_db_engine(None))
    rep = load_seed_file(DATA / "golden" / "seeds.jsonl", c.repo, c.indexer, strict=True)
    assert rep.errors == []
    return c
