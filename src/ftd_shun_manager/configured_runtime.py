"""Configured fenced compositions on existing storage; never a migration."""

import sqlite3
from contextlib import closing, contextmanager

from .agent_client import UnixAgentClient
from .continuous_dispatch import ContinuousDispatcher
from .inventory import load_public_inventory
from .operation_queue import QueueConflict
from .store import Store


class ExistingRuntimeStore(Store):
    """Never create a database/directory, including a missing-file startup race."""

    @contextmanager
    def _connection(self):
        with closing(sqlite3.connect(self.path.absolute().as_uri() + '?mode=rw', uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA journal_mode=WAL')
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise


def checked_inventory(store, path, expected=None):
    """Assert the complete public projection; never upsert or infer missing IDs."""
    if not store.path.is_file():
        raise QueueConflict('Configured runtime requires an existing database; nothing was initialized.')
    try:
        entries = load_public_inventory(path)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise QueueConflict('Public inventory is unavailable or invalid; no inventory was applied.') from error
    if not 1 <= len(entries) <= 10:
        raise QueueConflict('Configured continuous inventory requires 1..10 total devices, including disabled IDs.')
    if expected is not None and entries != expected:
        raise QueueConflict('Frozen public inventory changed; stop and review the configuration before restarting.')
    with store._connection() as db:
        db.execute('BEGIN')
        rows = db.execute('SELECT id,hostname,management_ip,ssh_host_key,enabled FROM devices ORDER BY id').fetchall()
        wanted = [(entry.device.id, entry.device.hostname, entry.device.management_ip.packed,
                   entry.ssh_host_key, int(entry.device.enabled)) for entry in entries]
        if [tuple(row) for row in rows] != wanted:
            raise QueueConflict('Public inventory differs from retained device identity/trust; reviewed migration is required.')
    return entries


def configured_dispatcher(settings, store):
    """No fake client, schema initialization, socket call or policy grant."""
    if settings.api_runtime not in {'continuous-observation', 'continuous-managed'} or settings.device_inventory_path is None:
        raise ValueError('Configured continuous runtime requires its explicit selector and public inventory path.')
    # Refuse absent state before any component can open/create a SQLite file.
    if not store.path.is_file():
        raise QueueConflict('Configured runtime requires existing fenced storage; nothing was initialized.')
    managed = settings.api_runtime == 'continuous-managed'
    addition_ids = frozenset()
    if managed:
        entries = checked_inventory(store, settings.device_inventory_path)
        enabled = [entry.device for entry in entries if entry.device.enabled]
        if not enabled or any(device.addition_profile is None for device in enabled):
            raise ValueError('Managed runtime requires an explicit supported ADD profile on every enabled device.')
        addition_ids = frozenset(device.id for device in enabled)
    agent = UnixAgentClient(settings.agent_socket, settings.agent_timeout_seconds + 5,
                            large_snapshots=True, settled_cycles=True, recoverable_cycles=True,
                            additions_enabled=managed, addition_device_ids=addition_ids)
    return ContinuousDispatcher(store, agent, enabled=True, agent_concurrency=settings.agent_concurrency,
                                bulk_dispatch_enabled=managed, addition_device_ids=addition_ids,
                                ordered_promotion_enabled=managed,
                                operation_timeout_seconds=settings.agent_timeout_seconds + 5,
                                poll_interval_seconds=settings.poll_interval_seconds,
                                interactive_min_interval_seconds=settings.interactive_refresh_min_interval_seconds,
                                history_retention_days=settings.history_retention_days)
