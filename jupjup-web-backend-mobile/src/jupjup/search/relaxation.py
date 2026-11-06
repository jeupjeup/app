"""원본 필터에서 독립적으로 파생하는 완화 계획 집합."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta

from jupjup.config import SearchSettings
from jupjup.query.spell import Vocabulary
from jupjup.query.temporal import TemporalParser
from jupjup.query.understanding import ParsedQuery
from jupjup.search.filters import ResolvedFilters
from jupjup.search.types import RelaxationName, RelaxationPlan
from jupjup.text.lexicon import Lexicon


def expanded_time_bounds(parsed: ParsedQuery, settings: SearchSettings) -> tuple[datetime, datetime] | None:
    if parsed.time_range is None:
        return None
    coarser = TemporalParser.coarser(parsed.time_range.granularity)
    days = settings.time_margins.get(coarser, settings.relaxation.fallback_margin_days)[
        1 if parsed.time_range.fuzzy else 0
    ]
    if parsed.time_range.granularity == "month":
        days = max(days, settings.relaxation.minimum_month_margin_days)
    return parsed.time_range.start - timedelta(days=days), parsed.time_range.end + timedelta(days=days)


class RelaxationPolicy:
    def __init__(self, settings: SearchSettings, lexicon: Lexicon) -> None:
        self.settings = settings
        self.lexicon = lexicon

    def plans(
        self,
        filters: ResolvedFilters,
        parsed: ParsedQuery,
        vocabulary: Vocabulary | None = None,
    ) -> list[RelaxationPlan]:
        """가변 상태를 공유하지 않는 strict/완화 계획을 만든다."""
        del vocabulary  # spelling plan은 신뢰도 높은 canonical_terms에 이미 반영된다.
        time_states: list[tuple[RelaxationName, ...]] = [()]
        window = filters.saved_window
        if window is not None and window.origin == "query" and not window.locked and parsed.time_range is not None:
            time_states.extend([("time_window_expanded",), ("time_filter_dropped",)])

        atomic: list[RelaxationName] = []
        if filters.platforms is not None and filters.platforms.origin == "query" and not filters.platforms.locked:
            atomic.append("platform_filter_dropped")
        if (
            filters.content_types is not None
            and filters.content_types.origin == "query"
            and not filters.content_types.locked
        ):
            atomic.append("content_type_filter_dropped")

        facet_sets: list[tuple[RelaxationName, ...]] = []
        for size in range(len(atomic) + 1):
            facet_sets.extend(itertools.combinations(atomic, size))

        plans: list[RelaxationPlan] = []
        seen: set[str] = set()
        for time_relaxations in time_states:
            for facet_relaxations in facet_sets:
                allowed = (*time_relaxations, *facet_relaxations)
                plan_filters = self._derive(filters, parsed, allowed)
                hard = plan_filters.to_hard_filter(self.lexicon)
                key = hard.model_dump_json()
                if key in seen:
                    continue
                seen.add(key)
                plan_id = "strict" if not allowed else "+".join(allowed)
                plan = RelaxationPlan(
                    plan_id=plan_id,
                    allowed_query_relaxations=allowed,
                    filters=plan_filters,
                )
                self._assert_request_locks(filters, plan)
                plans.append(plan)
        return plans

    def _derive(
        self,
        original: ResolvedFilters,
        parsed: ParsedQuery,
        allowed: tuple[RelaxationName, ...],
    ) -> ResolvedFilters:
        derived = original.model_copy(deep=True)
        allowed_set = set(allowed)
        if (
            derived.saved_window is not None
            and derived.saved_window.origin == "query"
            and parsed.time_range is not None
        ):
            if "time_filter_dropped" in allowed_set:
                derived.saved_window.dropped = True
            elif "time_window_expanded" in allowed_set:
                bounds = expanded_time_bounds(parsed, self.settings)
                if bounds is not None:
                    derived.saved_window.start, derived.saved_window.end = bounds
            else:
                derived.saved_window.start = parsed.time_range.start
                derived.saved_window.end = parsed.time_range.end
                derived.saved_window.dropped = False
        if "platform_filter_dropped" in allowed_set and derived.platforms is not None:
            derived.platforms.strength = "soft"
        if "content_type_filter_dropped" in allowed_set and derived.content_types is not None:
            derived.content_types.strength = "soft"
        return derived

    @staticmethod
    def _assert_request_locks(original: ResolvedFilters, plan: RelaxationPlan) -> None:
        for name in ("platforms", "content_types", "saved_window"):
            source = getattr(original, name)
            if source is None or not source.locked:
                continue
            target = getattr(plan.filters, name)
            if target is None or target != source:
                raise ValueError(f"요청 잠금이 계획에서 변경되었습니다: {name}")
