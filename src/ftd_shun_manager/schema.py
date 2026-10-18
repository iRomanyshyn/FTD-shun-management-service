"""Trusted constant SQL only, with no executescript() implicit transaction commit."""

import sqlite3
from contextlib import contextmanager


@contextmanager
def schema_connection(store, connection=None):
    if connection is not None:
        if not connection.in_transaction:
            raise ValueError("Schema composition requires a caller-owned transaction.")
        yield connection
    else:
        with store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db


def execute_schema(db, script):
    """Execute complete trusted statements, including triggers, without committing."""
    if not db.in_transaction:
        raise ValueError("Schema composition requires a caller-owned transaction.")
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete trusted schema statement.")
