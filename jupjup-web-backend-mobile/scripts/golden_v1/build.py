"""골든셋 v1 직렬화 스크립트 (초안, 사용자 검수 전).

    uv run python scripts/golden_v1/build.py

seeds_data.py, queries_data.py, lexicon_data.py의 표를 data/golden/*.jsonl로 쓴다.
결정적이다: 같은 표에서 늘 같은 파일이 나온다. split은 카테고리 층화 + id 해시 순서로 dev 60% / test 40%.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lexicon_data import CASES  # noqa: E402
from queries_data import QUERIES  # noqa: E402
from seeds_data import ALICE, BOB, CAROL  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "data" / "golden"
EVAL_NOW = "2026-10-15T12:00:00+09:00"
AUTHORED_BY = "ai_draft_unreviewed"  # 사용자 검수 전 초안

_URL = {
    "instagram": "https://www.instagram.com/p/{h}/",
    "youtube": "https://www.youtube.com/watch?v={h}",
    "news": "https://news.example.com/article/{h}",
    "blog": "https://blog.example.com/post/{h}",
    "web": "https://www.example.com/page/{h}",
    "x": "https://x.com/i/status/{h}",
}


def _iso(local: str) -> str:
    date, time = local.split()
    return f"{date}T{time}:00+09:00"


def _h(s: str, n: int = 11) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:n]


def _detail(extra: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    d: dict[str, Any] = {"schema_version": 1}
    if extra.get("cat"):
        d["category"] = extra["cat"]
    d["topics"] = tags[:3]
    if extra.get("purpose"):
        d["purpose"] = extra["purpose"].split()
    if extra.get("loc"):
        d["locations"] = [{"name": n} for n in extra["loc"].split()]
    if extra.get("ent"):
        ents = []
        for e in extra["ent"].split(","):
            typ, name = e.split(":", 1)
            ents.append({"type": typ, "name": name})
        d["entities"] = ents
    if extra.get("academic"):
        d["academic"] = extra["academic"]
    if extra.get("channel"):
        d["media"] = {"channel": extra["channel"]}
    return d


def build_seeds() -> tuple[list[dict[str, Any]], dict[str, str]]:
    records: list[dict[str, Any]] = []
    key_to_id: dict[str, str] = {}
    for user, rows in (("u_alice", ALICE), ("u_bob", BOB), ("u_carol", CAROL)):
        short = user[2:]
        for i, (key, platform, ctype, saved, title, body, summary, tags, extra) in enumerate(rows, 1):
            if key in key_to_id:
                raise SystemExit(f"중복 key: {key}")
            cid = f"c_{short}_{i:04d}"
            key_to_id[key] = cid
            ai_tags = tags.split()
            n = len(ai_tags)
            tag_objs: list[dict[str, Any]] = [
                {"name": t, "source": "ai", "confidence": round(0.95 - 0.05 * j, 2)} for j, t in enumerate(ai_tags)
            ]
            tag_objs += [{"name": t, "source": "user"} for t in extra.get("utags", "").split()]
            url_t = _URL.get(platform)
            rec: dict[str, Any] = {
                "id": cid,
                "user_id": user,
                "source_url": url_t.format(h=_h(cid)) if url_t else None,
                "platform": platform,
                "content_type": ctype,
                "title": title,
                "author": extra.get("author"),
                "published_at": None,
                "saved_at": _iso(saved),
                "original_status": extra.get("status", "available"),
                "user_note": extra.get("note"),
                "snapshot": {"captured_at": _iso(saved), "text": body, "ocr_text": extra.get("ocr")},
                "summary": {"text": summary, "model": "human", "version": 1, "source": "ai"},
                "tags": tag_objs,
                "hidden_tags": extra.get("hidden", "").split(),
                "detail_tags": _detail(extra, ai_tags[: max(1, n)]),
                "meta": {"authored_by": AUTHORED_BY, "key": key},
            }
            if extra.get("user_summary"):
                rec["summaries"] = [{"text": extra["user_summary"], "model": "human", "version": 1, "source": "user"}]
            if extra.get("user_patch"):
                rec["detail_tags_user_patch"] = extra["user_patch"]
            records.append(rec)
    return records, key_to_id


def _split(queries: list[dict[str, Any]]) -> None:
    """첫 카테고리로 층화하고, 층 안에서 id 해시 순서로 앞 60%를 dev로 둔다."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in queries:
        if q.get("split") in {"dev", "test"}:
            continue
        groups[q["categories"][0]].append(q)
    for items in groups.values():
        items.sort(key=lambda q: _h(q["id"], 16))
        n_dev = round(len(items) * 0.6)
        for i, q in enumerate(items):
            q["split"] = "dev" if i < n_dev else "test"


def _tr(t: tuple[str, str] | None) -> dict[str, str] | None:
    if t is None:
        return None
    return {"start": f"{t[0]}T00:00:00+09:00", "end": f"{t[1]}T00:00:00+09:00", "field": "saved_at"}


def build_queries(key_to_id: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, q in enumerate(QUERIES, 1):
        rel = {}
        for key, grade in q["rel"].items():
            if key not in key_to_id:
                raise SystemExit(f"질의 {i} '{q['query']}': 없는 seed key {key}")
            rel[key_to_id[key]] = grade
        rec: dict[str, Any] = {
            "id": f"q_{i:04d}",
            "user_id": q["user"],
            "query": q["query"],
            "now": EVAL_NOW,
            "categories": q["cats"],
            "split": q["split"],
            "request_filters": q["filters"],
            "expected": {
                "intent": q["intent"],
                "time_range": _tr(q["time"]),
                "platforms": q["plats"],
                "content_types": q["types"],
                "keywords_must_include": q["kw"],
            },
            "relevance": rel,
            "notes": q["notes"] or None,
        }
        out.append(rec)
    _split(out)
    return out


def build_lexicon() -> list[dict[str, Any]]:
    out = []
    for i, (text, now, rng, plats, types) in enumerate(CASES, 1):
        out.append(
            {
                "id": f"t_{i:03d}",
                "text": text,
                "now": now or EVAL_NOW,
                "expected": {"time_range": _tr(rng), "platforms": plats.split(), "content_types": types.split()},
            }
        )
    return out


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n")


def main() -> None:
    seeds, key_to_id = build_seeds()
    queries = build_queries(key_to_id)
    cases = build_lexicon()
    _write(OUT / "seeds.jsonl", seeds)
    _write(OUT / "queries.jsonl", queries)
    _write(OUT / "lexicon_cases.jsonl", cases)
    by_user: dict[str, int] = defaultdict(int)
    for s in seeds:
        by_user[s["user_id"]] += 1
    print(f"seeds={len(seeds)} {dict(by_user)} queries={len(queries)} lexicon_cases={len(cases)}")


if __name__ == "__main__":
    main()
