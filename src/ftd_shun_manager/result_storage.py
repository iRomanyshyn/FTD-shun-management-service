"""Bounded local-only result persistence; never repeat an agent operation."""

import json
import sqlite3
from time import monotonic, sleep

ATTEMPTS = 3
RETRY_START_SECONDS = 7.0
LOCK_WAIT_SECONDS = 2.0
DELAYS = (0.05, 0.15)


def _connect(path):
    return sqlite3.connect(path.resolve(strict=True).as_uri() + '?mode=rw',
                           uri=True, timeout=LOCK_WAIT_SECONDS)


def persist_result(store, write, *, phase):
    """Run a trusted DB-only callback with fresh checks after proved rollback.

    Only grouped ACK/result callbacks may call this. They cannot commit, execute
    device commands or modify queue memory. Successful commit is returned once;
    an error after commit or failed rollback never qualifies for retry.
    """
    if phase not in {'acknowledgement', 'addition_result'}:
        raise ValueError('Unsupported local result persistence phase.')
    started = monotonic()
    retry_error = None
    for attempt in range(ATTEMPTS):
        if attempt and monotonic() - started >= RETRY_START_SECONDS:
            raise retry_error
        db = _connect(store.path)
        db.row_factory = sqlite3.Row
        began = False
        try:
            db.execute('PRAGMA foreign_keys=ON')
            # The initialized product already uses WAL; no mode/schema change.
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                raise ValueError('Result persistence requires existing WAL storage.')
            db.execute('BEGIN IMMEDIATE')
            began = True
            result = write(db)
            if not db.in_transaction:
                raise ValueError('Result callback ended its owning transaction.')
            db.commit()
        except BaseException as error:
            code = getattr(error, 'sqlite_errorcode', None)
            busy = (isinstance(error, sqlite3.OperationalError) and type(code) is int
                    and code & 255 == sqlite3.SQLITE_BUSY)
            # A failed BEGIN is pre-write. After BEGIN, only a still-open
            # transaction whose explicit rollback succeeds supplies safe proof.
            safe = not began and not db.in_transaction
            if db.in_transaction:
                db.rollback()  # Failure propagates; never turns into retry proof.
                safe = not db.in_transaction
            if (not busy or not safe or attempt + 1 == ATTEMPTS
                    or monotonic() - started + DELAYS[attempt] >= RETRY_START_SECONDS):
                raise
            retry_error = error
        else:
            if attempt:
                print(json.dumps({'event': 'queue.result_storage.recovered', 'phase': phase,
                                  'attempts': attempt + 1}), flush=True)
            return result
        finally:
            db.close()
        print(json.dumps({'event': 'queue.result_storage.retry', 'phase': phase,
                          'attempt': attempt + 1, 'sqlite_code': code,
                          'retry_seconds': DELAYS[attempt]}), flush=True)
        sleep(DELAYS[attempt])  # Owning SQL thread only; no event-loop/SSH retry.
