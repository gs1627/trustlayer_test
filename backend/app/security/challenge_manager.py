"""Database-backed, one-use approval challenges.

The raw challenge token is returned only once and must be delivered through an
independent trusted channel (for example, the authenticated banking app), not
spoken over the call or sent to Gemini. The token hash is stored in the DB.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Column, Float, MetaData, String, Table, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


transaction_challenges = Table(
    "transaction_challenges",
    Base.metadata,
    Column("challenge_id", String(64), primary_key=True),
    Column("customer_id", String(128), nullable=False, index=True),
    Column("call_id", String(128), nullable=False, index=True),
    Column("action", String(64), nullable=False),
    Column("amount_text", String(40), nullable=True),
    Column("beneficiary_ref", String(256), nullable=True),
    Column("token_hash", String(64), nullable=False),
    Column("status", String(20), nullable=False, index=True),
    Column("expires_at_epoch", Float, nullable=False),
    Column("created_at_epoch", Float, nullable=False),
    Column("consumed_at_epoch", Float, nullable=True),
)


class ChallengeError(RuntimeError):
    pass


class ChallengeGrant(BaseModel):
    challenge_id: str
    challenge_token: str
    expires_at_epoch: float
    status: str = "issued"


class ChallengeManager:
    def __init__(self, default_ttl_seconds: int = 120):
        if not 15 <= default_ttl_seconds <= 900:
            raise ValueError("Challenge TTL must be between 15 and 900 seconds")
        self.default_ttl_seconds = default_ttl_seconds

    @staticmethod
    def _canonical_amount(amount: Decimal | float | int | str | None) -> str | None:
        if amount is None:
            return None
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Invalid monetary amount") from exc
        if not value.is_finite() or value < 0:
            raise ValueError("Amount must be a finite non-negative number")
        return format(value.quantize(Decimal("0.01")), "f")

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    async def _ensure_table(db: AsyncSession) -> None:
        # Create only this P3-owned table if the app's normal metadata setup ran
        # before this module was imported. No destructive schema operations.
        await db.run_sync(
            lambda sync_session: transaction_challenges.create(
                sync_session.connection(), checkfirst=True
            )
        )

    async def issue(
        self,
        db: AsyncSession,
        *,
        customer_id: str,
        call_id: str,
        action: str,
        amount: Decimal | float | int | str | None = None,
        beneficiary_ref: str | None = None,
        ttl_seconds: int | None = None,
    ) -> ChallengeGrant:
        if not customer_id.strip() or not call_id.strip() or not action.strip():
            raise ValueError("customer_id, call_id and action are required")
        ttl = ttl_seconds or self.default_ttl_seconds
        if not 15 <= ttl <= 900:
            raise ValueError("Challenge TTL must be between 15 and 900 seconds")

        await self._ensure_table(db)
        now = time.time()
        challenge_id = secrets.token_urlsafe(24)
        token = secrets.token_urlsafe(32)
        expires_at = now + ttl
        await db.execute(
            insert(transaction_challenges).values(
                challenge_id=challenge_id,
                customer_id=customer_id,
                call_id=call_id,
                action=action.upper(),
                amount_text=self._canonical_amount(amount),
                beneficiary_ref=beneficiary_ref,
                token_hash=self._hash_token(token),
                status="issued",
                expires_at_epoch=expires_at,
                created_at_epoch=now,
                consumed_at_epoch=None,
            )
        )
        await db.flush()
        return ChallengeGrant(
            challenge_id=challenge_id,
            challenge_token=token,
            expires_at_epoch=expires_at,
        )

    async def consume(
        self,
        db: AsyncSession,
        *,
        challenge_id: str,
        challenge_token: str,
        customer_id: str,
        call_id: str,
        action: str,
        amount: Decimal | float | int | str | None = None,
        beneficiary_ref: str | None = None,
    ) -> bool:
        """Atomically consume a challenge only when every bound field matches."""
        if not all((challenge_id, challenge_token, customer_id, call_id, action)):
            return False
        await self._ensure_table(db)
        supplied_hash = self._hash_token(challenge_token)
        row_result = await db.execute(
            select(transaction_challenges.c.token_hash).where(
                transaction_challenges.c.challenge_id == challenge_id,
                transaction_challenges.c.customer_id == customer_id,
                transaction_challenges.c.call_id == call_id,
                transaction_challenges.c.action == action.upper(),
                transaction_challenges.c.status == "issued",
            )
        )
        row = row_result.first()
        if row is None or not hmac.compare_digest(str(row[0]), supplied_hash):
            return False

        conditions = [
            transaction_challenges.c.challenge_id == challenge_id,
            transaction_challenges.c.customer_id == customer_id,
            transaction_challenges.c.call_id == call_id,
            transaction_challenges.c.action == action.upper(),
            transaction_challenges.c.amount_text == self._canonical_amount(amount),
            transaction_challenges.c.status == "issued",
            transaction_challenges.c.token_hash == supplied_hash,
            transaction_challenges.c.expires_at_epoch > time.time(),
        ]
        if beneficiary_ref is None:
            conditions.append(transaction_challenges.c.beneficiary_ref.is_(None))
        else:
            conditions.append(transaction_challenges.c.beneficiary_ref == beneficiary_ref)

        result = await db.execute(
            update(transaction_challenges)
            .where(*conditions)
            .values(status="consumed", consumed_at_epoch=time.time())
        )
        await db.flush()
        return result.rowcount == 1

    async def revoke(self, db: AsyncSession, *, challenge_id: str, customer_id: str) -> bool:
        await self._ensure_table(db)
        result = await db.execute(
            update(transaction_challenges)
            .where(
                transaction_challenges.c.challenge_id == challenge_id,
                transaction_challenges.c.customer_id == customer_id,
                transaction_challenges.c.status == "issued",
            )
            .values(status="revoked")
        )
        await db.flush()
        return result.rowcount == 1
