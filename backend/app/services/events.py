from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import logging
from typing import Any, Protocol
import uuid

from app.db.models import utc_now
from app.schemas.contracts import (
    DomainEvent,
    DomainEventType,
    EvidenceItemRead,
    TrustAssessmentRead,
)

logger = logging.getLogger(__name__)


def make_domain_event(
    event_type: DomainEventType,
    *,
    call_id: str,
    payload: dict[str, Any] | None = None,
) -> DomainEvent:
    """Create a timestamped domain event envelope for internal subscribers."""
    return DomainEvent(
        event_id=f"evpub_{uuid.uuid4().hex}",
        event_type=event_type,
        call_id=call_id,
        occurred_at=utc_now(),
        payload=payload or {},
    )


class EventPublisher(Protocol):
    """Decoupled domain-event publishing contract for Priority 4/5 WebSocket fan-out."""

    async def publish(self, event: DomainEvent) -> None: ...


class NoOpEventPublisher:
    """Safe default publisher when no real-time broker is attached."""

    async def publish(self, event: DomainEvent) -> None:
        return None


class InMemoryEventBus:
    """In-process pub/sub event bus decoupled from DB repositories and REST routes."""

    def __init__(self, *, max_queue_size: int = 256) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: dict[str, tuple[str | None, asyncio.Queue[DomainEvent]]] = {}
        self._callbacks: list[Callable[[DomainEvent], Any]] = []

    def add_listener(self, callback: Callable[[DomainEvent], Any]) -> None:
        """Register an in-process listener (sync or async) for testing or adapters."""
        self._callbacks.append(callback)

    def remove_listener(self, callback: Callable[[DomainEvent], Any]) -> None:
        self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    @asynccontextmanager
    async def subscribe(self, *, call_id: str | None = None) -> AsyncIterator[asyncio.Queue[DomainEvent]]:
        """Yield an async queue receiving matching domain events (`call_id=None` receives all)."""
        sub_id = uuid.uuid4().hex
        queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[sub_id] = (call_id, queue)
        try:
            yield queue
        finally:
            self._subscribers.pop(sub_id, None)

    async def publish(self, event: DomainEvent) -> None:
        for sub_call_id, queue in list(self._subscribers.values()):
            if sub_call_id is not None and sub_call_id != event.call_id:
                continue
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping domain event %s for slow subscriber", event.event_id)

        for callback in list(self._callbacks):
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Domain event listener raised while handling %s", event.event_type)


_default_publisher: EventPublisher = InMemoryEventBus()


def get_event_publisher() -> EventPublisher:
    """FastAPI dependency and accessor returning the active internal EventPublisher."""
    return _default_publisher


def set_event_publisher(publisher: EventPublisher) -> None:
    """Swap the active internal EventPublisher (useful for Priority 4/5 adapters or tests)."""
    global _default_publisher
    _default_publisher = publisher


def reset_event_publisher() -> InMemoryEventBus:
    """Reset to a fresh InMemoryEventBus instance."""
    global _default_publisher
    bus = InMemoryEventBus()
    _default_publisher = bus
    return bus


async def publish_status_changed(
    publisher: EventPublisher,
    *,
    call_id: str,
    previous_status: str | None,
    status: str,
    ended_reason: str | None = None,
) -> None:
    """Publish a `call.status_changed` domain event."""
    await publisher.publish(
        make_domain_event(
            "call.status_changed",
            call_id=call_id,
            payload={
                "previous_status": previous_status,
                "status": status,
                "ended_reason": ended_reason,
            },
        )
    )


async def publish_evidence_added(
    publisher: EventPublisher,
    *,
    item: EvidenceItemRead,
) -> None:
    """Publish an `evidence.added` domain event for a newly persisted item."""
    await publisher.publish(
        make_domain_event(
            "evidence.added",
            call_id=item.call_id,
            payload={
                "evidence_id": item.evidence_id,
                "provider": item.provider,
                "model": item.model,
                "check_type": item.check_type,
                "status": item.status,
                "verdict": item.verdict,
                "is_early": item.is_early,
                "is_final": item.is_final,
                "source_channel": item.source_channel,
            },
        )
    )


async def publish_trust_updated(
    publisher: EventPublisher,
    *,
    assessment: TrustAssessmentRead,
) -> None:
    """Publish a `trust.updated` domain event for a newly persisted assessment."""
    await publisher.publish(
        make_domain_event(
            "trust.updated",
            call_id=assessment.call_id,
            payload={
                "assessment_id": assessment.assessment_id,
                "trust_score": assessment.trust_score,
                "risk_level": assessment.risk_level,
                "recommended_action": assessment.recommended_action,
                "is_final": assessment.is_final,
                "evidence_ids": assessment.evidence_ids,
                "model_version": assessment.model_version,
            },
        )
    )
