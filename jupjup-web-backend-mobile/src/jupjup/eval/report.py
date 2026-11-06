"""평가 리포트 (JSON, Markdown). 사람이 실패 원인을 바로 볼 수 있게 쓴다 (설계서 3.4절)."""

from __future__ import annotations

from pathlib import Path

from jupjup.eval.harness import EvalReport, QueryResult


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    if float(v).is_integer() and abs(v) >= 1:
        return str(int(v))
    return f"{v:.3f}"


def _parsed_summary(r: QueryResult) -> str:
    p = r.parsed
    parts = []
    if p.time_range:
        parts.append(f"기간 {p.time_range.start.date()}~{p.time_range.end.date()}")
    if p.hard_platforms():
        parts.append("플랫폼 " + ",".join(p.hard_platforms()))
    if p.hard_content_types():
        parts.append("유형 " + ",".join(p.hard_content_types()))
    parts.append("kw " + ",".join(p.keywords) if p.keywords else "kw -")
    if p.corrections:
        parts.append("교정 " + ",".join(f"{c.from_}→{c.to}" for c in p.corrections))
    return "; ".join(parts)


def render_markdown(report: EvalReport, max_failures: int = 20) -> str:
    cfg = report.config
    g = report.gate
    lines: list[str] = []
    lines.append(f"# 줍줍 검색 평가 리포트 — mode={cfg.mode}, split={cfg.split}")
    lines.append("")
    lines.append(f"- 골든셋 상태: **{report.golden_status}**")
    lines.append(f"- 생성: {report.created_at.isoformat()} / git: {report.git_sha or '-'}")
    lines.append("- 규모: " + ", ".join(f"{k} {v}" for k, v in report.counts.items()))
    if cfg.search_overrides:
        lines.append(f"- search_overrides: `{cfg.search_overrides}`")
    lines.append(f"- 판정: **{'PASS' if g.passed else 'FAIL'}**")
    lines.append(
        "- 제품 품질 PASS 근거: "
        + ("사용 가능" if report.product_evidence.get("eligible") else "사용 불가")
        + f" — {report.product_evidence.get('reason', '-')}"
    )
    lines.append("")
    lines.append("## 합격 기준 (설계서 3.3.4절)")
    lines.append("")
    lines.append("| 지표 | 값 | 기준 | 충족 |")
    lines.append("|---|---|---|---|")
    for c in g.checks + g.regression:
        lines.append(f"| {c.name} | {_fmt(c.value)} | {c.op} {_fmt(c.threshold)} | {'O' if c.passed else 'X'} |")
    lines.append("")
    lines.append("## 전체 지표")
    lines.append("")
    lines.append("| 지표 | 값 |")
    lines.append("|---|---|")
    for k, v in report.overall.items():
        lines.append(f"| {k} | {_fmt(v)} |")
    for k, v in report.safety.items():
        lines.append(f"| {k} | {v} |")
    for k, v in report.perf.items():
        lines.append(f"| {k} (비결정적) | {v:.1f} |")
    lines.append("")
    lines.append("## review_status별 지표")
    lines.append("")
    lines.append(
        "| review_status | n | 순위 질의 | Recall@10 | MRR@10 | nDCG@10 | time exact | "
        "platform F1 | type F1 | keyword | 절대 | 회귀 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for status, metrics in report.by_review_status.items():
        gate = report.review_status_gates.get(status)
        regression = bool(gate and gate.regression and all(check.passed for check in gate.regression))
        lines.append(
            f"| {status} | {_fmt(metrics.get('n_queries'))} | {_fmt(metrics.get('n_ranked'))} | "
            f"{_fmt(metrics.get('recall@10'))} | {_fmt(metrics.get('mrr@10'))} | "
            f"{_fmt(metrics.get('ndcg@10'))} | {_fmt(metrics.get('time_exact'))} | "
            f"{_fmt(metrics.get('platform_f1'))} | {_fmt(metrics.get('content_type_f1'))} | "
            f"{_fmt(metrics.get('keyword_inclusion'))} | "
            f"{'O' if gate and all(check.passed for check in gate.checks) else 'X'} | "
            f"{'O' if regression else '-'} |"
        )
    lines.append("")
    lines.append("## filter-only browse 지표")
    lines.append("")
    lines.append("filter-only는 일반 Recall@10과 category minimum에서 제외합니다.")
    lines.append("")
    lines.append("| 지표 | 값 |")
    lines.append("|---|---|")
    for key, value in report.browse.items():
        lines.append(f"| {key} | {_fmt(value)} |")
    lines.append("")
    lines.append("## 카테고리별")
    lines.append("")
    lines.append("| 카테고리 | n | 순위 질의 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | Success@1 | 정답 빈 결과율 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for cat, m in report.by_category.items():
        ranked = m.get("n_ranked", 0) > 0
        cells = [_fmt(m[k]) if ranked else "-" for k in ("recall@5", "recall@10", "mrr@10", "ndcg@10", "success@1")]
        lines.append(
            f"| {cat} | {_fmt(m['n'])} | {_fmt(m['n_ranked'])} | "
            + " | ".join(cells)
            + f" | {_fmt(m.get('true_empty_rate'))} |"
        )
    lines.append("")
    lines.append("## 질의 이해")
    lines.append("")
    lines.append("| 지표 | 전체 | lexicon_cases | queries |")
    lines.append("|---|---|---|---|")
    u = report.understanding
    for k in (
        "time_exact",
        "time_iou",
        "platform_precision",
        "platform_recall",
        "platform_f1",
        "content_type_precision",
        "content_type_recall",
        "content_type_f1",
        "keyword_inclusion",
        "intent_accuracy",
    ):
        lines.append(f"| {k} | {_fmt(u.get(k))} | {_fmt(u.get('lexicon.' + k))} | {_fmt(u.get('queries.' + k))} |")
    if report.understanding_failures:
        lines.append("")
        lines.append(f"질의 이해 불일치 {len(report.understanding_failures)}건:")
        lines.append("")
        for f in report.understanding_failures[:30]:
            lines.append(f"- `{f['id']}` {f['text']} → {', '.join(f['problems'])}")
    lines.append("")
    lines.append(f"## 실패 질의 (상위 {max_failures}개 / 전체 {len(report.failures)}개)")
    lines.append("")
    lines.append("일반 질의의 Recall@10/Success@1, browse precision/필터 준수, 또는 negative 빈 결과 실패.")
    lines.append("")
    lines.append("| id | 질의 | 카테고리 | 해석 | 상위 5 | 정답 (등급) | R@10 | S@1 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in report.failures[:max_failures]:
        top5 = ", ".join(cid.split("_")[-1] for cid in r.ranked_ids[:5]) or "(빈 결과)"
        gold = ", ".join(f"{cid.split('_')[-1]}({g})" for cid, g in sorted(r.relevance.items())) or "(정답 없음)"
        pm = r.per_query_metrics
        lines.append(
            f"| {r.query_id} | {r.query} | {','.join(r.categories)} | {_parsed_summary(r)} | {top5} | {gold} | "
            f"{_fmt(pm.get('recall@10'))} | {_fmt(pm.get('success@1'))} |"
        )
    lines.append("")
    if not g.passed:
        lines.append("## 미달 사유")
        lines.append("")
        for reason in g.reasons:
            lines.append(f"- {reason}")
        lines.append("")
    return "\n".join(lines)


def write_report(report: EvalReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"eval_{report.config.mode}_{report.config.split}"
    jp = out_dir / f"{stem}.json"
    mp = out_dir / f"{stem}.md"
    jp.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    mp.write_text(render_markdown(report), encoding="utf-8")
    return jp, mp
