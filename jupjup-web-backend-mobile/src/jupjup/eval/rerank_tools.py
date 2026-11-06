"""크로스 인코더 녹화(T33)와 live 지연 벤치마크(T31, T36).

두 기능 모두 optional extra `[rerank]`가 있어야 실제 모델을 쓴다. 이 모듈은 CLI에서만 import한다.
"""

from __future__ import annotations

import json
import resource
import shutil
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from jupjup.config import REPO_ROOT, RerankModelSettings, SearchSettings, Settings, apply_overrides
from jupjup.container import AppContainer, build_container
from jupjup.domain.errors import JupjupError
from jupjup.eval.ab import LatencyReport
from jupjup.eval.metrics import percentile
from jupjup.eval.schema import GoldenQuery, load_and_validate
from jupjup.providers.rerank import RecordingReranker, Reranker
from jupjup.providers.rerank_bge import BgeCrossEncoderReranker
from jupjup.search.cross_rerank import CrossRerankStage
from jupjup.search.service import SearchRequest
from jupjup.storage.db import create_db_engine
from jupjup.storage.seed import load_seed_file

GOLDEN = REPO_ROOT / "data" / "golden"

# 설계 4.11절 녹화 범위: 합집합 R_base 상위 50개와 계획별 상위 5개. 실제 창(최대 32)보다 넓다.
RECORD_N_GLOBAL = 50
RECORD_K_PLAN = 5
RECORD_N_MAX = 100

# 설계 4.9절 장치별 예산 (창 20쌍 기준, ms)
RERANK_BUDGET_MS = {"mps": 150.0, "cpu": 400.0}
SEARCH_BUDGET_MS = {"mps": 300.0, "cpu": 600.0}


class _Request(BaseModel):
    user_id: str
    query: str
    now: datetime
    filters: Any = None


def _requests(
    queries: Sequence[GoldenQuery],
    probes_path: Path | None,
) -> list[_Request]:
    rows = [_Request(user_id=q.user_id, query=q.query, now=q.now, filters=q.request_filters) for q in queries]
    if probes_path is not None and probes_path.exists():
        for line in probes_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                now = datetime.fromisoformat(row["now"])
                rows.append(_Request(user_id=row["user_id"], query=row["query"], now=now))
    return rows


def _seeded_container(settings: Settings, seeds: Path) -> AppContainer:
    container = build_container(settings, engine=create_db_engine(None))
    loaded = load_seed_file(seeds, container.repo, container.indexer, strict=True)
    if loaded.errors or loaded.rolled_back or loaded.embedding_pending:
        raise JupjupError("시드 적재에 실패했습니다", {"errors": [error.message for error in loaded.errors[:5]]})
    return container


def _recorded_settings(search: SearchSettings) -> Settings:
    return Settings(env="test", mode="recorded", db_path=Path(":memory:"), search=search)


