"""Public watch-page caption discovery; no cookies, login, or alternate clients."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jupjup.domain.errors import JupjupError, SourceTextUnavailableError
from jupjup.ingest.fetch import HttpSourceFetcher, RawSource, SourceSpec
from jupjup.ingest.youtube_metadata import YoutubeMetadata

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com"})
MESSAGE = (
    "영상의 공개 자막을 가져오지 못했어요. 자막이 없거나 공개 접근이 제한되어 있어요. "
    "자막(VTT/SRT)이나 영상 내용을 텍스트로 직접 저장해 주세요."
)

SOURCE_REASON_MESSAGES = {
    "private_video": "비공개 영상이라 제목·설명을 가져올 수 없어요.",
    "public_access_restricted": "공개 접근이 제한된 영상이에요. 로그인 없이 수집할 수 없어요.",
    "playback_unavailable": "공개 플레이어에서 이용할 수 없는 영상이에요.",
    "player_unavailable": "공개 영상 플레이어 정보를 찾지 못했어요.",
    "http_access_denied": "YouTube가 공개 접근을 차단했어요.",
    "metadata_title_unavailable": "공개 제목이 없어 제목·설명 분류를 진행할 수 없어요.",
    "public_access_failed": "공개 영상 정보를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.",
    "unsafe_caption_url": "안전하지 않은 자막 주소라 수집을 중단했어요.",
    "invalid_description": "공개 설명 필드가 올바른 텍스트 형식이 아니에요.",
}


def is_youtube_url(url: str | None) -> bool:
    return bool(url and urlsplit(url).hostname in YOUTUBE_HOSTS)


def has_transcript_evidence(raw_meta: dict[str, Any]) -> bool:
    return bool(raw_meta.get("transcript_segments")) or raw_meta.get("source_mime") in {
        "text/vtt",
        "application/x-subrip",
        "application/json",
    }


def is_legacy_watch_snapshot(url: str | None, raw_meta: dict[str, Any]) -> bool:
    return is_youtube_url(url) and raw_meta.get("source") == "http" and not has_transcript_evidence(raw_meta)


def unavailable(reason: str) -> SourceTextUnavailableError:
    return SourceTextUnavailableError(
        SOURCE_REASON_MESSAGES.get(reason, MESSAGE), {"reason": reason, "retryable": False}
    )


def _youtube_policy(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in YOUTUBE_HOSTS or parsed.port not in (None, 443):
        raise unavailable("unsafe_caption_url")
    if parsed.username is not None or parsed.password is not None:
        raise unavailable("unsafe_caption_url")


class YoutubeCaptionFetcher:
    def __init__(self, http: HttpSourceFetcher | None = None, *, timeout_s: float = 10.0) -> None:
        self.http = http or HttpSourceFetcher(max_bytes=5_000_000, timeout_s=timeout_s)
        self.timeout_s = timeout_s

    def supports(self, spec: SourceSpec) -> bool:
        return spec.fixture is None and (spec.kind == "youtube" or (spec.kind == "url" and is_youtube_url(spec.url)))

    def fetch(self, spec: SourceSpec) -> RawSource:
        if not spec.url:
            raise unavailable("missing_url")
        deadline = time.monotonic() + self.timeout_s
        try:
            watch = self.http.fetch(SourceSpec(kind="url", url=spec.url), url_policy=_youtube_policy, deadline=deadline)
            # A supplied transcript URL remains a supported source format.
            if watch.mime.partition(";")[0] in {"text/vtt", "application/x-subrip", "application/json"}:
                if spec.youtube_metadata_only:
                    raise unavailable("player_unavailable")
                return watch.model_copy(update={"kind": "youtube"})
            source = watch.body.decode("utf-8") if isinstance(watch.body, bytes) else watch.body
            player = None
            for match in re.finditer(r"(?:var\s+)?ytInitialPlayerResponse\s*=\s*", source):
                try:
                    player, _ = json.JSONDecoder().raw_decode(source[match.end() :])
                except (ValueError, RecursionError):
                    continue
                if isinstance(player, dict):
                    break
            if not isinstance(player, dict):
                raise unavailable("player_unavailable")
            if player.get("playabilityStatus", {}).get("status") != "OK":
                status = player.get("playabilityStatus", {}).get("status")
                reason = str(player.get("playabilityStatus", {}).get("reason", "")).casefold()
                if "private" in reason or "비공개" in reason:
                    raise unavailable("private_video")
                raise unavailable("public_access_restricted" if status == "LOGIN_REQUIRED" else "playback_unavailable")
            details = player.get("videoDetails", {})

            def metadata_source(reason: Any) -> RawSource:
                title = details.get("title")
                description = details.get("shortDescription")
                if not isinstance(title, str) or not title.strip():
                    raise unavailable("metadata_title_unavailable")
                if description is not None and not isinstance(description, str):
                    raise unavailable("invalid_description")
                metadata = YoutubeMetadata(
                    title=title[:1000],
                    description=(description or "")[:20_000],
                    description_source="videoDetails.shortDescription" if description is not None else "absent",
                    description_status="missing"
                    if description is None
                    else "available"
                    if description.strip()
                    else "empty",
                    title_truncated=len(title) > 1000,
                    description_truncated=len(description or "") > 20_000,
                    transcript_reason=reason,
                )
                return watch.model_copy(
                    update={
                        "kind": "youtube",
                        "body": "",
                        "mime": "text/plain",
                        "final_url": spec.url,
                        "meta": {"source": "youtube_metadata", "youtube_metadata": metadata.model_dump(mode="json")},
                    }
                )

            if spec.youtube_metadata_only:
                return metadata_source("not_requested")

            tracks = player.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
            tracks = [t for t in tracks if isinstance(t, dict) and isinstance(t.get("baseUrl"), str)]
            if not tracks:
                return metadata_source("captions_unavailable")
            tracks.sort(key=lambda t: (t.get("languageCode") != "ko", t.get("kind") == "asr"))
            parsed = urlsplit(tracks[0]["baseUrl"])
            if parsed.path != "/api/timedtext":
                raise unavailable("unsafe_caption_url")
            query = parse_qs(parsed.query, keep_blank_values=True)
            query["fmt"] = ["json3"]
            url = urlunsplit(parsed._replace(query=urlencode(query, doseq=True)))
            caption = self.http.fetch(SourceSpec(kind="url", url=url), url_policy=_youtube_policy, deadline=deadline)
            if not caption.body:
                return metadata_source("empty_captions")
            payload = json.loads(caption.body)
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                return metadata_source("empty_or_invalid_captions")
            if not any(
                isinstance(event, dict)
                and any(
                    isinstance(seg, dict) and isinstance(seg.get("utf8"), str) and seg["utf8"].strip()
                    for seg in event.get("segs", [])
                )
                for event in payload["events"]
            ):
                return metadata_source("empty_captions")
            return caption.model_copy(
                update={
                    "kind": "youtube",
                    "mime": "application/json",
                    "final_url": spec.url,
                    "meta": {
                        **caption.meta,
                        "source": "youtube_captions",
                        "title": player.get("videoDetails", {}).get("title"),
                        "language": tracks[0].get("languageCode"),
                    },
                }
            )
        except SourceTextUnavailableError:
            raise
        except JupjupError as exc:
            reason = "http_access_denied" if exc.details.get("status") in {401, 403} else "public_access_failed"
            raise unavailable(reason) from exc
        except (ValueError, TypeError, AttributeError, RecursionError) as exc:
            raise unavailable("public_access_failed") from exc
