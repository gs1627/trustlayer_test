"""Priority 2 schema: session updates, UTC timestamps, profiles, operations, evidence, and trust assessments.

Revision ID: 0002_priority2_schema
Revises: 0001_initial_priority1
Create Date: 2026-11-25 11:37:00.000000+00:00
"""
from datetime import datetime, timezone
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_priority2_schema"
down_revision: Union[str, Sequence[str], None] = "0001_initial_priority1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PG_TS_CASE = (
    "CASE "
    "WHEN {col} IS NULL OR btrim({col}) = '' THEN NULL "
    "WHEN btrim({col}) ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}([T ]\\d{{2}}:\\d{{2}}:\\d{{2}}(\\.\\d+)?)?([Zz]|[+-]\\d{{2}}:?\\d{{2}})?$' "
    "THEN btrim({col})::timestamptz "
    "ELSE NULL "
    "END"
)


def _parse_iso_to_sqlite_utc(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    if cleaned.endswith(("Z", "z")):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")


def _snapshot_sqlite_timestamps(table: str, pk_col: str, ts_col: str) -> list[tuple[Any, str | None]]:
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"SELECT {pk_col}, {ts_col} FROM {table} WHERE {ts_col} IS NOT NULL")).fetchall()
    snapshot: list[tuple[Any, str | None]] = []
    for pk_val, raw_val in rows:
        snapshot.append((pk_val, _parse_iso_to_sqlite_utc(raw_val)))
    if rows:
        # Clear before SQLite batch_alter_table so Alembic's CAST(... AS DATETIME) does not truncate strings to year ints
        conn.execute(sa.text(f"UPDATE {table} SET {ts_col} = NULL WHERE {ts_col} IS NOT NULL"))
    return snapshot


def _restore_sqlite_timestamps(table: str, pk_col: str, ts_col: str, snapshot: list[tuple[Any, str | None]]) -> None:
    if not snapshot:
        return
    conn = op.get_bind()
    for pk_val, normalized in snapshot:
        conn.execute(
            sa.text(f"UPDATE {table} SET {ts_col} = :ts_val WHERE {pk_col} = :pk_val"),
            {"ts_val": normalized, "pk_val": pk_val},
        )