class _CapturingReranker:
    """창 구성을 엿보기 위한 가짜 리랭커. 모든 쌍에 0을 돌려준다."""

    model_id = "capture"
    revision = "capture"
    is_replay = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def score_logits(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        return [0.0] * len(documents)


def _install_stage(container: AppContainer, reranker: Reranker, settings: RerankModelSettings, device: str) -> None:
    container.search.cross_stage = CrossRerankStage(
        reranker,
        settings,
        container.settings.search.relevance_v3.calibration,
        device=device,
    )


def _wide(settings: RerankModelSettings) -> RerankModelSettings:
    return settings.model_copy(
        update={
            "enabled": True,
            "n_global": RECORD_N_GLOBAL,
            "k_plan": RECORD_K_PLAN,
            "n_max": RECORD_N_MAX,
            "pre_threshold": 0.0,
            "timeout_ms": 10_000,
        }
    )


def _run_all(container: AppContainer, requests: Sequence[_Request]) -> Iterator[tuple[_Request, Any]]:
    for request in requests:
        yield (
            request,
            container.search.search(
                SearchRequest(
                    user_id=request.user_id,
                    query=request.query,
                    filters=request.filters,
                    limit=10,
                    now=request.now,
                )
            ),
        )


def record_rerank(
    *,
    output: Path,
    cache_dir: Path,
    device: str,
    force: bool,
    overrides: dict[str, Any] | None = None,
    seeds: Path = GOLDEN / "seeds.jsonl",
    queries: Path = GOLDEN / "queries.jsonl",
    lexicon_cases: Path = GOLDEN / "lexicon_cases.jsonl",
    challenge: Path = GOLDEN / "challenge_queries.jsonl",
    probes: Path = GOLDEN / "recorded_probes.jsonl",
) -> dict[str, Any]:
    """골든(dev+test)·challenge·probe 전체 질의의 넓은 창을 녹화한다.

    `force`가 없으면 기존 녹화본에 새 쌍만 덧붙인다 (녹화 갱신). 실패하면 기존 파일을 건드리지 않는다.
    """
    gs = load_and_validate(seeds, queries, lexicon_cases, challenge)
    search = apply_overrides(SearchSettings(), overrides or {})
    config = search.cross_rerank.model_copy(update={"device": device})
    requests = _requests(gs.queries, probes)
    container = _seeded_container(_recorded_settings(search), seeds)

    # 녹화 전에 예상 쌍 수를 센다 (같은 창 선택 규칙, 모델 호출 없음).
    capture = _CapturingReranker()
    _install_stage(container, capture, _wide(config), "capture")
    for _ in _run_all(container, requests):
        pass
    expected_pairs = sum(len(documents) for _, documents in capture.calls)
    print(f"녹화 예정: 질의 {len(requests)}개, 쌍 {expected_pairs}개 (중복 포함)", file=sys.stderr)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with suppress(FileNotFoundError):
        temporary.unlink()
    existing_rows = 0
    if output.exists() and not force:
        shutil.copyfile(output, temporary)
        existing_rows = sum(1 for line in temporary.read_text(encoding="utf-8").splitlines() if line.strip())
    started = time.perf_counter()
    try:
        live = BgeCrossEncoderReranker(config, cache_dir)
        live.warm_up()
        recorder = RecordingReranker(live, temporary, config.max_length)
        _install_stage(container, recorder, _wide(config), live.device)
        skipped = 0
        for request, result in _run_all(container, requests):
            if result.rerank_status not in {"scored", "skipped:empty_query", None}:
                raise JupjupError(
                    "녹화 중 리랭크가 건너뛰어졌습니다", {"query": request.query, "status": result.rerank_status}
                )
            skipped += result.rerank_status == "skipped:empty_query"
        if not temporary.exists():
            temporary.write_text("", encoding="utf-8")
        temporary.replace(output)
    except BaseException:
        with suppress(FileNotFoundError):
            temporary.unlink()
        raise
    rows = sum(1 for line in output.read_text(encoding="utf-8").splitlines() if line.strip())
    return {
        "output": str(output),
        "queries": len(requests),
        "expected_pairs": expected_pairs,
        "rows": rows,
        "added_rows": rows - existing_rows,
        "empty_query_skips": skipped,
        "bytes": output.stat().st_size,
        "device": live.device,
        "seconds": round(time.perf_counter() - started, 1),
    }


def _rss_mb() -> float:
    # macOS는 바이트, Linux는 KiB 단위다.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024


def bench_rerank(
    *,
    cache_dir: Path,
    devices: Sequence[str],
    max_lengths: Sequence[int],
    windows: Sequence[int],
    repeat: int,
    split: str = "dev",
) -> dict[str, Any]:
    """T31 스파이크: 실제 창 구성(dev 질의)으로 장치 × max_length × 창 크기별 리랭크 지연을 잰다."""
    gs = load_and_validate(
        GOLDEN / "seeds.jsonl",
        GOLDEN / "queries.jsonl",
        GOLDEN / "lexicon_cases.jsonl",
        GOLDEN / "challenge_queries.jsonl",
    )
    queries = [q for q in gs.queries if q.split == split]
    search = SearchSettings()
    container = _seeded_container(_recorded_settings(search), GOLDEN / "seeds.jsonl")
    capture = _CapturingReranker()
    widest = search.cross_rerank.model_copy(
        update={"enabled": True, "n_global": max(windows), "n_max": max(windows), "k_plan": 1, "pre_threshold": 0.0}
    )
    _install_stage(container, capture, widest, "capture")
    for _ in _run_all(container, _requests(queries, None)):
        pass
    calls = [(query, documents) for query, documents in capture.calls if documents]

    rows: list[dict[str, Any]] = []
    for device in devices:
        for max_length in max_lengths:
            rss_before = _rss_mb()
            config = search.cross_rerank.model_copy(update={"device": device, "max_length": max_length})
            model = BgeCrossEncoderReranker(config, cache_dir)
            model.warm_up()
            rss_after = _rss_mb()
            for window in windows:
                latencies: list[float] = []
                for _ in range(repeat):
                    for query, documents in calls:
                        started = time.perf_counter()
                        model.score_logits(query, documents[:window])
                        latencies.append((time.perf_counter() - started) * 1000)
                rows.append(
                    {
                        "device": model.device,
                        "max_length": max_length,
                        "window": window,
                        "calls": len(latencies),
                        "p50_ms": round(percentile(latencies, 50), 1),
                        "p95_ms": round(percentile(latencies, 95), 1),
                        "max_ms": round(max(latencies), 1),
                        "rss_peak_increase_mb": round(rss_after - rss_before, 1),
                    }
                )
                print(json.dumps(rows[-1], ensure_ascii=False), file=sys.stderr)
            del model
    return {"split": split, "queries": len(calls), "repeat": repeat, "rows": rows}


def bench_search(
    *,
    cache_dir: Path,
    embedding_cache_dir: Path,
    device: str,
    repeat: int,
    split: str = "dev",
    overrides: dict[str, Any] | None = None,
    scratch_dir: Path,
) -> LatencyReport:
    """T36 live 벤치마크: 같은 프로세스에서 A0(리랭커 끔)과 A1(켬)의 검색 전체 지연을 잰다."""
    gs = load_and_validate(
        GOLDEN / "seeds.jsonl",
        GOLDEN / "queries.jsonl",
        GOLDEN / "lexicon_cases.jsonl",
        GOLDEN / "challenge_queries.jsonl",
    )
    queries = [q for q in gs.queries if q.split == split]
    requests = _requests(queries, None)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    search_off = apply_overrides(SearchSettings(), {**(overrides or {}), "cross_rerank": {"enabled": False}})
    settings = Settings(
        env="test",
        mode="live",
        db_path=Path(":memory:"),
        search=search_off,
        bge_cache_dir=embedding_cache_dir,
        bge_device=device if device != "auto" else "auto",
        embedding_recording_path=scratch_dir / "bench_embeddings.jsonl",
    )
    container = _seeded_container(settings, GOLDEN / "seeds.jsonl")
    for _ in _run_all(container, requests[:5]):
        pass  # warm-up

    def run_arm() -> tuple[list[float], list[float], int]:
        totals: list[float] = []
        stages: list[float] = []
        skipped = 0
        for _ in range(repeat):
            for _, result in _run_all(container, requests):
                totals.append(result.timing_ms.get("total", 0.0))
                if "cross_rerank" in result.timing_ms:
                    stages.append(result.timing_ms["cross_rerank"])
                if result.rerank_status and result.rerank_status.startswith("skipped:"):
                    skipped += result.rerank_status != "skipped:empty_query"
        return totals, stages, skipped

    baseline_totals, _, _ = run_arm()
    rss_before = _rss_mb()
    config = search_off.cross_rerank.model_copy(update={"enabled": True, "device": device})
    model = BgeCrossEncoderReranker(config, cache_dir)
    model.warm_up()
    rss_after = _rss_mb()
    _install_stage(container, model, config, model.device)
    totals, stages, skipped = run_arm()
    resolved = model.device
    return LatencyReport(
        device=resolved,
        repeat=repeat,
        queries=len(requests),
        rerank_p50_ms=round(percentile(stages, 50), 1),
        rerank_p95_ms=round(percentile(stages, 95), 1),
        rerank_max_ms=round(max(stages, default=0.0), 1),
        search_p50_ms=round(percentile(totals, 50), 1),
        search_p95_ms=round(percentile(totals, 95), 1),
        search_max_ms=round(max(totals, default=0.0), 1),
        baseline_search_p95_ms=round(percentile(baseline_totals, 95), 1),
        rerank_budget_ms=RERANK_BUDGET_MS.get(resolved, RERANK_BUDGET_MS["cpu"]),
        search_budget_ms=SEARCH_BUDGET_MS.get(resolved, SEARCH_BUDGET_MS["cpu"]),
        skip_rate=round(skipped / len(totals), 6) if totals else 0.0,
        rss_increase_mb=round(rss_after - rss_before, 1),
        cpu_enabled=config.enabled_on_cpu,
    )
