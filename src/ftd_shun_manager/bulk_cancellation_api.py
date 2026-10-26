"""Fixed whole-import revocation and local evidence; no new device authority."""

import sqlite3

from fastapi import HTTPException
from pydantic import Field, field_validator

from .bulk_intent import _uuid
from .bulk_ordered_removals import _time
from .bulk_preparation_api import PreparationOwner
from .managed_safety import ManagedStateUnavailable
from .managed_shuns import ManagedConflict

PREFIX = '/api/v2/managed-imports/'


class CancellationReference(PreparationOwner):
    operation_id: str = Field(min_length=36, max_length=36)

    @field_validator('operation_id')
    @classmethod
    def canonical_key(cls, value):
        _uuid(value)
        return value


class CancellationDecision(CancellationReference):
    reviewed_at: str = Field(min_length=24, max_length=24)
    review_digest: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    accepted_count: int = Field(ge=1, le=100000)

    @field_validator('reviewed_at')
    @classmethod
    def canonical_time(cls, value):
        return _time(value)


class CancellationPage(CancellationReference):
    page: int = Field(default=1, ge=1, le=1000)


class CancellationReviewPage(CancellationDecision):
    page: int = Field(default=1, ge=1, le=1000)


def register_bulk_cancellation_api(app, runtime):
    def service():
        if runtime is None:
            raise HTTPException(503, 'Version-2 cancellation requires existing compatible continuous storage.')
        runtime.managed_metadata()
        return runtime.import_cancellations

    def failure(error):
        if isinstance(error, PermissionError): return HTTPException(403, 'Original Operator owner or current Administrator required.')
        if isinstance(error, ManagedStateUnavailable): return HTTPException(503, 'Retained cancellation evidence unavailable; no repair or success inferred.')
        if isinstance(error, ManagedConflict): return HTTPException(409, str(error))
        if isinstance(error, (sqlite3.DatabaseError, TypeError, KeyError)):
            return HTTPException(503, 'Cancellation outcome unconfirmed; inspect or retry only the original review/actor.')
        return HTTPException(422, str(error))

    def invoke(change, action):
        coordinator = service()
        try: return action(coordinator)
        except (PermissionError, ValueError, sqlite3.DatabaseError, TypeError, KeyError) as error:
            raise failure(error) from error

    @app.post(PREFIX + 'cancellation-review')
    def review(change: CancellationReference):
        return invoke(change, lambda coordinator: coordinator.review(change.operation_id, change.actor.subject, tuple(change.actor.roles)))

    @app.post(PREFIX + 'cancellation-targets')
    def targets(change: CancellationReviewPage):
        return invoke(change, lambda coordinator: coordinator.review_page(change.operation_id, change.reviewed_at,
            change.review_digest, change.accepted_count, change.actor.subject, tuple(change.actor.roles), page=change.page))

    @app.post(PREFIX + 'cancel')
    def cancel(change: CancellationDecision):
        value = invoke(change, lambda coordinator: coordinator.cancel(change.operation_id, change.reviewed_at,
            change.review_digest, change.accepted_count, change.actor.subject, change.actor.display_name, tuple(change.actor.roles)))
        if not value['replayed']: runtime.note_state_change()  # Local revocation only; never signal work.
        return value

    @app.post(PREFIX + 'cancellation')
    def status(change: CancellationPage):
        return invoke(change, lambda coordinator: coordinator.page(change.operation_id, change.actor.subject,
            tuple(change.actor.roles), page=change.page))