def _snapshot_sqlite_iso_strings(table: str, pk_col: str, ts_col: str) -> list[tuple[Any, str | None]]:
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"SELECT {pk_col}, {ts_col} FROM {table} WHERE {ts_col} IS NOT NULL")).fetchall()
    snapshot: list[tuple[Any, str | None]] = []
    for pk_val, raw_val in rows:
        if isinstance(raw_val, datetime):
            dt = raw_val if raw_val.tzinfo else raw_val.replace(tzinfo=timezone.utc)
            iso_str = dt.astimezone(timezone.utc).isoformat()
        else:
            parsed = _parse_iso_to_sqlite_utc(str(raw_val))
            iso_str = parsed.replace(" ", "T") + "+00:00" if parsed else None
        snapshot.append((pk_val, iso_str))
    if rows:
        conn.execute(sa.text(f"UPDATE {table} SET {ts_col} = NULL WHERE {ts_col} IS NOT NULL"))
    return snapshot


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    is_offline = op.get_context().as_sql

    if is_offline:
        existing_tables = {"webhook_events", "call_sessions"}
        wh_cols: set[str] = set()
        cs_cols: set[str] = set()
        cs_checks: set[str] = set()
    else:
        inspector = sa.inspect(bind)
        existing_tables = set(inspector.get_table_names())
        wh_cols = {col["name"] for col in inspector.get_columns("webhook_events")}
        cs_cols = {col["name"] for col in inspector.get_columns("call_sessions")}
        cs_checks = {ck["name"] for ck in inspector.get_check_constraints("call_sessions")}

    wh_ts_snapshot: list[tuple[Any, str | None]] = []
    cs_ts_snapshot: list[tuple[Any, str | None]] = []
    if dialect_name == "sqlite" and not is_offline:
        wh_ts_snapshot = _snapshot_sqlite_timestamps("webhook_events", "id", "event_created_at")
        cs_ts_snapshot = _snapshot_sqlite_timestamps("call_sessions", "call_id", "last_provider_event_at")

    with op.batch_alter_table("webhook_events") as batch_op:
        if "processed_at" not in wh_cols:
            batch_op.add_column(sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
        alter_kwargs = {
            "existing_type": sa.String(length=64),
            "type_": sa.DateTime(timezone=True),
            "existing_nullable": True,
        }
        if dialect_name == "postgresql":
            alter_kwargs["postgresql_using"] = _PG_TS_CASE.format(col="event_created_at")
        batch_op.alter_column("event_created_at", **alter_kwargs)

    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.alter_column(
            "speaker_id",
            existing_type=sa.String(length=64),
            nullable=True,
        )
        if "checks_mode" not in cs_cols:
            batch_op.add_column(
                sa.Column(
                    "checks_mode",
                    sa.String(length=32),
                    nullable=False,
                    server_default="deepfake,verify",
                )
            )
        if "consent_confirmed" not in cs_cols:
            batch_op.add_column(
                sa.Column(
                    "consent_confirmed",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "consent_recorded_at" not in cs_cols:
            batch_op.add_column(sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True))
        if "ended_at" not in cs_cols:
            batch_op.add_column(sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
        if "ended_reason" not in cs_cols:
            batch_op.add_column(sa.Column("ended_reason", sa.String(length=64), nullable=True))
        alter_kwargs = {
            "existing_type": sa.String(length=64),
            "type_": sa.DateTime(timezone=True),
            "existing_nullable": True,
        }
        if dialect_name == "postgresql":
            alter_kwargs["postgresql_using"] = _PG_TS_CASE.format(col="last_provider_event_at")
        batch_op.alter_column("last_provider_event_at", **alter_kwargs)
        if "ck_call_sessions_checks_mode" not in cs_checks:
            batch_op.create_check_constraint(
                "ck_call_sessions_checks_mode",
                "checks_mode IN ('deepfake,verify', 'deepfake', 'deepfake,enroll')",
            )
        if "ck_call_sessions_speaker_required" not in cs_checks:
            batch_op.create_check_constraint(
                "ck_call_sessions_speaker_required",
                "checks_mode = 'deepfake' OR speaker_id IS NOT NULL",
            )

    if dialect_name == "sqlite" and not is_offline:
        _restore_sqlite_timestamps("webhook_events", "id", "event_created_at", wh_ts_snapshot)
        _restore_sqlite_timestamps("call_sessions", "call_id", "last_provider_event_at", cs_ts_snapshot)

    if "speaker_profiles" not in existing_tables:
        op.create_table(
            "speaker_profiles",
            sa.Column("speaker_id", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=128), nullable=True),
            sa.Column("consent_confirmed", sa.Boolean(), nullable=False),
            sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("enrollment_status", sa.String(length=32), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("sample_count >= 0", name="ck_speaker_profiles_sample_count"),
            sa.PrimaryKeyConstraint("speaker_id"),
        )

    if "provider_operations" not in existing_tables:
        op.create_table(
            "provider_operations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("call_id", sa.String(length=128), nullable=True),
            sa.Column("speaker_id", sa.String(length=64), nullable=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("operation_type", sa.String(length=64), nullable=False),
            sa.Column("request_id", sa.String(length=160), nullable=True),
            sa.Column("operation_id", sa.String(length=160), nullable=True),
            sa.Column("stream_id", sa.String(length=160), nullable=True),
            sa.Column("idempotency_key", sa.String(length=160), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("credits", sa.Integer(), nullable=True),
            sa.Column("raw_response", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["call_id"], ["call_sessions.call_id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["speaker_id"], ["speaker_profiles.speaker_id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("operation_id", name="uq_provider_operations_operation_id"),
        )
        op.create_index("ix_provider_operations_call_id", "provider_operations", ["call_id"], unique=False)
        op.create_index("ix_provider_operations_speaker_id", "provider_operations", ["speaker_id"], unique=False)
        op.create_index("ix_provider_operations_provider", "provider_operations", ["provider"], unique=False)
        op.create_index("ix_provider_operations_operation_type", "provider_operations", ["operation_type"], unique=False)
        op.create_index("ix_provider_operations_request_id", "provider_operations", ["request_id"], unique=False)
        op.create_index("ix_provider_operations_operation_id", "provider_operations", ["operation_id"], unique=False)
        op.create_index("ix_provider_operations_stream_id", "provider_operations", ["stream_id"], unique=False)
        op.create_index("ix_provider_operations_idempotency_key", "provider_operations", ["idempotency_key"], unique=False)
        op.create_index("ix_provider_operations_status", "provider_operations", ["status"], unique=False)

    if "evidence_items" not in existing_tables:
        op.create_table(
            "evidence_items",
            sa.Column("evidence_id", sa.String(length=64), nullable=False),
            sa.Column("call_id", sa.String(length=128), nullable=False),
            sa.Column("speaker_id", sa.String(length=64), nullable=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model", sa.String(length=64), nullable=False),
            sa.Column("check_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("verdict", sa.String(length=64), nullable=True),
            sa.Column("raw_score", sa.Float(), nullable=True),
            sa.Column("score_type", sa.String(length=64), nullable=True),
            sa.Column("is_early", sa.Boolean(), nullable=True),
            sa.Column("is_final", sa.Boolean(), nullable=False),
            sa.Column("source_channel", sa.String(length=32), nullable=True),
            sa.Column("source_event_key", sa.String(length=200), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=True),
            sa.Column("provider_operation_id", sa.String(length=160), nullable=True),
            sa.Column("provider_request_id", sa.String(length=160), nullable=True),
            sa.Column("provider_stream_id", sa.String(length=160), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "check_type IN ('deepfake', 'speaker_verification', 'transcription', 'context')",
                name="ck_evidence_items_check_type",
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'completed', 'failed', 'inconclusive')",
                name="ck_evidence_items_status",
            ),
            sa.ForeignKeyConstraint(["call_id"], ["call_sessions.call_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("evidence_id"),
            sa.UniqueConstraint("evidence_id", "call_id", name="uq_evidence_items_id_call"),
            sa.UniqueConstraint(
                "call_id",
                "provider",
                "check_type",
                "source_event_key",
                name="uq_evidence_items_source_event",
            ),
        )
        op.create_index("ix_evidence_items_call_id", "evidence_items", ["call_id"], unique=False)
        op.create_index("ix_evidence_items_speaker_id", "evidence_items", ["speaker_id"], unique=False)
        op.create_index("ix_evidence_items_provider", "evidence_items", ["provider"], unique=False)
        op.create_index("ix_evidence_items_check_type", "evidence_items", ["check_type"], unique=False)
        op.create_index("ix_evidence_items_status", "evidence_items", ["status"], unique=False)
        op.create_index("ix_evidence_items_is_final", "evidence_items", ["is_final"], unique=False)
        op.create_index("ix_evidence_items_provider_operation_id", "evidence_items", ["provider_operation_id"], unique=False)
        op.create_index("ix_evidence_items_provider_request_id", "evidence_items", ["provider_request_id"], unique=False)
        op.create_index("ix_evidence_items_provider_stream_id", "evidence_items", ["provider_stream_id"], unique=False)
        op.create_index("ix_evidence_items_observed_at", "evidence_items", ["observed_at"], unique=False)

    if "trust_assessments" not in existing_tables:
        op.create_table(
            "trust_assessments",
            sa.Column("assessment_id", sa.String(length=64), nullable=False),
            sa.Column("call_id", sa.String(length=128), nullable=False),
            sa.Column("trust_score", sa.Float(), nullable=False),
            sa.Column("risk_level", sa.String(length=32), nullable=False),
            sa.Column("recommended_action", sa.String(length=32), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("reasons", sa.JSON(), nullable=False),
            sa.Column("is_final", sa.Boolean(), nullable=False),
            sa.Column("model_version", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "trust_score >= 0.0 AND trust_score <= 1.0",
                name="ck_trust_assessments_score_bounds",
            ),
            sa.CheckConstraint(
                "risk_level IN ('low', 'medium', 'high', 'critical', 'inconclusive')",
                name="ck_trust_assessments_risk_level",
            ),
            sa.CheckConstraint(
                "recommended_action IN ('allow', 'step_up_verify', 'hold', 'block')",
                name="ck_trust_assessments_action",
            ),
            sa.ForeignKeyConstraint(["call_id"], ["call_sessions.call_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("assessment_id"),
            sa.UniqueConstraint("assessment_id", "call_id", name="uq_trust_assessments_id_call"),
        )
        op.create_index("ix_trust_assessments_call_id", "trust_assessments", ["call_id"], unique=False)
        op.create_index("ix_trust_assessments_risk_level", "trust_assessments", ["risk_level"], unique=False)
        op.create_index("ix_trust_assessments_is_final", "trust_assessments", ["is_final"], unique=False)

    if "trust_assessment_evidence" not in existing_tables:
        op.create_table(
            "trust_assessment_evidence",
            sa.Column("assessment_id", sa.String(length=64), nullable=False),
            sa.Column("evidence_id", sa.String(length=64), nullable=False),
            sa.Column("call_id", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["assessment_id", "call_id"],
                ["trust_assessments.assessment_id", "trust_assessments.call_id"],
                ondelete="CASCADE",
                name="fk_tae_assessment_call",
            ),
            sa.ForeignKeyConstraint(
                ["evidence_id", "call_id"],
                ["evidence_items.evidence_id", "evidence_items.call_id"],
                ondelete="CASCADE",
                name="fk_tae_evidence_call",
            ),
            sa.PrimaryKeyConstraint("assessment_id", "evidence_id"),
        )
        op.create_index("ix_trust_assessment_evidence_call_id", "trust_assessment_evidence", ["call_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    is_offline = op.get_context().as_sql

    op.drop_index("ix_trust_assessment_evidence_call_id", table_name="trust_assessment_evidence")
    op.drop_table("trust_assessment_evidence")

    op.drop_index("ix_trust_assessments_is_final", table_name="trust_assessments")
    op.drop_index("ix_trust_assessments_risk_level", table_name="trust_assessments")
    op.drop_index("ix_trust_assessments_call_id", table_name="trust_assessments")
    op.drop_table("trust_assessments")

    op.drop_index("ix_evidence_items_observed_at", table_name="evidence_items")
    op.drop_index("ix_evidence_items_provider_stream_id", table_name="evidence_items")
    op.drop_index("ix_evidence_items_provider_request_id", table_name="evidence_items")
    op.drop_index("ix_evidence_items_provider_operation_id", table_name="evidence_items")
    op.drop_index("ix_evidence_items_is_final", table_name="evidence_items")
    op.drop_index("ix_evidence_items_status", table_name="evidence_items")
    op.drop_index("ix_evidence_items_check_type", table_name="evidence_items")
    op.drop_index("ix_evidence_items_provider", table_name="evidence_items")
    op.drop_index("ix_evidence_items_speaker_id", table_name="evidence_items")
    op.drop_index("ix_evidence_items_call_id", table_name="evidence_items")
    op.drop_table("evidence_items")

    op.drop_index("ix_provider_operations_status", table_name="provider_operations")
    op.drop_index("ix_provider_operations_idempotency_key", table_name="provider_operations")
    op.drop_index("ix_provider_operations_stream_id", table_name="provider_operations")
    op.drop_index("ix_provider_operations_operation_id", table_name="provider_operations")
    op.drop_index("ix_provider_operations_request_id", table_name="provider_operations")
    op.drop_index("ix_provider_operations_operation_type", table_name="provider_operations")
    op.drop_index("ix_provider_operations_provider", table_name="provider_operations")
    op.drop_index("ix_provider_operations_speaker_id", table_name="provider_operations")
    op.drop_index("ix_provider_operations_call_id", table_name="provider_operations")
    op.drop_table("provider_operations")

    op.drop_table("speaker_profiles")

    cs_iso_snapshot: list[tuple[Any, str | None]] = []
    wh_iso_snapshot: list[tuple[Any, str | None]] = []
    if dialect_name == "sqlite" and not is_offline:
        cs_iso_snapshot = _snapshot_sqlite_iso_strings("call_sessions", "call_id", "last_provider_event_at")
        wh_iso_snapshot = _snapshot_sqlite_iso_strings("webhook_events", "id", "event_created_at")

    # Ensure NULL speaker_id rows cannot violate NOT NULL on downgrade
    op.execute(sa.text("UPDATE call_sessions SET speaker_id = 'UNKNOWN_SPEAKER' WHERE speaker_id IS NULL"))

    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_constraint("ck_call_sessions_speaker_required", type_="check")
        batch_op.drop_constraint("ck_call_sessions_checks_mode", type_="check")
        alter_kwargs = {
            "existing_type": sa.DateTime(timezone=True),
            "type_": sa.String(length=64),
            "existing_nullable": True,
        }
        if dialect_name == "postgresql":
            alter_kwargs["postgresql_using"] = "to_char(last_provider_event_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
        batch_op.alter_column("last_provider_event_at", **alter_kwargs)
        batch_op.drop_column("ended_reason")
        batch_op.drop_column("ended_at")
        batch_op.drop_column("consent_recorded_at")
        batch_op.drop_column("consent_confirmed")
        batch_op.drop_column("checks_mode")
        batch_op.alter_column(
            "speaker_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )

    with op.batch_alter_table("webhook_events") as batch_op:
        alter_kwargs = {
            "existing_type": sa.DateTime(timezone=True),
            "type_": sa.String(length=64),
            "existing_nullable": True,
        }
        if dialect_name == "postgresql":
            alter_kwargs["postgresql_using"] = "to_char(event_created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
        batch_op.alter_column("event_created_at", **alter_kwargs)
        batch_op.drop_column("processed_at")

    if dialect_name == "sqlite" and not is_offline:
        _restore_sqlite_timestamps("call_sessions", "call_id", "last_provider_event_at", cs_iso_snapshot)
        _restore_sqlite_timestamps("webhook_events", "id", "event_created_at", wh_iso_snapshot)
