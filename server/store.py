"""Private SQLite records and explicit transaction boundaries."""
import contextlib
import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ('originals', 'previews', 'crops', 'staging'):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
            CREATE TABLE IF NOT EXISTS hashes(sha TEXT PRIMARY KEY, photo_id TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, photo_id TEXT UNIQUE NOT NULL,
              state TEXT NOT NULL, attempts INTEGER DEFAULT 0, error TEXT, duration_ms INTEGER);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT, action TEXT, entity_id TEXT, data TEXT);
            ''')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'collection.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self, kind, db=None):
        if db is None:
            with self.connect() as conn:
                return self.all(kind, conn)
        return [json.loads(r[0]) for r in db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid DESC', (kind,))]

    def get(self, kind, id, db=None):
        if db is None:
            with self.connect() as conn:
                return self.get(kind, id, conn)
        row = db.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind, data, db):
        db.execute('INSERT INTO records(kind,id,data) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                   (kind, data['id'], json.dumps(data, allow_nan=False)))

    def audit(self, db, action, id, data):
        db.execute('INSERT INTO audit(at,action,entity_id,data) VALUES(?,?,?,?)', (now(), action, id, json.dumps(data)))
