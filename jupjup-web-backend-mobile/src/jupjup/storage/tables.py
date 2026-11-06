"""SQLite tables from design section 6.2."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)

from jupjup.domain.models import CONTENT_TYPES, PLATFORMS
from jupjup.storage.instant import InstantText

metadata = MetaData()


def _enum_check(col: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} IN ({allowed})", name=f"ck_{col}_enum")


contents = Table(
    "contents",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, nullable=False, index=True),
    Column("source_url", Text),
    Column("source_kind", Text, nullable=False, server_default="text"),
    Column("normalized_url", Text),
    Column("platform", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("title", Text),
    Column("author", Text),
    Column("published_at", Text),
    Column("saved_at", Text, nullable=False),
    Column("saved_at_instant", InstantText()),
    Column("original_status", Text, nullable=False, server_default="unknown"),
    Column("user_note", Text),
    Column("hidden_tags", Text, nullable=False, server_default="[]"),
    Column("status", Text, nullable=False, server_default="ready"),
    Column("analysis_pending", Integer, nullable=False, server_default="0"),
    Column("automation_level", Text, nullable=False, server_default="auto"),
    Column("is_hidden", Integer, nullable=False, server_default="0"),
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("duplicate_of_content_id", Text, ForeignKey("contents.id", ondelete="CASCADE")),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("updated_at_instant", InstantText()),
    _enum_check("platform", PLATFORMS),
    _enum_check("content_type", CONTENT_TYPES),
    Index("ix_contents_user_saved", "user_id", "saved_at"),
    Index("ix_contents_user_hidden_saved", "user_id", "is_hidden", "saved_at", "id"),
    Index("ix_contents_user_updated", "user_id", "updated_at", "id"),
    Index("ix_contents_user_status", "user_id", "status"),
)

index_revisions = Table(
    "index_revisions",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("revision", Integer, nullable=False, server_default="0"),
)

snapshots = Table(
    "snapshots",
    metadata,
    Column("id", Text, primary_key=True),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("captured_at", Text, nullable=False),
    Column("text", Text),
    Column("ocr_text", Text),
    Column("raw_meta", Text, nullable=False, server_default="{}"),
    Column("content_hash", Text, nullable=False),
    Column("truncated", Integer, nullable=False, server_default="0"),
)

summaries = Table(
    "summaries",
    metadata,
    Column("id", Text, primary_key=True),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("model", Text),
    Column("source", Text, nullable=False),
    Column("analysis_run_id", Text),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("content_id", "source", "version", name="uq_summary_version"),
)

tags = Table(
    "tags",
    metadata,
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("confidence", Float),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("created_at", Text, nullable=False),
    PrimaryKeyConstraint("content_id", "name", "source"),
)

detail_tags = Table(
    "detail_tags",
    metadata,
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), primary_key=True),
    Column("ai_json", Text, nullable=False),
    Column("user_patch", Text),
    Column("schema_version", Integer, nullable=False, server_default="1"),
    Column("analysis_run_id", Text),
    Column("updated_at", Text, nullable=False),
)

embeddings = Table(
    "embeddings",
    metadata,
    Column("id", Text, primary_key=True),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("model_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("text_hash", Text, nullable=False),
    Column("dim", Integer, nullable=False),
    Column("vector", LargeBinary, nullable=False),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("content_id", "model_id", "kind", "chunk_index", name="uq_embedding_slot"),
)

ingest_jobs = Table(
    "ingest_jobs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, nullable=False, index=True),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("stage", Text, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("profile", Text, nullable=False),
    Column("attempts", Text, nullable=False, server_default="{}"),
    Column("next_run_at", Text),
    Column("lease_until", Text),
    Column("leased_by", Text),
    Column("lease_id", Text),
    Column("last_error", Text),
    Column("source_spec", Text),
    Column("stage_data", Text, nullable=False, server_default="{}"),
    Column("automation_level", Text, nullable=False, server_default="auto"),
    Column("result_content_id", Text),
    Column("candidate_id", Text),
    Column("completed_at", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("ix_ingest_jobs_schedule", "status", "priority", "next_run_at"),
    Index(
        "uq_ingest_jobs_active_content",
        "content_id",
        unique=True,
        sqlite_where=text("status IN ('queued', 'running', 'retry_wait', 'awaiting_confirmation')"),
    ),
)

ingest_job_events = Table(
    "ingest_job_events",
    metadata,
    Column("id", Text, primary_key=True),
    Column("job_id", Text, ForeignKey("ingest_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("at", Text, nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("stage", Text, nullable=False),
    Column("event", Text, nullable=False),
    Column("detail", Text, nullable=False, server_default="{}"),
)

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("job_id", Text, ForeignKey("ingest_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("profile", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("chunk_model", Text),
    Column("prompt_version", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("coverage", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("first_pass_ok", Integer, nullable=False),
    Column("partial", Integer, nullable=False),
    Column("repairs", Text, nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost_usd", Float, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("output_json", Text, nullable=False),
    Column("snapshot_id", Text),
    Column("candidate_id", Text),
    Column("model_fingerprint", Text),
    Column("validator_json", Text, nullable=False, server_default="{}"),
    Column("accepted_at", Text),
    Column("created_at", Text, nullable=False),
)

schema_migrations = Table(
    "schema_migrations",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("checksum", Text, nullable=False),
    Column("applied_at", Text, nullable=False),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("user_id", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("key_hash", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("response_status", Integer),
    Column("response_json", Text),
    Column("resource_id", Text),
    Column("job_id", Text),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    PrimaryKeyConstraint("user_id", "operation", "key_hash"),
)

content_fingerprints = Table(
    "content_fingerprints",
    metadata,
    Column("user_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("version", Text, nullable=False),
    Column("fingerprint", Text, nullable=False),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", Text, nullable=False),
    PrimaryKeyConstraint("user_id", "kind", "version", "fingerprint"),
)

analysis_candidates = Table(
    "analysis_candidates",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, nullable=False, index=True),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Text, ForeignKey("ingest_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("analysis_run_id", Text),
    Column("status", Text, nullable=False),
    Column("output_json", Text, nullable=False),
    Column("meta_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("decided_at", Text),
    Column("decision_revision", Integer, nullable=False, server_default="0"),
)

ingest_trace_artifacts = Table(
    "ingest_trace_artifacts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, nullable=False, index=True),
    Column("content_id", Text, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Text, ForeignKey("ingest_jobs.id", ondelete="CASCADE"), nullable=False),
    Column("stage", Text, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("artifact_type", Text, nullable=False),
    Column("schema_version", Integer, nullable=False, server_default="1"),
    Column("payload_json", Text, nullable=False),
    Column("payload_hash", Text, nullable=False),
    Column("sensitive", Integer, nullable=False, server_default="0"),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("job_id", "stage", "attempt", "artifact_type", "payload_hash", name="uq_ingest_trace_artifact"),
)
