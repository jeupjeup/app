"""Cross-encoder window selection, safe single-flight execution, and text construction."""

from __future__ import annotations

import concurrent.futures
import hashlib
import itertools
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jupjup.config import CrossCalibrationSettings, RerankModelSettings
from jupjup.domain.errors import RerankCacheMiss
from jupjup.index.document import IndexDocument
from jupjup.providers.rerank import Reranker
from jupjup.query.understanding import ParsedQuery


class RerankText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    text_hash: str


def build_rerank_query(parsed: ParsedQuery) -> str | None:
    # residual_text is the original normalized query after temporal/platform/type spans and stop phrases are removed.
    text = " ".join((parsed.residual_text or parsed.semantic_text_original).split()).strip()
    if not text:
        text = " ".join(parsed.original_terms).strip()
    return text or None


def build_rerank_text(document: IndexDocument, max_chars: int) -> RerankText:
    fields = document.fields
    parts = (
        fields["title"],
        " ".join(document.tags_display),
        fields["summary"],
        document.detail_core,
        fields["user_note"],
        fields["body"],
    )
    text = "\n".join(part.strip() for part in parts if part.strip())[:max_chars]
    return RerankText(text=text, text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest())


class RerankWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    content_ids: list[str]
    truncated: bool = False
    reasons: dict[str, str] = Field(default_factory=dict)


class CrossRerankOutcome(BaseModel):
    status: Literal["scored", "skipped"]
    skip_reason: Literal["disabled", "timeout", "error", "busy", "empty_query", "cpu_disabled"] | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    logits: dict[str, float] = Field(default_factory=dict)
    latency_ms: float = 0.0
    device: str = "unknown"
    model_id: str = ""
    revision: str = ""


class SingleFlightExecutor:
    """At most one inference runs; timed-out work finishes in the background and keeps the executor busy."""

    def __init__(self) -> None:
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="cross-rerank")
        self._lock = threading.Lock()
        self._busy = False

    def run(
        self, function: Callable[[], list[float]], timeout_s: float
    ) -> tuple[Literal["ok", "timeout", "busy", "error"], list[float] | None]:
        with self._lock:
            if self._busy:
                return "busy", None
            self._busy = True
        future = self._pool.submit(function)

        def release(_: concurrent.futures.Future[list[float]]) -> None:
            with self._lock:
                self._busy = False

        future.add_done_callback(release)
        try:
            return "ok", future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            return "timeout", None
        except RerankCacheMiss:
            raise
        except Exception:  # provider exceptions become a safe v2 fallback
            return "error", None


def calibrate_cross(probability: float, settings: CrossCalibrationSettings) -> float:
    probability = max(0.0, min(1.0, probability))
    points = settings.points
    for (left_x, left_y), (right_x, right_y) in itertools.pairwise(points):
        if probability <= right_x:
            width = right_x - left_x
            if width == 0:
                return right_y
            ratio = (probability - left_x) / width
            return max(0.0, min(1.0, left_y + ratio * (right_y - left_y)))
    return points[-1][1]


class CrossRerankStage:
    def __init__(
        self,
        reranker: Reranker | None,
        settings: RerankModelSettings,
        calibration: CrossCalibrationSettings,
        executor: SingleFlightExecutor | None = None,
        *,
        device: str = "unknown",
    ) -> None:
        self.reranker = reranker
        self.settings = settings
        self.calibration = calibration
        self.executor = executor or SingleFlightExecutor()
        self.device = device

    def select_window(
        self,
        base: Mapping[str, float],
        plan_members: Mapping[str, Sequence[str]],
    ) -> RerankWindow:
        ordered = sorted(base, key=lambda content_id: (-base[content_id], content_id))
        reasons: dict[str, str] = {}
        selected: set[str] = set()
        for content_id in ordered:
            if base[content_id] >= self.settings.pre_threshold and len(selected) < self.settings.n_global:
                selected.add(content_id)
                reasons[content_id] = "global"
        for plan_id in sorted(plan_members):
            members = sorted(
                (content_id for content_id in plan_members[plan_id] if content_id in base),
                key=lambda content_id: (-base[content_id], content_id),
            )
            for content_id in members[: self.settings.k_plan]:
                selected.add(content_id)
                reasons.setdefault(content_id, f"plan:{plan_id}")
        ranked = sorted(selected, key=lambda content_id: (-base[content_id], content_id))
        truncated = len(ranked) > self.settings.n_max
        ranked = ranked[: self.settings.n_max]
        return RerankWindow(
            content_ids=ranked,
            truncated=truncated,
            reasons={content_id: reasons[content_id] for content_id in ranked},
        )

    def score(
        self,
        parsed: ParsedQuery,
        window: RerankWindow,
        documents: Mapping[str, IndexDocument],
    ) -> CrossRerankOutcome:
        started = time.perf_counter()
        if not self.settings.enabled:
            return self._skipped("disabled", started)
        if self.device in {"cpu", "cpu_disabled"} and not self.settings.enabled_on_cpu:
            return self._skipped("cpu_disabled", started)
        if self.reranker is None:
            return self._skipped("disabled", started)
        query = build_rerank_query(parsed)
        if not query:
            return self._skipped("empty_query", started)
        ids = [content_id for content_id in window.content_ids if content_id in documents]
        texts = [build_rerank_text(documents[content_id], self.settings.max_doc_chars).text for content_id in ids]

        def infer() -> list[float]:
            assert self.reranker is not None
            return self.reranker.score_logits(query, texts)

        # Recorded replay is a deterministic local lookup. CI load must not turn it into a timeout fallback.
        status: Literal["ok", "timeout", "busy", "error"]
        logits: list[float] | None
        if self.reranker.is_replay:
            logits = infer()
            status = "ok"
        else:
            status, logits = self.executor.run(infer, self.settings.timeout_ms / 1000)
        if status != "ok" or logits is None:
            return self._skipped("error" if status == "ok" else status, started)
        if len(logits) != len(ids):
            return self._skipped("error", started)
        raw = dict(zip(ids, (float(logit) for logit in logits), strict=True))
        scores = {
            content_id: calibrate_cross(1.0 / (1.0 + math.exp(-logit)), self.calibration)
            for content_id, logit in raw.items()
        }
        return CrossRerankOutcome(
            status="scored",
            scores=scores,
            logits=raw,
            latency_ms=(time.perf_counter() - started) * 1000,
            device=self.device,
            model_id=self.reranker.model_id,
            revision=self.reranker.revision,
        )

    def _skipped(
        self,
        reason: Literal["disabled", "timeout", "error", "busy", "empty_query", "cpu_disabled"],
        started: float,
    ) -> CrossRerankOutcome:
        return CrossRerankOutcome(
            status="skipped",
            skip_reason=reason,
            latency_ms=(time.perf_counter() - started) * 1000,
            device=self.device,
            model_id=self.reranker.model_id if self.reranker is not None else "",
            revision=self.reranker.revision if self.reranker is not None else "",
        )
