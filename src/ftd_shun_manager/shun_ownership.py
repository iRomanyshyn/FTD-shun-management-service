"""Read-only maintenance classification, never device-creation attribution."""

from dataclasses import replace

# Fixed SQL shared by the count and bounded rows in the same read snapshot.
UNMANAGED_FILTER = ''' AND NOT EXISTS (SELECT 1 FROM managed_shun_targets t
    WHERE t.device_id=s.device_id AND t.ip=s.ip AND t.enabled=1)'''


def policy_present(db):
    from .bulk_policy import BulkUnavailable, _state
    from .managed_safety import managed_state

    if db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'managed_bulk_*' LIMIT 1").fetchone():
        if _state(db) is None:
            raise BulkUnavailable('Managed classification requires a complete existing policy profile.')
        return True
    return managed_state(db) is not None


def classify(db, rows, has_policy):
    """Annotate only selected pairs; caller owns the validated read transaction."""
    pairs = list({(row.device_id, row.ip.packed) for row in rows})
    maintained = set()
    if has_policy:
        for start in range(0, len(pairs), 250):
            chunk = pairs[start:start + 250]
            placeholders = ','.join('(?,?)' for _ in chunk)
            maintained.update((row[0], row[1]) for row in db.execute(
                'SELECT device_id,ip FROM managed_shun_targets WHERE enabled=1 AND (device_id,ip) IN ('
                + placeholders + ')', tuple(value for pair in chunk for value in pair)))
    return [replace(row, maintained=(row.device_id, row.ip.packed) in maintained) for row in rows]
