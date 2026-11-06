"""Isolated real service save -> GGUF -> collection -> bge search; no server changes."""

from __future__ import annotations

import json
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from jupjup.api.app import create_app
from jupjup.config import Settings
from jupjup.container import build_container, build_ingest_service
from jupjup.ingest.fetch import FetcherRouter, InlineTextFetcher, RawSource


class CapturedFetcher:
    def __init__(self, raw: RawSource):
        self.raw = raw

    def supports(self, spec):
        return True

    def fetch(self, spec):
        return self.raw


def main():
    raw = RawSource.model_validate_json(Path(sys.argv[1]).read_text())
    Path("var").mkdir(exist_ok=True)
    with ExitStack() as cleanup, tempfile.TemporaryDirectory(prefix="live-save-", dir="var") as directory:
        settings = Settings(db_path=Path(directory) / "isolated.db", recordings_dir=Path(directory) / "recordings")
        assert settings.mode == "live" and settings.analyzer.engine == "local"
        c = build_container(settings)
        ingest = build_ingest_service(c, worker_id="isolated-live")
        runners = ingest.worker.stages["fetch"].__self__
        cleanup.callback(runners.analyzer.llm.close)
        runners.fetcher = FetcherRouter([InlineTextFetcher(), CapturedFetcher(raw)])
        headers = {"X-User-Id": "u_live_validation", "Idempotency-Key": "real-local-save"}
        with TestClient(create_app(container=c, ingest=ingest)) as client:
            saved = client.post(
                "/v1/contents",
                headers=headers,
                json={"source": {"kind": "url", "url": raw.final_url}, "automation_level": "auto"},
            )
            assert saved.status_code == 202, saved.text
            ids = saved.json()
            ingest.run_inline(ids["job_id"])
            job = ingest.status(headers["X-User-Id"], ids["job_id"])
            print(json.dumps({"job": job.model_dump(mode="json")}, ensure_ascii=False), flush=True)
            assert job.status == "succeeded", job.last_error
            detail = client.get("/v1/contents/" + ids["content_id"], headers=headers).json()
            assert detail["summary"]["effective"] and len(detail["representative_tags"]["ai"]) >= 3
            assert detail["collection_ids"]
            with c.engine.connect() as conn:
                collections = conn.execute(text("SELECT name FROM collections")).scalars().all()
                models = conn.execute(text("SELECT model FROM analysis_runs")).scalars().all()
                embeddings = conn.execute(text("SELECT DISTINCT model_id FROM embeddings")).scalars().all()
            result = client.post("/v1/search", headers=headers, json={"query": "C++ 프로그래밍 강의"})
            print(
                json.dumps(
                    {
                        "detail": detail,
                        "collections": collections,
                        "models": models,
                        "embeddings": embeddings,
                        "search_status": result.status_code,
                        "search": result.json(),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )
            assert result.status_code == 200 and ids["content_id"] in result.text
            assert "bge-m3" in embeddings
            text_saved = client.post(
                "/v1/contents",
                headers={**headers, "Idempotency-Key": "real-text"},
                json={
                    "source": {
                        "kind": "text",
                        "text": (
                            "이번 C++ 강의에서는 변수와 함수를 배웁니다. 실습 도구는 Visual Studio Code입니다. "
                            "첫 과제는 정수 두 개를 더하는 프로그램을 작성하는 것입니다."
                        ),
                    },
                    "automation_level": "auto",
                },
            ).json()
            ingest.run_inline(text_saved["job_id"])
            text_job = ingest.status(headers["X-User-Id"], text_saved["job_id"])
            text_detail = client.get("/v1/contents/" + text_saved["content_id"], headers=headers).json()
            print(
                json.dumps(
                    {"authored_text_status": text_job.status, "error": text_job.last_error, "detail": text_detail},
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )
            assert text_job.status == "succeeded", text_job.last_error
            assert text_detail["summary"]["ai"] and len(text_detail["representative_tags"]["ai"]) >= 3
            assert text_detail["collection_ids"]


if __name__ == "__main__":
    main()
