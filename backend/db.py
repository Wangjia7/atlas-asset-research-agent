import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get('ASSET_AGENT_DB', str(ROOT / 'data' / 'research.sqlite3')))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def insert(conn, table, **values):
    keys = ','.join(values)
    qs = ','.join('?' for _ in values)
    return conn.execute(f'INSERT INTO {table} ({keys}) VALUES ({qs})', list(values.values())).lastrowid


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    with connect() as conn:
        conn.executescript((ROOT / 'backend' / 'schema.sql').read_text())
        # Immutable research ledger: corrections are additional rows/overrides.
        for table in ['raw_sources','claims','events','event_claims','event_factor','factor_asset',
                      'human_overrides','runs','predictions','outcomes','portfolio_snapshots','evaluations']:
            for action in ['UPDATE','DELETE']:
                conn.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END")
        conn.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','1')")
