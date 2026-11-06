"""Stable JSON/Markdown output for ingest evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from jupjup.eval.ingest_harness import LINKAGE_DROP_LIMIT, IngestEvalReport

METRIC_LABELS: tuple[tuple[str, str], ...] = (
    ("schema_first_pass_rate", "스키마 첫 시도 준수율"),
    ("schema_final_pass_rate", "스키마 최종 준수율"),
    ("average_retries", "평균 재요청 횟수"),
    ("tag_precision", "대표 태그 Precision"),
    ("tag_recall", "대표 태그 Recall"),
    ("tag_f1", "대표 태그 F1"),
    ("entity_precision", "엔티티 Precision"),
    ("entity_recall", "엔티티 Recall"),
    ("entity_f1", "엔티티 F1"),
    ("location_f1", "장소 F1"),
    ("category_accuracy", "카테고리 정확도"),
    ("save_intent_accuracy", "저장 의도 정확도"),
    ("summary_key_fact_recall", "요약 핵심 사실 재현율"),
    ("unsupported_sentence_rate", "요약 비충실 문장 비율"),
    ("injection_resistance", "주입 저항"),
    ("input_tokens_per_item", "건당 입력 토큰"),
    ("output_tokens_per_item", "건당 출력 토큰"),
    ("cost_usd_per_item", "건당 추정 비용(USD)"),
    ("latency_p50_ms", "지연 p50(ms)"),
    ("latency_p95_ms", "지연 p95(ms)"),
    ("search_recall@10", "검색 연결 Recall@10"),
    ("search_ndcg@10", "검색 연결 nDCG@10"),
)


def _fmt(value: float | None) -> str:
    return "해당 없음" if value is None else f"{value:.6f}".rstrip("0").rstrip(".")


UNCALIBRATED = "판정기 미보정"


def _faithfulness_calibrated(report: IngestEvalReport) -> bool:
    return report.judge is not None and report.judge.faithfulness_calibrated


def _keyfact_calibrated(report: IngestEvalReport) -> bool:
    return report.judge is not None and report.judge.keyfact_calibrated


def _calibrated_label(report: IngestEvalReport) -> str:
    """보정 통과 표시. 준-사람 라벨(Q-LA3)이면 게이트를 읽는 자리마다 "사람 판정 아님"을 붙인다 (T25g 검수 L2)."""
    if report.judge is not None and report.judge.human_labels is False:
        return "보정 통과 (준-사람 라벨, 사람 판정 아님)"
    return "보정 통과"


def _local_note(report: IngestEvalReport, key: str, value: float | None) -> str:
    if value is None:
        return "해당 없음"
    if key == "unsupported_sentence_rate":
        if _faithfulness_calibrated(report):
            return f"1차 결정적 + 2차 판정기 결합 ({_calibrated_label(report)})"
        return f"결정적 1차 검사만 ({UNCALIBRATED})"
    if key == "summary_key_fact_recall":
        if _keyfact_calibrated(report):
            return f"판정기 값 ({_calibrated_label(report)})"
        return f"결정적 매처 ({UNCALIBRATED})"
    if key.startswith("latency"):
        return "녹화 시점 값 (지연 판단은 bench analyze)"
    if key == "cost_usd_per_item":
        return "로컬 모델"
    return "분석 출력이 있는 건 평균"


def _linkage_recorded(report: IngestEvalReport) -> bool:
    return report.search_linkage is not None and report.search_linkage.get("recorded_embedder") == 1.0


def render_ingest_markdown(report: IngestEvalReport) -> str:
    mock = report.config.mode == "mock"
    lines = [
        f"# 줍줍 인제스트 평가 리포트 — mode={report.config.mode}, split={report.config.split}",
        "",
        f"- 골든셋 상태: **{report.golden_status}**",
        f"- 판정: **{'PASS' if report.gate.passed else 'FAIL'}**",
        "- 생성 시각은 결정성 보장을 위해 기록하지 않음",
    ]
    if mock:
        lines.append("- 품질 지표는 MockAnalyzer 배선 검증에서 제품 품질 근거로 사용하지 않음")
    else:
        lines.extend(
            [
                (
                    f"- 판정기 `{report.judge.profile}` {_calibrated_label(report)}: "
                    "비충실 문장 비율은 1차·2차 결합 값이다"
                    if report.judge is not None and report.judge.faithfulness_calibrated
                    else f"- {UNCALIBRATED}: 비충실 문장 비율은 결정적 1차 검사 값이다"
                ),
                "- 판단은 recorded 결과로만 한다. live 출력은 실행마다 다를 수 있다",
            ]
        )
        if not _linkage_recorded(report):
            lines.append(
                "- 검색 연결 지표 미측정(recorded 아님): 이 판정은 3.5.4절의 검색 연결 Recall@10 하락 기준을 "
                "빼고 냈다. 채택 판단에는 `--linkage recorded` 리포트를 쓴다"
            )
    lines.extend(["", "## 3.5.2절 지표", "", f"| 지표 | 값 | {'mock 비고' if mock else '비고'} |", "|---|---:|---|"])
    for key, label in METRIC_LABELS:
        value = report.overall.get(key)
        if not mock:
            note = _local_note(report, key, value)
        elif key == "schema_first_pass_rate":
            note = "계산 가능, mock 합격 게이트 제외"
        else:
            note = "품질 판정 제외" if value is None else "결정적 fixture 측정"
        lines.append(f"| {label} | {_fmt(value)} | {note} |")
    lines.extend(
        [
            "",
            "## 3.5.4절 mock 합격 기준" if mock else "## 3.5.4절 기본 분석기 기준",
            "",
            "| 지표 | 값 | 기준 | 충족 |",
            "|---|---:|---:|---|",
        ]
    )
    for check in [*report.gate.checks, *report.gate.regression]:
        name = check.name
        if not mock and (
            (check.name == "unsupported_sentence_rate" and not _faithfulness_calibrated(report))
            or (check.name == "summary_key_fact_recall" and not _keyfact_calibrated(report))
        ):
            name = f"{check.name} ({UNCALIBRATED})"
        elif (
            not mock
            and report.judge is not None
            and report.judge.human_labels is False
            and (
                (check.name == "unsupported_sentence_rate" and _faithfulness_calibrated(report))
                or (check.name == "summary_key_fact_recall" and _keyfact_calibrated(report))
            )
        ):
            name = f"{check.name} (준-사람 보정)"
        lines.append(
            f"| {name} | {_fmt(check.value)} | {check.op} {_fmt(check.threshold)} | "
            f"{'O' if check.passed else 'X'} |"
        )
    if not mock and not _linkage_recorded(report):
        lines.append(
            f"| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= {_fmt(LINKAGE_DROP_LIMIT)} | "
            "해당 없음 |"
        )
    lines.extend(
        [
            "",
            "## 플랫폼군별 배선 지표",
            "",
            "| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for group, metrics in report.by_platform.items():
        lines.append(
            f"| {group} | {_fmt(metrics.get('n'))} | {_fmt(metrics.get('schema_final_pass_rate'))} | "
            f"{_fmt(metrics.get('average_retries'))} | {_fmt(metrics.get('injection_resistance'))} |"
        )
    lines.extend(
        [
            "",
            "## 실행 건수",
            "",
            *[f"- {key}: {value}" for key, value in report.counts.items()],
            "",
            "## 결정적 충실도 1차 검사",
            "",
            "요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.",
            "항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.",
            "forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,",
            "제품 모드 overall은 항목별 비율의 평균입니다.",
            "",
        ]
    )
    flagged = [item for item in report.items if item.unsupported_sentences]
    if flagged:
        for item in flagged:
            lines.append(f"- `{item.source_id}`: {' / '.join(item.unsupported_sentences)}")
    else:
        lines.append("- 근거 없음 후보 없음")
    failed_items = [item for item in report.items if not item.schema_final_pass]
    if failed_items:
        lines.extend(["", "## 최종 스키마 실패 항목", ""])
        for item in failed_items:
            lines.append(f"- `{item.source_id}`: status={item.job_status}, error={item.error_code or 'UNKNOWN'}")
    if report.gate.reasons:
        lines.extend(["", "## 미달 사유", "", *[f"- {reason}" for reason in report.gate.reasons]])
    lines.extend(_local_sections(report))
    lines.append("")
    return "\n".join(lines)


def _local_sections(report: IngestEvalReport) -> list[str]:
    """recorded/live 전용 절. mock 리포트에는 아무것도 더하지 않는다 (바이트 동일)."""
    lines: list[str] = []
    if report.search_linkage is not None:
        linkage = report.search_linkage
        embedder = "recorded bge-m3" if linkage.get("recorded_embedder") == 1.0 else "mock HashingEmbedder (판정 제외)"
        lines.extend(["", "## 검색 연결 지표", "", f"- 임베딩: {embedder}", "", "| 값 | 사람 분석 | 분석기 | 하락 |"])
        lines.append("|---|---:|---:|---:|")
        for metric in ("recall@10", "ndcg@10"):
            lines.append(
                f"| {metric} | {_fmt(linkage.get(f'human_{metric}'))} | {_fmt(linkage.get(f'analyzer_{metric}'))} | "
                f"{_fmt(linkage.get(f'{metric}_drop'))} |"
            )
        lines.append(
            f"- 질의 {_fmt(linkage.get('n_queries'))}건, 시드 분석 성공 {_fmt(linkage.get('seeds_succeeded'))}건 / "
            f"그 외 {_fmt(linkage.get('seeds_not_succeeded'))}건"
        )
    if report.runtime is not None:
        runtime = report.runtime
        lines.extend(
            [
                "",
                "## 실행 설정 (AC-L15)",
                "",
                f"- 프로필: `{runtime.profile}` (모델 `{runtime.model}`)",
                f"- recording_model_id: `{runtime.recording_model_id}`",
                f"- 녹화 파일: {', '.join(f'`{path}`' for path in runtime.recording_files)}",
                f"- 녹화: {'예' if runtime.recording else '아니오'}",
                f"- frozen_config_sha256: `{runtime.frozen_config_sha256}`"
                f" ({'동결 해시 확인' if runtime.frozen_config_checked else '동결 전 (dev)'})",
                f"- llama-cpp-python: {runtime.llama_cpp_python or '해당 없음 (recorded)'}",
                *[f"- 프롬프트 `{name}`: `{digest}`" for name, digest in runtime.prompts.items()],
            ]
        )
    if report.judge is not None:
        judge = report.judge
        overall = report.overall
        combined = _fmt(overall.get("unsupported_sentence_rate")) if judge.faithfulness_calibrated else UNCALIBRATED
        lines.extend(
            [
                "",
                "## 판정기 (8.3·8.4절)",
                "",
                f"- 프로필: `{judge.profile}` (모델 `{judge.model}`), recording_model_id `{judge.recording_model_id}`",
                f"- 녹화 파일: `{judge.recording_file}`, 녹화: {'예' if judge.recording else '아니오'}",
                f"- 보정: {judge.calibration} (충실도 이진 κ {_fmt(judge.kappa_binary_faithfulness)}, "
                f"핵심 사실 이진 κ {_fmt(judge.kappa_binary_keyfact)})",
                *(["- 사람 판정 아님 (준-사람 라벨, Q-LA3)"] if judge.human_labels is False else []),
                *[f"- 프롬프트 `{name}`: `{digest}`" for name, digest in judge.prompts.items()],
                "",
                "| 값 | 결정적 | 판정기/결합 |",
                "|---|---:|---:|",
                f"| 비충실 문장 비율 | {_fmt(overall.get('unsupported_sentence_rate_deterministic'))} | "
                f"{combined} |",
                f"| 핵심 사실 재현율 | {_fmt(overall.get('summary_key_fact_recall_deterministic'))} | "
                f"{_fmt(overall.get('summary_key_fact_recall_judge'))} |",
                "",
                f"- 판정 문장 {_fmt(overall.get('judge_sentences'))}개: unsupported "
                f"{_fmt(overall.get('judge_unsupported_sentences'))}, partially(비충실로 세지 않음) "
                f"{_fmt(overall.get('judge_partially_sentences'))}, judge_failed "
                f"{_fmt(overall.get('judge_failed_sentences'))}",
                f"- 핵심 사실 partial {_fmt(overall.get('judge_partial_key_facts'))}, judge_failed "
                f"{_fmt(overall.get('judge_failed_key_facts'))} (judge_failed는 결정적 값으로 센다)",
                f"- judge_context=retrieved 건수 {_fmt(overall.get('judge_retrieved_context'))}, "
                f"재요청 {_fmt(overall.get('judge_retries'))}회",
            ]
        )
    if report.misses is not None:
        lines.extend(["", "## 녹화 미스", ""])
        if not report.misses:
            lines.append("- 없음")
        for miss in report.misses:
            lines.append(
                f"- `{miss.source_id}`: {miss.kind}, schema={miss.schema_name or '-'}, "
                f"max_tokens={miss.max_tokens if miss.max_tokens is not None else '-'}, "
                f"request_hash=`{miss.request_hash or '-'}`"
            )
    return lines


def write_ingest_report(report: IngestEvalReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"eval_ingest_{report.config.mode}_{report.config.split}"
    json_path = out_dir / f"{stem}.json"
    markdown_path = out_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report.deterministic_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_ingest_markdown(report), encoding="utf-8")
    return json_path, markdown_path
