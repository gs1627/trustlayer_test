"""Initial Priority 1 schema baseline (call_sessions and webhook_events).

Revision ID: 0001_initial_priority1
Revises:
Create Date: 2026-11-25 11:36:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_priority1"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("delivery_id", sa.String(length=160), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_created_at", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", name="uq_webhook_delivery_id"),
    )
    op.create_index("ix_webhook_events_delivery_id", "webhook_events", ["delivery_id"], unique=False)
    op.create_index("ix_webhook_events_event_id", "webhook_events", ["event_id"], unique=False)
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"], unique=False)

    op.create_table(
        "call_sessions",
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("speaker_id", sa.String(length=64), nullable=False),
        sa.Column("provider_stream_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("last_deepfake_sequence", sa.Integer(), nullable=False),
        sa.Column("last_provider_event_at", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("call_id"),
    )
    op.create_index("ix_call_sessions_provider_stream_id", "call_sessions", ["provider_stream_id"], unique=False)
    op.create_index("ix_call_sessions_speaker_id", "call_sessions", ["speaker_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_call_sessions_speaker_id", table_name="call_sessions")
    op.drop_index("ix_call_sessions_provider_stream_id", table_name="call_sessions")
    op.drop_table("call_sessions")

    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_delivery_id", table_name="webhook_events")
    op.drop_table("webhook_events")
