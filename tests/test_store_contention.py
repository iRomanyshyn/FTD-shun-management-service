"""Real WAL readers/writers, durable result settings and no transaction replay."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from ftd_shun_manager import result_storage
from ftd_shun_manager import store as store_module
from ftd_shun_manager.configured_runtime import ExistingRuntimeStore
from ftd_shun_manager.store import Store


@pytest.fixture(params=[Store, ExistingRuntimeStore])
def store(tmp_path, request):
    result = Store(tmp_path / 'private-state.db')
    result.initialize()
    with result._connection() as db:
        db.execute('CREATE TABLE contention_fixture (value INTEGER NOT NULL)')
        db.execute('INSERT INTO contention_fixture VALUES (0)')
    return request.param(result.path)


def trace_connections(monkeypatch, statements, *, on_begin=None):
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        db = connect(*args, **kwargs)

        def trace(sql):
            statements.append(sql)
            if on_begin is not None and sql == 'BEGIN IMMEDIATE':
                on_begin.set()

        db.set_trace_callback(trace)
        return db

    monkeypatch.setattr(sqlite3, 'connect', traced)


def test_reopened_store_enforces_durability_without_reselecting_wal(store, monkeypatch):
    statements = []
    trace_connections(monkeypatch, statements)
    for instance in (store, Store(store.path)):
        with instance._connection() as db:
            assert db.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
            assert db.execute('PRAGMA synchronous').fetchone()[0] == 2  # FULL
            assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
            assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            assert db.execute('SELECT value FROM contention_fixture').fetchone()[0] == 0
    assert not any('journal_mode =' in sql for sql in statements)


def test_existing_rollback_database_can_still_be_initialized_in_wal(tmp_path):
    path = tmp_path / 'rollback.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE retained (value INTEGER)')
        db.execute('INSERT INTO retained VALUES (42)')
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    store = Store(path)
    store.initialize()
    with store._connection() as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert db.execute('SELECT value FROM retained').fetchone()[0] == 42


def test_wal_reader_keeps_a_consistent_snapshot_while_another_writer_commits(store):
    writer = sqlite3.connect(store.path)
    try:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('UPDATE contention_fixture SET value=1')
        with store._connection() as reader:
            reader.execute('BEGIN')
            assert reader.execute('SELECT value FROM contention_fixture').fetchone()[0] == 0
            writer.commit()
            assert reader.execute('SELECT value FROM contention_fixture').fetchone()[0] == 0
        with store._connection() as reader:
            assert reader.execute('SELECT value FROM contention_fixture').fetchone()[0] == 1
    finally:
        writer.close()


def test_competing_writer_waits_then_runs_the_body_once(store, monkeypatch, capsys):
    writer = sqlite3.connect(store.path)
    writer.execute('BEGIN IMMEDIATE')
    attempted = Event()
    statements, calls = [], []
    trace_connections(monkeypatch, statements, on_begin=attempted)

    def write():
        with store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            calls.append(True)
            db.execute('UPDATE contention_fixture SET value=value+1')

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(write)
            try:
                assert attempted.wait(2), 'The contender did not reach BEGIN.'
                assert not future.done()
            finally:
                writer.rollback()
            future.result(timeout=5)
    finally:
        writer.close()
    assert calls == [True] and statements.count('BEGIN IMMEDIATE') == 1
    with store._connection() as db:
        assert db.execute('SELECT value FROM contention_fixture').fetchone()[0] == 1
    assert not capsys.readouterr().out


def test_expired_writer_wait_is_reported_without_sql_or_a_retry(store, monkeypatch, capsys):
    writer = sqlite3.connect(store.path)
    writer.execute('BEGIN IMMEDIATE')
    monkeypatch.setattr(store_module, 'SQLITE_LOCK_WAIT_SECONDS', 0.02)
    calls = []
    try:
        with pytest.raises(sqlite3.OperationalError) as caught, store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            calls.append(True)
    finally:
        writer.close()
    assert caught.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
    assert not calls
    report = json.loads(capsys.readouterr().out)
    assert report['event'] == 'store.sqlite_contention'
    assert report['phase'] == 'transaction'
    assert report['sqlite_code'] == sqlite3.SQLITE_BUSY
    assert report['elapsed_seconds'] >= 0
    assert set(report) == {'event', 'phase', 'sqlite_code', 'elapsed_seconds'}


def test_busy_snapshot_preserves_original_error_and_rolls_back_without_replay(store, capsys):
    writer = sqlite3.connect(store.path)
    calls = []
    try:
        with pytest.raises(sqlite3.OperationalError) as caught, store._connection() as reader:
            reader.execute('BEGIN')
            reader.execute('SELECT value FROM contention_fixture').fetchall()
            writer.execute('UPDATE contention_fixture SET value=1')
            writer.commit()
            calls.append(True)
            reader.execute('UPDATE contention_fixture SET value=99')
    finally:
        writer.close()
    assert caught.value.sqlite_errorcode == sqlite3.SQLITE_BUSY_SNAPSHOT
    assert calls == [True]
    assert json.loads(capsys.readouterr().out)['sqlite_code'] == sqlite3.SQLITE_BUSY_SNAPSHOT
    with store._connection() as db:
        assert db.execute('SELECT value FROM contention_fixture').fetchone()[0] == 1


@pytest.mark.parametrize('error', [ValueError('private SQL or identity'), KeyboardInterrupt()])
def test_exception_or_interruption_rolls_back_and_is_not_logged_as_contention(store, capsys, error):
    with pytest.raises(type(error)), store._connection() as db:
        db.execute('UPDATE contention_fixture SET value=99')
        raise error
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute('SELECT 1')  # Closed even when the caller is interrupted.
    with store._connection() as reopened:
        assert reopened.execute('SELECT value FROM contention_fixture').fetchone()[0] == 0
    assert not capsys.readouterr().out


def test_configuration_failure_still_closes_the_connection(store, monkeypatch):
    connections = []

    def fail(db):
        connections.append(db)
        raise ValueError('Synthetic failed UDF installation')

    monkeypatch.setattr(type(store.environment_protection), 'install', lambda self, db: fail(db))
    with pytest.raises(ValueError, match='Synthetic'), store._connection():
        pytest.fail('Must not yield an unconfigured connection.')
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute('SELECT 1')


def test_local_result_writer_keeps_its_separate_two_second_wait_and_full_sync(store):
    def write(db):
        assert db.execute('PRAGMA busy_timeout').fetchone()[0] == 2000
        assert db.execute('PRAGMA synchronous').fetchone()[0] == 2
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        db.execute('INSERT INTO contention_fixture VALUES (7)')
        return 'stored'

    assert result_storage.persist_result(store, write, phase='pending_checkpoint') == 'stored'
    with store._connection() as db:
        assert [row[0] for row in db.execute('SELECT value FROM contention_fixture')] == [0, 7]


@pytest.mark.parametrize('parent_exists', [False, True])
def test_runtime_store_never_creates_missing_storage(tmp_path, parent_exists):
    path = tmp_path / 'missing-parent' / 'state.db'
    if parent_exists:
        path.parent.mkdir()
    store = ExistingRuntimeStore(path)
    with pytest.raises(sqlite3.OperationalError) as caught, store._connection():
        pytest.fail('Missing existing-runtime storage must refuse.')
    assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CANTOPEN
    assert not path.exists()
    assert path.parent.exists() is parent_exists


def test_runtime_store_checks_the_file_on_every_connection(store):
    runtime = ExistingRuntimeStore(store.path)
    with runtime._connection() as db:
        assert db.execute('SELECT value FROM contention_fixture').fetchone()[0] == 0
    archive = store.path.with_suffix('.retained.db')
    store.path.rename(archive)
    with pytest.raises(sqlite3.OperationalError), runtime._connection():
        pytest.fail('Must not recreate a disappeared initialized database.')
    assert archive.exists() and not store.path.exists()
