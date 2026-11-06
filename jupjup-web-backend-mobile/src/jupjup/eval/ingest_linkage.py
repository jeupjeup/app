"""검색 연결 지표 (설계 design_local_analyzer.md 7.4절, PRD 3.5.4절 "검색 연결 Recall@10 하락").

시드 200건을 두 갈래로 색인하고 같은 검색 골든 질의로 Recall@10, nDCG@10을 잰다.

- 사람 분석: ``load_seed_file``이 시드의 사람 요약·태그를 그대로 넣는다 (검색 기준선과 같다).
- 분석기: ``load_seed_file_for_analysis``가 스냅샷만 넣고 인제스트 파이프라인(주입한 분석기)으로 요약·태그를 만든다.

임베딩은 두 가지다.

- ``mock``: ``HashingEmbedder``. 녹화 없이 결정적이다 (회귀 감시·디버깅용).
- ``recorded``: 질의는 기존 ``embeddings.bge-m3.jsonl``, 분석기 문서·청크는 ``record-linkage``가 만든
  ``data/recordings/linkage/embeddings.bge-m3.<profile>.jsonl``에서 읽는다. 3.5.4절 판정은 이 값으로 한다.

검색 순위 로직과 검색 기준선 녹화는 건드리지 않는다. 이 모듈은 평가 전용이다.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from jupjup.config import REPO_ROOT, Settings
from jupjup.container import AppContainer, build_container, build_ingest_service
from jupjup.domain.errors import EmbeddingCacheMiss, JupjupError
from jupjup.eval.ingest_runtime import CapturingAnalyzer, MissRecord
from jupjup.eval.metrics import ndcg_at_k, recall_at_k
from jupjup.eval.schema import GoldenQuery, load_and_validate
from jupjup.ingest.analyzer import ContentAnalyzer
from jupjup.ingest.chunking import ChunkSettings
from jupjup.ingest.seeding import load_seed_file_for_analysis
from jupjup.search.service import SearchRequest
from jupjup.storage.db import create_db_engine
from jupjup.storage.seed import load_seed_file

GOLDEN = REPO_ROOT / "data" / "golden"
LINKAGE_RECORDINGS_DIR = REPO_ROOT / "data" / "recordings" / "linkage"
LINKAGE_K = 10
_FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)

LinkageEmbedder = Literal["mock", "recorded"]
# (embedder 모드, 임베딩 녹화 경로 또는 None) → 메모리 DB 컨테이너
LinkageContainerFactory = Callable[[LinkageEmbedder, Path | None], AppContainer]


def linkage_recording_file(profile_name: str, root: Path = LINKAGE_RECORDINGS_DIR) -> Path:
    return root / f"embeddings.bge-m3.{profile_name}.jsonl"


def default_linkage_container(embedder: LinkageEmbedder, recording_path: Path | None) -> AppContainer:
    settings = Settings(env="test", mode=embedder, db_path=Path(":memory:"), embedding_recording_path=recording_path)
    return build_container(settings, engine=create_db_engine(None))


class LinkageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedder: LinkageEmbedder
    query_split: Literal["dev", "test", "all"]
    n_queries: int
    seed_statuses: dict[str, int]
    human: dict[str, float]
    analyzer: dict[str, float]
    misses: list[MissRecord]

    def report_metrics(self) -> dict[str, float]:
        """``IngestEvalReport.search_linkage``(숫자 사전)용 값. 하락 = 사람 − 분석기 (양수면 나빠짐)."""
        recall_key, ndcg_key = f"recall@{LINKAGE_K}", f"ndcg@{LINKAGE_K}"
        return {
            "recorded_embedder": 1.0 if self.embedder == "recorded" else 0.0,
            "n_queries": float(self.n_queries),
            "seeds_succeeded": float(self.seed_statuses.get("succeeded", 0)),
            "seeds_not_succeeded": float(sum(v for k, v in self.seed_statuses.items() if k != "succeeded")),
            f"human_{recall_key}": self.human[recall_key],
            f"analyzer_{recall_key}": self.analyzer[recall_key],
            f"{recall_key}_drop": round(self.human[recall_key] - self.analyzer[recall_key], 6),
            f"human_{ndcg_key}": self.human[ndcg_key],
            f"analyzer_{ndcg_key}": self.analyzer[ndcg_key],
            f"{ndcg_key}_drop": round(self.human[ndcg_key] - self.analyzer[ndcg_key], 6),
        }


def _search_metrics(container: AppContainer, queries: Sequence[GoldenQuery]) -> tuple[dict[str, float], int]:
    recalls: list[float] = []
    ndcgs: list[float] = []
    for query in queries:
        result = container.search.search(
            SearchRequest(
                user_id=query.user_id,
                query=query.query,
                filters=query.request_filters,
                limit=LINKAGE_K,
                now=query.now,
            )
        )
        if result.browse or not query.relevance:
            continue  # 필터 전용 질의와 정답 없는 질의는 순위 지표가 없다 (검색 eval과 같은 규칙)
        ranked = [item.content_id for item in result.results]
        recalls.append(recall_at_k(ranked, query.relevance, LINKAGE_K))
        ndcgs.append(ndcg_at_k(ranked, query.relevance, LINKAGE_K))
    count = len(recalls)
    return (
        {
            f"recall@{LINKAGE_K}": round(sum(recalls) / count, 6) if count else 0.0,
            f"ndcg@{LINKAGE_K}": round(sum(ndcgs) / count, 6) if count else 0.0,
        },
        count,
    )


def _analyze_seeds(
    container: AppContainer,
    analyzer: CapturingAnalyzer,
    chunk_settings: ChunkSettings | None,
    seeds_path: Path,
) -> tuple[dict[str, int], list[MissRecord]]:
    """시드를 분석기로 다시 분석·색인한다. (잡 상태별 건수, 임베딩 녹화 미스로 실패한 시드)를 돌려준다.

    recorded 임베딩에서 분석기 문서·청크가 연결 녹화에 없으면 시드 잡이 ``EMBEDDING_CACHE_MISS``로 실패한다. 이것은
    분석기 품질이 아니라 녹화 문제이므로 미스로 따로 모은다 (T25f 검수 M1: 예전에는 조용히 R@10 하락으로 나왔다).
    """
    service = build_ingest_service(
        container,
        clock=lambda: _FIXED_NOW,
        worker_id="linkage-eval",
        concurrency=1,
        analyzer=analyzer,
        chunk_settings=chunk_settings,
    )
    report = load_seed_file_for_analysis(seeds_path, service, container.indexer, strict=True, inline=True)
    if report.rolled_back or report.errors:
        raise JupjupError("시드 분석 적재에 실패했습니다", {"errors": [e.message for e in report.errors[:5]]})
    misses: list[MissRecord] = []
    for job_id in report.job_ids:
        job = service.queue.get(job_id)
        if job.status == "failed" and (job.last_error or {}).get("code") == EmbeddingCacheMiss.code:
            misses.append(MissRecord(source_id=job.content_id, kind="embedding"))
    return dict(sorted(report.statuses.items())), sorted(misses, key=lambda miss: miss.source_id)


def run_linkage(
    analyzer: ContentAnalyzer,
    chunk_settings: ChunkSettings | None,
    *,
    embedder: LinkageEmbedder,
    linkage_file: Path | None = None,
    query_split: Literal["dev", "test", "all"] = "all",
    seeds_path: Path = GOLDEN / "seeds.jsonl",
    queries_path: Path = GOLDEN / "queries.jsonl",
    lexicon_path: Path = GOLDEN / "lexicon_cases.jsonl",
    container_factory: LinkageContainerFactory = default_linkage_container,
) -> LinkageResult:
    """사람 분석 인덱스와 분석기 인덱스의 검색 지표를 같은 질의로 잰다."""
    golden = load_and_validate(seeds_path, queries_path, lexicon_path)
    queries = [q for q in golden.queries if query_split == "all" or q.split == query_split]

    human_container = container_factory(embedder, None)
    loaded = load_seed_file(seeds_path, human_container.repo, human_container.indexer, strict=True)
    if loaded.errors or loaded.rolled_back:
        raise JupjupError("시드 적재에 실패했습니다", {"errors": [e.message for e in loaded.errors[:5]]})
    human, n_queries = _search_metrics(human_container, queries)

    capturing = analyzer if isinstance(analyzer, CapturingAnalyzer) else CapturingAnalyzer(analyzer)
    with tempfile.TemporaryDirectory(prefix="jupjup-linkage-") as scratch:
        merged: Path | None = None
        if embedder == "recorded":
            if linkage_file is None or not linkage_file.is_file():
                raise JupjupError(
                    "연결 지표 임베딩 녹화가 없습니다. `jupjup analyze record-linkage --profile <P>`로 먼저 녹화하세요",
                    {"path": "" if linkage_file is None else linkage_file.name},
                )
            # 질의는 기존 검색 녹화, 분석기 문서·청크는 연결 녹화에서 읽는다. 두 파일을 이어 붙인 임시본을 쓴다.
            merged = Path(scratch) / "embeddings.merged.jsonl"
            with merged.open("wb") as out:
                for source in (human_container.settings.recording_path, linkage_file):
                    with source.open("rb") as handle:
                        shutil.copyfileobj(handle, out)
                    out.write(b"\n")
        analyzer_container = container_factory(embedder, merged)
        statuses, embedding_misses = _analyze_seeds(analyzer_container, capturing, chunk_settings, seeds_path)
        analyzed, _ = _search_metrics(analyzer_container, queries)
    return LinkageResult(
        embedder=embedder,
        query_split=query_split,
        n_queries=n_queries,
        seed_statuses=statuses,
        human=human,
        analyzer=analyzed,
        misses=[*capturing.misses, *embedding_misses],
    )


def record_linkage(
    analyzer: ContentAnalyzer,
    chunk_settings: ChunkSettings | None,
    output: Path,
    *,
    seeds_path: Path = GOLDEN / "seeds.jsonl",
    force: bool = False,
    container_factory: Callable[[Path], AppContainer] | None = None,
) -> dict[str, object]:
    """분석기 출력으로 만든 시드 문서·청크 텍스트를 live bge-m3로 임베딩해 ``output``에 녹화한다 (7.4절 2번).

    분석기는 recorded(시드 분석 녹화)를 쓰는 것이 원칙이다. 녹화는 임시 파일에 쓰고 성공하면 바꿔 넣는다.
    """
    if output.exists() and not force:
        raise ValueError(f"연결 지표 녹화가 이미 있습니다: {output.name} (--force로 교체)")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with suppress(FileNotFoundError):
        temporary.unlink()

    def live_container(path: Path) -> AppContainer:
        settings = Settings(env="test", mode="live", db_path=Path(":memory:"), embedding_recording_path=path)
        return build_container(settings, engine=create_db_engine(None))

    factory = container_factory or live_container
    capturing = analyzer if isinstance(analyzer, CapturingAnalyzer) else CapturingAnalyzer(analyzer)
    try:
        container = factory(temporary)
        statuses, _ = _analyze_seeds(container, capturing, chunk_settings, seeds_path)
        if capturing.misses:
            raise JupjupError("시드 분석 녹화에 없는 요청이 있습니다", {"misses": len(capturing.misses)})
        if not temporary.exists():
            raise JupjupError("녹화된 임베딩이 없습니다", {})
        temporary.replace(output)
    except BaseException:
        with suppress(FileNotFoundError):
            temporary.unlink()
        raise
    rows = sum(1 for line in output.read_text(encoding="utf-8").splitlines() if line.strip())
    return {"output": output.name, "vectors": rows, "seed_statuses": statuses}
