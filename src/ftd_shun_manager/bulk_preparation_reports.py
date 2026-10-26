"""Bulk draft inspection with full retained-scope integrity, never authority."""

import hashlib
import hmac

from .bulk_policy import BulkPreparations, BulkUnavailable
from .import_preparations import PAGE_SIZE, PreparationUnavailable, _feed, _member


class BulkPreparationReports(BulkPreparations):
    """Same journal/classifier; strengthen runtime reads without migrating it."""

    def _plan(self, db, plan_id, subject):
        self._managed_state(db)  # Validate exact v2 state in this same transaction.
        row, header = super()._plan(db, plan_id, subject)
        digest = hashlib.sha256()
        _feed(digest, header)
        cursor = db.execute('SELECT * FROM import_preparation_targets WHERE plan_id=? ORDER BY device_id,ip', (plan_id,))
        while members := cursor.fetchmany(PAGE_SIZE):
            for member in members:
                _feed(digest, _member(member))
        if not hmac.compare_digest(digest.hexdigest(), row['digest']):
            raise BulkUnavailable('Original retained preparation integrity is unavailable; no reduced scope was inferred.')
        return row, header

    def _verified_plan(self, db, plan_id, subject, expected_digest):
        if not db.in_transaction:
            raise ValueError('Preparation inspection requires a caller-owned transaction.')
        if type(expected_digest) is not str or len(expected_digest) != 64 or not expected_digest.isascii():
            raise PreparationUnavailable('Invalid preparation digest.')
        # _plan streams and verifies the entire original journal exactly once.
        row, header = self._plan(db, plan_id, subject)
        if not hmac.compare_digest(expected_digest, row['digest']):
            raise PreparationUnavailable('Preparation digest does not match the original reference.')
        return row, header
