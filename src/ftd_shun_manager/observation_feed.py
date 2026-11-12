"""Private query-only metadata feed, isolated from device/control sockets."""

import argparse
import hashlib
import sqlite3
from ipaddress import IPv4Address
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import FastAPI, HTTPException, Query

MAX_PAIRS = 200000


def snapshot(path, rowid=0, event_id=None, source=None):
    path = Path(path)
    if not path.is_file():
        raise ValueError('An existing observation database is required.')
    identity = hashlib.sha256(f'{path.stat().st_dev}:{path.stat().st_ino}'.encode()).hexdigest()[:16]
    # mode=rw opens existing files only. SQLite needs writable WAL/SHM bookkeeping
    # even for reads; query_only forbids source DML/DDL. The internet-connected
    # worker receives only this narrow feed socket, never this DB mount.
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=0.5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        anchor = db.execute('SELECT id FROM shun_events WHERE rowid=?', (rowid,)).fetchone() if rowid else None
        baseline = source != identity or (rowid and (anchor is None or anchor[0] != event_id))
        if baseline:
            rows = db.execute('SELECT device_id,ip,interface FROM shun_state WHERE active=1 '
                              'ORDER BY ip,device_id,interface LIMIT ?', (MAX_PAIRS + 1,)).fetchall()
            if len(rows) > MAX_PAIRS:
                raise ValueError('Observation feed exceeds bounded capacity.')
            last = db.execute('SELECT rowid,id FROM shun_events ORDER BY rowid DESC LIMIT 1').fetchone()
            return {'source': identity, 'baseline': True, 'cursor': list(last) if last else [0, None],
                    'observations': [[row['device_id'], str(IPv4Address(row['ip'])), row['interface']] for row in rows],
                    'events': []}
        events = db.execute('SELECT rowid,id,event_type,device_id,ip,interface,timestamp '
                            'FROM shun_events WHERE rowid>? ORDER BY rowid LIMIT 1000', (rowid,)).fetchall()
        return {'source': identity, 'baseline': False, 'cursor': [events[-1]['rowid'], events[-1]['id']] if events else [rowid, event_id],
                'observations': [], 'events': [{**dict(row), 'ip': str(IPv4Address(row['ip'])) if row['ip'] else None} for row in events]}
    finally:
        db.close()


def create_app(path):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.get('/observations')
    def observations(rowid: int = Query(0, ge=0, le=2**63 - 1), event_id: UUID | None = None,
                     source: str | None = Query(None, pattern='^[a-f0-9]{16}$')):
        try:
            return snapshot(path, rowid, str(event_id) if event_id else None, source)
        except (ValueError, OSError, sqlite3.Error) as error:
            raise HTTPException(503, 'Observation feed is temporarily unavailable; no source changes were made.') from error

    @app.get('/healthz')
    def health():
        return {'status': 'ok', 'query_only': True}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--socket', required=True)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error('Existing observation database required; nothing was initialized.')
    uvicorn.run(create_app(args.source), uds=args.socket, access_log=False, limit_concurrency=4)


if __name__ == '__main__':
    main()
