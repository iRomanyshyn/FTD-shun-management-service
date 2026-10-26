"""Fixed v2 non-authoritative draft routes; never policy admission or execution."""

import sqlite3
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .bulk_intent import _uuid
from .bulk_policy import _state
from .bulk_policy_views import BulkPolicyViews
from .bulk_preparation_reports import BulkPreparationReports
from .import_preparations import PreparationCapacity, PreparationUnavailable, _present
from .import_preview import MAX_TEXT_BYTES
from .managed_safety import ManagedStateUnavailable

PREFIX = '/api/v2/managed-imports/'


class PreparationActor(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    subject: str = Field(min_length=1, max_length=255)
    display_name: str = Field(max_length=255)
    roles: list[Literal['Viewer', 'Operator', 'Administrator']] = Field(max_length=3)

    @field_validator('subject', 'display_name')
    @classmethod
    def plain_identity(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError('A plain authenticated identity is required.')
        return value

    @field_validator('subject')
    @classmethod
    def nonblank_subject(cls, value):
        if not value.strip():
            raise ValueError('An authenticated subject is required.')
        return value

    @field_validator('roles')
    @classmethod
    def distinct_roles(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Roles must be distinct.')
        return value


class PreparationOwner(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    actor: PreparationActor


class PreparationInput(PreparationOwner):
    text: str = Field(max_length=MAX_TEXT_BYTES)
    device_ids: list[Annotated[int, Field(strict=True, ge=1, le=65535)]] = Field(min_length=1, max_length=10)
    label: str = Field(default='', max_length=100)
    reason: str = Field(default='', max_length=500)

    @field_validator('text')
    @classmethod
    def utf8_size(cls, value):
        if len(value.encode('utf-8')) > MAX_TEXT_BYTES:
            raise ValueError('Paste at most 1 MiB of UTF-8 text.')
        return value

    @field_validator('device_ids')
    @classmethod
    def distinct_devices(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Select distinct explicit devices.')
        return value

    @field_validator('label', 'reason')
    @classmethod
    def plain_metadata(cls, value):
        if any(ord(char) < 32 and char not in '\t\n' for char in value):
            raise ValueError('Metadata contains unsupported control characters.')
        return value


class PreparationReference(PreparationOwner):
    preparation_id: str = Field(min_length=36, max_length=36)

    @field_validator('preparation_id')
    @classmethod
    def canonical_reference(cls, value):
        _uuid(value)
        return value


class PreparationPage(PreparationReference):
    page: int = Field(default=1, ge=1, le=1000)


class PreparationProposal(PreparationReference):
    preparation_digest: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    operation_id: str = Field(min_length=36, max_length=36)

    @field_validator('operation_id')
    @classmethod
    def canonical_operation(cls, value):
        _uuid(value)
        return value


def register_bulk_preparation_api(app, runtime):
    reports = BulkPreparationReports(runtime.store, clock=runtime.queue._now) if runtime is not None else None

    def operator(actor):
        if not {'Operator', 'Administrator'}.intersection(actor.roles):
            raise HTTPException(403, 'Operator role required for draft creation or proposal review.')

    def preparations(*, optional=False):
        if runtime is None:
            raise HTTPException(503, 'Version-2 preparations require explicit compatible continuous composition.')
        try:
            with BulkPolicyViews(runtime.store)._snapshot() as db:
                if _state(db) is None or (not _present(db) and not optional):
                    raise HTTPException(503, 'Existing exact preparation storage is required; nothing was initialized.')
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(503, 'Preparation profile is unavailable; no repair or admission was attempted.') from error
        return reports

    def failure(error):
        if isinstance(error, ManagedStateUnavailable):
            return HTTPException(503, 'Version-2 preparation state is unavailable; no policy or device work was admitted.')
        if isinstance(error, PreparationCapacity):
            return HTTPException(429, str(error))
        if isinstance(error, PreparationUnavailable):
            return HTTPException(409, str(error))
        if isinstance(error, (sqlite3.DatabaseError, TypeError, KeyError)):
            return HTTPException(503, 'Draft outcome or report is unconfirmed. Inspect the owner list; no device authority is implied.')
        return HTTPException(422, str(error))

    @app.post(PREFIX + 'prepare', status_code=201)
    def create(change: PreparationInput):
        operator(change.actor)
        source = preparations()
        try:
            value = source.create(change.text, change.device_ids, change.actor.subject, change.actor.display_name,
                                  tuple(change.actor.roles), label=change.label, reason=change.reason)
            return {**value, 'intent_format': 2, 'policy_saved': False, 'device_work_admitted': False}
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise failure(error) from error

    @app.post(PREFIX + 'preparations')
    def list_owner(change: PreparationOwner):
        source = preparations(optional=True)
        try:
            return {**source.list_for_owner(change.actor.subject), 'intent_format': 2,
                    'policy_saved': False, 'device_work_admitted': False}
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise failure(error) from error

    @app.post(PREFIX + 'preparation')
    def page(change: PreparationPage):
        source = preparations()
        try:
            return {**source.page(change.preparation_id, change.actor.subject, page=change.page),
                    'intent_format': 2, 'policy_saved': False, 'device_work_admitted': False}
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise failure(error) from error

    @app.post(PREFIX + 'proposal')
    def proposal(change: PreparationProposal):
        operator(change.actor)
        source = preparations()
        try:
            return source.propose_bulk_intent(change.preparation_id, change.actor.subject,
                                             change.preparation_digest, change.operation_id)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise failure(error) from error

    @app.post(PREFIX + 'cancel-preparation')
    def cancel(change: PreparationReference):
        source = preparations()
        try:
            changed = source.cancel(change.preparation_id, change.actor.subject)
            return {'intent_format': 2, 'preparation_id': change.preparation_id, 'cancelled': changed,
                    'can_execute': False, 'policy_saved': False, 'device_work_admitted': False}
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
            raise failure(error) from error
