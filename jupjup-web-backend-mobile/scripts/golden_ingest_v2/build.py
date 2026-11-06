"""Build the natural-language ingest golden v2 (T25c) into data/golden/ingest/.

    uv run python scripts/golden_ingest_v2/build.py           # 쓰기 (결정적)
    uv run python scripts/golden_ingest_v2/build.py --check   # 파일이 이 스크립트 결과와 같은지만 확인
    uv run python scripts/golden_ingest_v2/build.py --reseal --reason "<이유>"   # test gold를 고쳐 봉인이 바뀔 때만

test 봉인 규칙 (T25c 검수 L1): 생성 결과의 test 봉인이 기존 ``test.sha256``(없으면 ``SEAL_HISTORY`` 마지막 값)과 다르면
``--reseal --reason``이 없을 때 쓰지 않는다. 다시 봉인했으면 출력 안내대로 ``SEAL_HISTORY``에 이유와 해시를 더해
커밋한다. gold를 고칠 때는 건마다 ``GOLD_REVISIONS``에 이유를 남긴다. 둘 다 ``manifest.json``에 그대로 들어간다.

산출물: sources.jsonl, annotations.jsonl, fixtures/, test.sha256, sample_for_user.jsonl, manifest.json.
모든 annotation은 AI 초안(annotator ai, review_status ai_draft_unreviewed)이다.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "data" / "golden" / "ingest"
sys.path.insert(0, str(HERE))

import data_blog_web  # noqa: E402
import data_image  # noqa: E402
import data_instagram  # noqa: E402
import data_kakaotalk  # noqa: E402
import data_news  # noqa: E402
import data_paper  # noqa: E402
import data_youtube  # noqa: E402

from jupjup.eval.ingest_golden_checks import compute_test_seal, format_seal, read_seal  # noqa: E402
from jupjup.eval.ingest_harness import load_ingest_golden  # noqa: E402

GROUPS: tuple[tuple[str, Any, tuple[str, str] | None], ...] = (
    ("instagram", data_instagram, ("instagram", "post")),
    ("youtube", data_youtube, ("youtube", "video")),
    ("news", data_news, ("news", "article")),
    ("paper", data_paper, ("web", "paper")),
    ("kakaotalk", data_kakaotalk, ("kakaotalk", "message")),
    ("blog_web", data_blog_web, None),
    ("image", data_image, ("local", "image")),
)
# test 봉인 이력. 마지막 값이 현재 test split 봉인이어야 한다.
SEAL_HISTORY: tuple[dict[str, str], ...] = (
    {
        "date": "2026-11-02",
        "digest": "764aaf760ad049846311a498fe36ab2cdc214466b43c19b2e3836f8baca2d68c",
        "reason": "T25c 최초 봉인 (test 32건)",
    },
)
# gold 수정 이력 (건별 이유). source_id는 생성 순서로 정해지므로 RECORDS 순서를 바꾸지 않는다.
GOLD_REVISIONS: tuple[dict[str, str], ...] = (
    {
        "date": "2026-11-02",
        "task": "T25p",
        "source_id": "ing2_0038",
        "split": "dev",
        "change": "forbidden_claims '입장료' → '유료 입장'",
        "reason": (
            "T25c 검수 M1: key_fact '입장료는 없다'의 부분 문자열이라, 그 사실을 담은 가장 충실한 요약이 "
            "비충실 1.0이 됐다"
        ),
    },
    {
        "date": "2026-11-02",
        "task": "T25p",
        "source_id": "ing2_0069",
        "split": "dev",
        "change": "forbidden_claims '굴' → '굴을 넣'",
        "reason": "T25c 검수 M1 ③: 한 글자 forbidden_claim은 '얼굴'·'동굴'처럼 무관한 단어에도 걸린다",
    },
)
SAMPLE_SEED = 20261102
SAMPLE_SIZE = 24
REVIEW_QUESTIONS = [
    "원문을 읽고 대표 태그 3~7개가 꼭 필요한 태그인가요? (빠진 것/지울 것)",
    "엔티티와 장소가 원문에 실제로 나오고 빠진 것은 없나요?",
    "category와 save_intent가 이 저장물을 저장한 이유에 맞나요?",
    "key_facts가 원문과 사실이 같고(숫자·날짜 포함), 요약에 꼭 들어가야 할 내용인가요?",
    "forbidden_claims가 원문에 없고 모델이 지어내기 쉬운 내용인가요?",
]


def _dumps(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def build_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    fixtures: dict[str, str] = {}
    authored: list[dict[str, Any]] = []
    number = 0
    for group, module, default_platform in GROUPS:
        for record in module.RECORDS:
            number += 1
            source_id = f"ing2_{number:04d}"
            platform, content_type = default_platform or (record["platform"], record["content_type"])
            platform = record["platform"] or platform
            content_type = record["content_type"] or content_type
            if record["text"] is not None:
                spec: dict[str, Any] = {"kind": "text", "text": record["text"]}
            elif record["ocr_text"] is not None:
                spec = {"kind": "image", "ocr_text": record["ocr_text"], "image_path": f"images/{source_id}.png"}
            else:
                fixture = record["fixture"]
                spec = {
                    "kind": fixture["kind"],
                    "url": f"https://fixtures.local/{source_id}",
                    "fixture": fixture["name"],
                }
                assert fixture["name"] not in fixtures, fixture["name"]
                fixtures[fixture["name"]] = fixture["body"]
            row: dict[str, Any] = {
                "source_id": source_id,
                "platform_group": group,
                "platform": platform,
                "content_type": content_type,
                "source": spec,
                "title": record["title"],
                "difficult_cases": record["difficult_cases"],
            }
            if record["mock_failure"]:
                row["mock_failure"] = record["mock_failure"]
            if record["injection_target"]:
                row["injection_target"] = record["injection_target"]
            sources.append(row)
            annotations.append(
                {
                    "source_id": source_id,
                    "gold": record["gold"],
                    "annotator": "ai",
                    "split": record["split"],
                    "review_status": "ai_draft_unreviewed",
                }
            )
            authored.append({"source_id": source_id, "key": record["key"], "group": group, "split": record["split"]})
    return sources, annotations, fixtures, authored


def user_sample(sources: list[dict[str, Any]], annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """플랫폼군 비율대로 층화하고, 어려운 사례 5종과 mock 실패 배선 건을 각 1건 이상 넣는 결정적 표본."""
    rng = random.Random(SAMPLE_SEED)
    gold_by_id = {row["source_id"]: row for row in annotations}
    quota = {"instagram": 4, "youtube": 4, "news": 4, "paper": 3, "kakaotalk": 3, "blog_web": 3, "image": 3}
    assert sum(quota.values()) == SAMPLE_SIZE
    chosen: list[str] = []
    for case in ("long_text", "ad_hashtag_heavy", "mostly_english", "number_date_dense", "prompt_injection"):
        candidates = [
            row["source_id"] for row in sources if case in row["difficult_cases"] and row["source_id"] not in chosen
        ]
        chosen.append(rng.choice(sorted(candidates)))
    for group, count in quota.items():
        already = sum(1 for row in sources if row["source_id"] in chosen and row["platform_group"] == group)
        pool = sorted(
            row["source_id"] for row in sources if row["platform_group"] == group and row["source_id"] not in chosen
        )
        chosen.extend(rng.sample(pool, max(0, count - already)))
    chosen = sorted(set(chosen))
    rows = []
    for source in sources:
        if source["source_id"] not in chosen:
            continue
        annotation = gold_by_id[source["source_id"]]
        spec = source["source"]
        rows.append(
            {
                "source_id": source["source_id"],
                "split": annotation["split"],
                "platform_group": source["platform_group"],
                "title": source["title"],
                "difficult_cases": source["difficult_cases"],
                "source_ref": spec.get("fixture") or ("ocr_text" if spec["kind"] == "image" else "text"),
                "source_excerpt": (spec.get("text") or spec.get("ocr_text") or "")[:1200]
                or f"fixtures/{spec['fixture']} 파일을 여세요 (긴 글은 앞부분과 key_facts 근거 문단을 확인)",
                "gold": annotation["gold"],
                "review_questions": REVIEW_QUESTIONS,
                "user_verdict": None,
                "user_notes": "",
            }
        )
    return rows


def _check_seal(out: Path, digest: str, reseal_reason: str | None) -> list[dict[str, str]]:
    """봉인이 바뀌면 이유 없이 쓰지 않는다. manifest에 넣을 봉인 이력을 돌려준다."""
    seal_path = out / "test.sha256"
    expected = read_seal(seal_path) if seal_path.is_file() else SEAL_HISTORY[-1]["digest"]
    history = [dict(row) for row in SEAL_HISTORY]
    if reseal_reason is None:
        if digest != expected:
            raise SystemExit(
                f"test 봉인이 바뀝니다 ({expected[:16]}… → {digest[:16]}…). test 원문·gold를 고쳤다면 "
                '--reseal --reason "<이유>"로 다시 실행하고 SEAL_HISTORY에 이유를 더하세요'
            )
        return history
    if not reseal_reason.strip():
        raise SystemExit("--reseal에는 비어 있지 않은 --reason이 필요합니다")
    history.append({"date": "unrecorded", "digest": digest, "reason": reseal_reason.strip()})
    print(f"다시 봉인: {digest}. SEAL_HISTORY에 이 항목을 더해 커밋하세요: {history[-1]}")
    return history


def write(out: Path, *, reseal_reason: str | None = None) -> None:
    sources, annotations, fixtures, _ = build_rows()
    fixtures_dir = out / "fixtures"
    if fixtures_dir.exists():
        shutil.rmtree(fixtures_dir)
    for name, body in sorted(fixtures.items()):
        path = fixtures_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    (out / "sources.jsonl").write_text("".join(_dumps(row) + "\n" for row in sources), encoding="utf-8")
    (out / "annotations.jsonl").write_text("".join(_dumps(row) + "\n" for row in annotations), encoding="utf-8")
    golden, errors = load_ingest_golden(out / "sources.jsonl", out / "annotations.jsonl")
    if errors:
        raise SystemExit("골든 로드 실패: " + "; ".join(errors))
    digest, count = compute_test_seal(golden, fixtures_dir)
    seal_history = _check_seal(out, digest, reseal_reason)
    (out / "test.sha256").write_text(format_seal(digest, count), encoding="utf-8")
    sample = user_sample(sources, annotations)
    (out / "sample_for_user.jsonl").write_text("".join(_dumps(row) + "\n" for row in sample), encoding="utf-8")
    manifest = {
        "version": 2,
        "created": "2026-11-02",
        "author": "ai (Claude, Codex-Primary 대체 실행)",
        "records": len(sources),
        "splits": dict(sorted(Counter(row["split"] for row in annotations).items())),
        "platform_groups": dict(Counter(row["platform_group"] for row in sources)),
        "difficult_cases": dict(sorted(Counter(c for row in sources for c in row["difficult_cases"]).items())),
        "review_status": "ai_draft_unreviewed",
        "user_sample": {"file": "sample_for_user.jsonl", "count": len(sample), "seed": SAMPLE_SEED},
        "test_seal": {"file": "test.sha256", "records": count},
        "seal_history": seal_history,
        "gold_revisions": [dict(row) for row in GOLD_REVISIONS],
        "generator": "scripts/golden_ingest_v2/build.py",
        "content_policy": "모든 원문은 직접 쓴 합성 데이터. 상호·인물·단체는 지어낸 이름, 실존 개인정보 없음",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="쓰지 않고 현재 파일과 같은지 비교")
    parser.add_argument("--reseal", action="store_true", help="test 봉인이 바뀌는 것을 허용 (--reason 필수)")
    parser.add_argument("--reason", default=None, help="다시 봉인하는 이유")
    args = parser.parse_args()
    if args.reseal and not args.reason:
        raise SystemExit("--reseal에는 --reason이 필요합니다")
    if not args.check:
        write(OUT, reseal_reason=args.reason if args.reseal else None)
        print(f"wrote {OUT}")
        return
    import filecmp
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        write(target)
        mismatch = [
            str(path.relative_to(target))
            for path in sorted(target.rglob("*"))
            if path.is_file() and not filecmp.cmp(path, OUT / path.relative_to(target), shallow=False)
        ]
    if mismatch:
        raise SystemExit(f"생성 결과와 다른 파일: {mismatch}")
    print("golden v2 files match the generator")


if __name__ == "__main__":
    main()
