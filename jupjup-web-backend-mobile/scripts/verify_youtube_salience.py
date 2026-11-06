"""Offline real-provider reproduction. No DB, servers, embeddings or network used.

Run: scripts/live_local.sh scripts/verify_youtube_salience.py
Optional first argument: path to a captured YoutubeMetadata JSON (with optional url/provenance).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jupjup.config import REPO_ROOT, Settings
from jupjup.container import build_local_content_analyzer
from jupjup.ingest.chunking import AnalysisInput, ContentMeta
from jupjup.ingest.profiles import AnalyzerProfiles
from jupjup.ingest.youtube_metadata import YoutubeMetadata
from jupjup.ingest.youtube_salience import filter_metadata
from jupjup.providers.llm_local import LlamaCppLLM
from jupjup.text.lexicon import Lexicon


def main() -> None:
    settings = Settings()
    profiles = AnalyzerProfiles.load(settings.analyzer.profiles_path)
    profile = profiles.profile(settings.analyzer.profile)
    llm = LlamaCppLLM(profiles.model_for(profile), profile.decoding, settings.analyzer_cache_dir)
    analyzer = build_local_content_analyzer(profile, llm, None, Lexicon.load(REPO_ROOT / "data/lexicon"))
    fixture = (
        Path(sys.argv[1])
        if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
        else REPO_ROOT / "tests/fixtures/youtube/salience_case.json"
    )
    value = json.loads(fixture.read_text())
    metadata = YoutubeMetadata.model_validate({k: v for k, v in value.items() if k not in {"provenance", "url"}})
    results: dict[str, object] = {"provenance": value.get("provenance"), "metadata": metadata.model_dump()}
    try:
        cases = [
            ("gaming", metadata),
            (
                "music",
                metadata.model_copy(
                    update={
                        "title": "Lost Sky - Dreams pt. II [NCS Release]",
                        "description": "Lost Sky - Dreams pt. II [NCS Release]\nMusic provided by NoCopyrightSounds.\n",
                    }
                ),
            ),
        ]
        if "--gaming-only" in sys.argv:
            cases = cases[:1]
        for name, current in cases:
            row: dict[str, object] = {}
            results[name] = row
            if name == "gaming" and "--skip-before" not in sys.argv:
                try:
                    before, before_meta = analyzer.analyze(
                        AnalysisInput(
                            mode="single",
                            text=f"제목: {current.title}\n설명: {current.description}",
                            meta=ContentMeta(
                                title=current.title,
                                platform="youtube",
                                content_type="video",
                                description="공개 제목·설명만 제공됨. 영상 전체 내용은 알 수 없음.",
                            ),
                        )
                    )
                    row["before"] = before.model_dump(mode="json")
                    row["before_meta"] = before_meta.model_dump(mode="json")
                except Exception as exc:
                    row["before_error"] = {"message": str(exc), "details": getattr(exc, "details", {})}
            try:
                salience = filter_metadata(current, analyzer)
                row["salience"] = salience.model_dump(mode="json")
                after, meta = analyzer.analyze_youtube_metadata(
                    AnalysisInput(
                        mode="single",
                        text=salience.primary_text(),
                        meta=ContentMeta(
                            title=next((b.text for b in salience.primary if b.field == "title"), None),
                            platform="youtube",
                            content_type="video",
                            ),
                    )
                )
                row["after"] = after.model_dump(mode="json")
                row["after_meta"] = meta.model_dump(mode="json")
            except Exception as exc:
                row["after_error"] = {"message": str(exc), "details": getattr(exc, "details", {})}
    finally:
        llm.close()
        print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
