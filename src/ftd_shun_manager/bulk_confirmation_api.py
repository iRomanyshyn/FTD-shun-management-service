"""Independent default-off suspended standing policy; never queue/device work."""

import sqlite3

from fastapi import HTTPException, Request
from pydantic import Field, StrictBool

from .bulk_intent import _uuid, decode_bulk_descriptor
from .bulk_policy_views import BulkPolicyViews
from .bulk_preparation_api import PreparationOwner
from .managed_safety import ManagedStateUnavailable
from .managed_shuns import ManagedCapacity, ManagedConflict

PREFIX = '/api/v2/managed-imports/'


class BulkPolicyConfirmation(PreparationOwner):
    canonical: str = Field(min_length=1, max_length=8192)
    digest: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    accepted_count: int = Field(ge=1, le=100000)
    maintain_present: StrictBool


class BulkReceiptPage(PreparationOwner):
    operation_id: str = Field(min_length=36, max_length=36)
    page: int = Field(default=1, ge=1, le=1000)


class ConcurrentPolicyConfirmation(BulkPolicyConfirmation):
    expected_suspended: StrictBool


def register_bulk_confirmation_api(app, runtime):
    def coordinator():
        if runtime is None:
            raise HTTPException(503, 'Version-2 policy receipts require explicit compatible continuous composition.')
        runtime.managed_metadata()  # Exact existing profile; never initialize.
        return runtime.policy_revocation

    def failure(error):
        if isinstance(error, PermissionError): return HTTPException(403, str(error))
        if isinstance(error, ManagedStateUnavailable): return HTTPException(503, 'Retained bulk policy state is unavailable; no successful operation is inferred.')
        if isinstance(error, (ManagedConflict, ManagedCapacity)): return HTTPException(409, str(error))
        if isinstance(error, (sqlite3.DatabaseError, TypeError, KeyError)):
            return HTTPException(503, 'Policy outcome is unconfirmed. Inspect receipts or retry only the original frozen review/key.')
        return HTTPException(422, str(error))

    @app.post(PREFIX + 'confirm')
    def confirm(change: BulkPolicyConfirmation, request: Request):
        return save(change, request)

    @app.post(PREFIX + 'confirm-concurrent')
    def confirm_concurrent(change: ConcurrentPolicyConfirmation, request: Request):
        if runtime is None or runtime.bulk_policy_concurrent_enabled is not True:
            raise HTTPException(503, 'Concurrent standing admission is disabled; inspect original receipts.')
        return save(change, request, concurrent=True)

    def save(change, request, *, concurrent=False):
        if runtime is None or runtime.bulk_policy_admission_enabled is not True:
            raise HTTPException(503, 'Version-2 standing policy admission is disabled; inspect any earlier receipt.')
        if not {'Operator', 'Administrator'}.intersection(change.actor.roles):
            raise HTTPException(403, 'Current Operator/Administrator required.')
        service = coordinator()
        try:
            descriptor = decode_bulk_descriptor(change.canonical, change.digest)
            key = request.headers.get('Idempotency-Key', '')
            _uuid(key)
            if key != descriptor['operation_id']:
                raise ValueError('Original request key must equal the frozen descriptor operation UUID.')
            method = service.confirm_concurrent if concurrent else service.confirm
            result = method(change.canonical, change.digest, change.accepted_count,
                change.actor.subject, change.actor.display_name, tuple(change.actor.roles),
                maintain_present=change.maintain_present, enabled=True,
                addition_device_ids=runtime.bulk_policy_device_ids,
                **({'expected_suspended': change.expected_suspended} if concurrent else {}))
        except (PermissionError, ValueError, sqlite3.DatabaseError, TypeError, KeyError) as error:
            raise failure(error) from error
        if not result['replayed']:
            runtime.note_state_change()
            if runtime.managed_execution is True and result['changed_targets'] > 0:
                runtime.dispatcher.request_policy_scan(frozenset(descriptor['manifest']['device_ids']))
        return result

    @app.post(PREFIX + 'receipts')
    def receipts(change: PreparationOwner):
        service = coordinator()
        try:
            return {**service.list_for_owner(change.actor.subject), 'intent_format': 2, 'device_work_admitted': False}
        except (ValueError, sqlite3.DatabaseError, TypeError, KeyError) as error:
            raise failure(error) from error

    @app.post(PREFIX + 'receipt')
    def receipt(change: BulkReceiptPage):
        service = coordinator()
        try:
            _uuid(change.operation_id)
            value = service.page(change.operation_id, change.actor.subject, page=change.page)
            with BulkPolicyViews(runtime.store)._snapshot() as db:
                # This read never depends on an expired/pruned preparation.
                row = db.execute('''SELECT r.payload_json,m.payload_digest FROM managed_shun_requests r
                    JOIN managed_bulk_manifests m ON m.id=r.id WHERE r.id=? AND r.actor_subject=?''',
                                 (change.operation_id, change.actor.subject)).fetchone()
                if row is None: raise ValueError('Original receipt unavailable.')
                value['canonical'] = row['payload_json']
                value['digest'] = row['payload_digest']
            return value
        except (ValueError, sqlite3.DatabaseError, TypeError, KeyError) as error:
            raise failure(error) from error
