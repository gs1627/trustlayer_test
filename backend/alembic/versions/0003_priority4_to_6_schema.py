"""Priority 4-6 schema: ownership, operation lifecycle, webhook reconciliation, simulated transactions.

Revision ID: 0003_priority4_to_6_schema
Revises: 0002_priority2_schema
Create Date: 2026-11-25 12:25:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_priority4_to_6_schema"
down_revision: Union[str, Sequence[str], None] = "0002_priority2_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_offline = op.get_context().as_sql
    if is_offline:
        existing_tables: set[str] = {
            "webhook_events",
            "speaker_profiles",
            "call_sessions",
            "provider_operations",
        }
        wh_cols: set[str] = set()
        sp_cols: set[str] = set()
        cs_cols: set[str] = set()
        po_cols: set[str] = set()
    else:
        inspector = sa.inspect(bind)
        existing_tables = set(inspector.get_table_names())
        wh_cols = {c["name"] for c in inspector.get_columns("webhook_events")}
        sp_cols = {c["name"] for c in inspector.get_columns("speaker_profiles")}
        cs_cols = {c["name"] for c in inspector.get_columns("call_sessions")}
        po_cols = {c["name"] for c in inspector.get_columns("provider_operations")}

    with op.batch_alter_table("webhook_events") as batch_op:
        if "call_id" not in wh_cols:
            batch_op.add_column(sa.Column("call_id", sa.String(length=128), nullable=True))
        if "attempt_count" not in wh_cols:
            batch_op.add_column(
                sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1")
            )
        if "last_attempt_at" not in wh_cols:
            batch_op.add_column(sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
        if "next_retry_at" not in wh_cols:
            batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
        if "dead_lettered_at" not in wh_cols:
            batch_op.add_column(sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_webhook_events_call_id", "webhook_events", ["call_id"], unique=False, if_not_exists=True)
    op.create_index("ix_webhook_events_status", "webhook_events", ["status"], unique=False, if_not_exists=True)
    op.create_index("ix_webhook_events_next_retry_at", "webhook_events", ["next_retry_at"], unique=False, if_not_exists=True)

    with op.batch_alter_table("speaker_profiles") as batch_op:
        if "owner_id" not in sp_cols:
            batch_op.add_column(sa.Column("owner_id", sa.String(length=128), nullable=True))
    op.create_index("ix_speaker_profiles_owner_id", "speaker_profiles", ["owner_id"], unique=False, if_not_exists=True)

    with op.batch_alter_table("call_sessions") as batch_op:
        if "owner_id" not in cs_cols:
            batch_op.add_column(sa.Column("owner_id", sa.String(length=128), nullable=True))
    op.create_index("ix_call_sessions_owner_id", "call_sessions", ["owner_id"], unique=False, if_not_exists=True)

    with op.batch_alter_table("provider_operations") as batch_op:
        if "correlation_id" not in po_cols:
            batch_op.add_column(sa.Column("correlation_id", sa.String(length=128), nullable=True))
        if "retry_count" not in po_cols:
            batch_op.add_column(
                sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0")
            )
        if "error_code" not in po_cols:
            batch_op.add_column(sa.Column("error_code", sa.String(length=100), nullable=True))
        if "error_message" not in po_cols:
            batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        if "failure_details" not in po_cols:
            batch_op.add_column(sa.Column("failure_details", sa.JSON(), nullable=True))
        if "started_at" not in po_cols:
            batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        if "completed_at" not in po_cols:
            batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(
            "uq_provider_operations_idempotency",
            ["provider", "operation_type", "idempotency_key"],
        )
    op.create_index("ix_provider_operations_correlation_id", "provider_operations", ["correlation_id"], unique=False, if_not_exists=True)

    if "simulated_transactions" not in existing_tables:
        op.create_table(
            "simulated_transactions",
            sa.Column("transaction_id", sa.String(length=64), nullable=False),
            sa.Column("call_id", sa.String(length=128), nullable=False),
            sa.Column("assessment_id", sa.String(length=64), nullable=True),
            sa.Column("actor_subject", sa.String(length=128), nullable=True),
            sa.Column("action_type", sa.String(length=32), nullable=False),
            sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False),
            sa.Column("recipient_ref", sa.String(length=128), nullable=True),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("decision", sa.String(length=32), nullable=False),
            sa.Column("policy_reasons", sa.JSON(), nullable=False),
            sa.Column("evidence_ids", sa.JSON(), nullable=False),
            sa.Column("policy_version", sa.String(length=32), nullable=False),
            sa.Column("simulated", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "action_type IN ('fund_transfer', 'beneficiary_add', 'credential_reset', 'limit_change')",
                name="ck_simulated_transactions_action_type",
            ),
            sa.CheckConstraint("amount > 0", name="ck_simulated_transactions_amount_positive"),
            sa.CheckConstraint(
                "decision IN ('allow', 'step_up_verify', 'hold', 'block')",
                name="ck_simulated_transactions_decision",
            ),
            sa.ForeignKeyConstraint(["call_id"], ["call_sessions.call_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assessment_id"], ["trust_assessments.assessment_id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("transaction_id"),
        )
        op.create_index("ix_simulated_transactions_call_id", "simulated_transactions", ["call_id"], unique=False)
        op.create_index("ix_simulated_transactions_assessment_id", "simulated_transactions", ["assessment_id"], unique=False)
        op.create_index("ix_simulated_transactions_decision", "simulated_transactions", ["decision"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_simulated_transactions_decision", table_name="simulated_transactions")
    op.drop_index("ix_simulated_transactions_assessment_id", table_name="simulated_transactions")
    op.drop_index("ix_simulated_transactions_call_id", table_name="simulated_transactions")
    op.drop_table("simulated_transactions")

    op.drop_index("ix_provider_operations_correlation_id", table_name="provider_operations")
    with op.batch_alter_table("provider_operations") as batch_op:
        batch_op.drop_constraint("uq_provider_operations_idempotency", type_="unique")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("failure_details")
        batch_op.drop_column("error_message")
        batch_op.drop_column("error_code")
        batch_op.drop_column("retry_count")
        batch_op.drop_column("correlation_id")

    op.drop_index("ix_call_sessions_owner_id", table_name="call_sessions")
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("owner_id")

    op.drop_index("ix_speaker_profiles_owner_id", table_name="speaker_profiles")
    with op.batch_alter_table("speaker_profiles") as batch_op:
        batch_op.drop_column("owner_id")

    op.drop_index("ix_webhook_events_next_retry_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_status", table_name="webhook_events")
    op.drop_index("ix_webhook_events_call_id", table_name="webhook_events")
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.drop_column("dead_lettered_at")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("last_attempt_at")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("call_id")
