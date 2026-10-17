"""Durable mutation pause, independent of monitoring and desired restoration."""


def mutations_suspended(db) -> bool:
    columns = {row[1] for row in db.execute("PRAGMA table_info(operation_executor)")}
    if "mutations_suspended" not in columns:
        return False  # Pre-migration/offline registry-only database.
    row = db.execute("SELECT mutations_suspended FROM operation_executor WHERE id=1").fetchone()
    if row is None or row[0] not in (0, 1):
        raise ValueError("Invalid durable mutation suspension state.")
    return bool(row[0])
