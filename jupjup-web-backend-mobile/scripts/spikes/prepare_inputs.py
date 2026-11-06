"""T25b: 스파이크 입력(정본 스키마, ds-1 근사 디코딩 스키마, 프롬프트 메시지)을 만든다.

프로젝트 환경에서 실행한다 (jupjup를 import한다. src/는 읽기만 한다):
    uv run python scripts/spikes/prepare_inputs.py

출력: scripts/spikes/results/inputs.json
- canonical_schema: analysis_output_json_schema() 그대로
- decoding_schema: 설계 5.2절 ds-1 표를 스파이크용으로 근사한 것 (T25d의 build_decoding_schema가 정본)
- items: 문서마다 system/user 메시지. 문법 유/무 두 조건이 **같은 프롬프트**를 쓴다 (문법만 다르다)
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from jupjup.ingest.schemas import analysis_output_json_schema

HERE = Path(__file__).resolve().parent
DOCS = HERE / "data" / "synthetic_dev_v1.jsonl"
OUT = HERE / "results" / "inputs.json"
PROMPT = HERE.parents[1] / "src" / "jupjup" / "ingest" / "prompts" / "analyze_v1.md"

UNSUPPORTED = {"$schema", "$id", "title", "description", "maxProperties", "format"}
ORDER = ["language", "title_suggestion", "evidence", "summary", "representative_tags", "detail_tags", "save_intent"]


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            return _inline(copy.deepcopy(defs[name]), defs)
        return {k: _inline(v, defs) for k, v in node.items() if k not in UNSUPPORTED and k != "$defs"}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def build_ds1(canonical: dict[str, Any]) -> dict[str, Any]:
    schema = _inline(canonical, canonical.get("$defs", {}))
    props = schema["properties"]
    schema["properties"] = {k: props[k] for k in ORDER}
    props = schema["properties"]
    props["evidence"]["maxItems"] = 6
    props["evidence"]["items"]["properties"]["source_span"]["maxLength"] = 120
    detail = props["detail_tags"]["properties"]
    for drop in ("attributes", "save_intent", "purpose"):
        detail.pop(drop)
    detail["entities"]["maxItems"] = 10
    detail["keywords"]["maxItems"] = 10
    detail["topics"]["maxItems"] = 5
    return schema


def main() -> None:
    canonical = analysis_output_json_schema()
    decoding = build_ds1(canonical)
    template = PROMPT.read_text(encoding="utf-8")
    instructions, _, _ = template.partition("<source_document>")
    system = (
        instructions.strip()
        + "\n\nJSON Schema (follow exactly, keys in this order):\n"
        + json.dumps(decoding, ensure_ascii=False, separators=(",", ":"))
    )
    items = []
    for line in DOCS.read_text(encoding="utf-8").splitlines():
        doc = json.loads(line)
        metadata = {k: doc[k] for k in ("content_type", "platform", "url", "user_note")}
        user = (
            "<source_document>\n" + str(doc["source_document"]) + "\n</source_document>\n\n"
            "<content_metadata>\n" + json.dumps(metadata, ensure_ascii=False) + "\n</content_metadata>"
        )
        items.append({"id": doc["id"], "source_document": doc["source_document"], "system": system, "user": user})
    # 지연 상한 확인용 긴 입력 1건 (10건을 이어 붙인 스크랩 모음, 약 4.8K자). 준수율 통계에는 넣지 않는다.
    joined = "\n\n---\n\n".join(str(i["source_document"]) for i in items)
    long_meta = {"content_type": "note", "platform": "memo", "url": None, "user_note": "스크랩 모음"}
    long_user = (
        "<source_document>\n" + joined + "\n</source_document>\n\n"
        "<content_metadata>\n" + json.dumps(long_meta, ensure_ascii=False) + "\n</content_metadata>"
    )
    long_probe = {"id": "long-probe-joined10", "source_document": joined, "system": system, "user": long_user}
    payload = {
        "prompt_source": "src/jupjup/ingest/prompts/analyze_v1.md (instructions part) + ds-1 approx schema",
        "decoding_schema_sha256": hashlib.sha256(
            json.dumps(decoding, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "canonical_schema": canonical,
        "decoding_schema": decoding,
        "items": items,
        "long_probe": long_probe,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} items -> {OUT}; system chars={len(system)}")


if __name__ == "__main__":
    main()
