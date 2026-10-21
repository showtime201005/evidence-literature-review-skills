"""Persistent bounded work tickets and immutable JSON artifacts.

This module schedules no model calls and makes no scientific verdicts. Runtime
tools own the context/lease identity and supply validators on submission.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4


ROLES = {"reader", "comparer", "writer", "verifier", "assembly-auditor"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class TaskStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "objects").mkdir(exist_ok=True)
        self.database = self.root / "tasks.sqlite3"
        with self._transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, role TEXT NOT NULL, input_hash TEXT NOT NULL,
                    status TEXT NOT NULL, context TEXT, lease TEXT, expires REAL,
                    output_hash TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS dependencies (
                    task TEXT NOT NULL, dependency TEXT NOT NULL,
                    PRIMARY KEY(task, dependency));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    task TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
            ''')

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction:
                db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, task, kind, data):
        db.execute("INSERT INTO events(at,task,kind,data) VALUES(?,?,?,?)",
                   (time.time(), task, kind, canonical(data).decode("utf-8")))

    def put(self, value):
        raw = canonical(value)
        digest = sha256(raw).hexdigest()
        target = self.root / "objects" / (digest + ".json")
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError("Immutable artifact was modified")
            return digest
        temporary = target.with_name(uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            # Identical content concurrent writers are harmless; content is hashed.
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def get(self, digest):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid artifact hash")
        raw = (self.root / "objects" / (digest + ".json")).read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError("Artifact integrity failure")
        return json.loads(raw)

    def create(self, role, payload, dependencies=(), *, max_attempts=3):
        if role not in ROLES or max_attempts < 1:
            raise ValueError("Invalid role or attempt budget")
        dependencies = list(dependencies)
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("Duplicate dependencies")
        digest = self.put(payload)
        ticket = "t_" + uuid4().hex[:20]
        with self._transaction() as db:
            for dependency in dependencies:
                if not db.execute("SELECT id FROM tasks WHERE id=?", (dependency,)).fetchone():
                    raise ValueError("Unknown dependency")
            # Dependencies must predate creation: cycles cannot be introduced.
            db.execute("INSERT INTO tasks(id,role,input_hash,status,max_attempts) VALUES(?,?,?,'pending',?)",
                       (ticket, role, digest, max_attempts))
            db.executemany("INSERT INTO dependencies VALUES(?,?)", [(ticket, d) for d in dependencies])
            self._event(db, ticket, "created", {"role": role, "input_hash": digest, "dependencies": dependencies})
        return ticket

    @staticmethod
    def _expire(db):
        db.execute("UPDATE tasks SET status=CASE WHEN attempt>=max_attempts THEN 'failed' ELSE 'pending' END, "
                   "error='lease expired', context=NULL, lease=NULL WHERE status='running' AND expires<=?",
                   (time.time(),))

    def ready(self, limit=16):
        if not 1 <= limit <= 100:
            raise ValueError("Ready page size must be 1..100")
        with self._transaction() as db:
            self._expire(db)
            rows = db.execute("SELECT id,role,input_hash,attempt FROM tasks t WHERE status='pending' "
                "AND NOT EXISTS (SELECT 1 FROM dependencies d JOIN tasks p ON p.id=d.dependency "
                "WHERE d.task=t.id AND p.status!='accepted') ORDER BY t.rowid LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def claim(self, ticket, role, context, *, lease_seconds=600):
        if not context or lease_seconds <= 0:
            raise ValueError("Runtime context and positive lease required")
        with self._transaction() as db:
            self._expire(db)
            row = db.execute("SELECT * FROM tasks WHERE id=?", (ticket,)).fetchone()
            if row is None or row['role'] != role or row['status'] != 'pending':
                raise ValueError("Ticket is not available for this role")
            if db.execute("SELECT 1 FROM dependencies d JOIN tasks p ON p.id=d.dependency "
                          "WHERE d.task=? AND p.status!='accepted'", (ticket,)).fetchone():
                raise ValueError("Dependencies are incomplete")
            lease = uuid4().hex
            db.execute("UPDATE tasks SET status='running',context=?,lease=?,expires=?,attempt=attempt+1 WHERE id=?",
                       (context, lease, time.time()+lease_seconds, ticket))
            self._event(db, ticket, 'claimed', {"context": context, "lease": lease})
        return {"ticket": ticket, "lease": lease, "context": context,
                "input_hash": row['input_hash'], "payload": self.get(row['input_hash'])}

    @staticmethod
    def _owned(db, ticket, context, lease):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (ticket,)).fetchone()
        if (row is None or row['status'] != 'running' or row['context'] != context
                or row['lease'] != lease or row['expires'] <= time.time()):
            raise ValueError("Stale or foreign lease")
        return row

    def accept(self, ticket, context, lease, output, *, validator):
        # The validator is runtime-owned, never supplied through model arguments.
        with self._transaction() as db:
            row = self._owned(db, ticket, context, lease)
            validator(self.get(row['input_hash']), output)
            digest = self.put(output)
            db.execute("UPDATE tasks SET status='accepted',output_hash=?,expires=NULL WHERE id=?", (digest, ticket))
            receipt = {"ticket": ticket, "context": context, "input_hash": row['input_hash'],
                       "output_hash": digest, "status": "accepted"}
            self._event(db, ticket, 'accepted', receipt)
        return receipt

    def fail(self, ticket, context, lease, issue, *, retryable=False):
        with self._transaction() as db:
            row = self._owned(db, ticket, context, lease)
            status = 'pending' if retryable and row['attempt'] < row['max_attempts'] else 'failed'
            db.execute("UPDATE tasks SET status=?,error=?,expires=NULL WHERE id=?",
                       (status, canonical(issue).decode('utf-8'), ticket))
            self._event(db, ticket, 'failed', {"status": status, "issue": issue})

    def status(self):
        with self._transaction() as db:
            self._expire(db)
            return [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY rowid")]


class ScopedTaskStore:
    """Fixed readiness/status view for one stage or revision's exact tickets.

    Historical accepted/failed/obsolete tasks remain intact in ``store``. Only
    the view's tickets contribute to stage completion. Readiness still requires
    ALL actual dependencies to be accepted, including dependencies outside this
    view. Worker factories must continue claiming/accepting through the original
    TaskStore; this view exposes no mutation methods and never invents success.

    The scope is immutable. Downstream tickets created later need a new view.
    Filtering happens before the ready limit, so unrelated pending tickets
    cannot hide this stage behind the global first 100 tickets.
    """

    def __init__(self, store, tickets):
        if not isinstance(store, TaskStore):
            raise TypeError("ScopedTaskStore requires the original TaskStore")
        if isinstance(tickets, (str, bytes)):
            raise TypeError("tickets must be an iterable of ticket IDs")
        self.store = store
        self.tickets = tuple(tickets)
        if any(not isinstance(ticket, str) or not ticket for ticket in self.tickets):
            raise ValueError("Scope tickets must be nonempty strings")
        if len(set(self.tickets)) != len(self.tickets):
            raise ValueError("Duplicate scope ticket")
        known = {row['id'] for row in store.status()}
        if set(self.tickets) - known:
            raise ValueError("Unknown scope ticket")

    def _rows(self, *, ready=False, limit=None):
        rows = []
        with self.store._transaction() as db:
            self.store._expire(db)
            # Stay below older SQLite's portable 999 bound-variable limit.
            for start in range(0, len(self.tickets), 500):
                chunk = self.tickets[start:start+500]
                placeholders = ','.join('?' for _ in chunk)
                query = "SELECT t.rowid AS _scope_rowid,t.* FROM tasks t WHERE t.id IN (" + placeholders + ")"
                if ready:
                    query += (" AND t.status='pending' AND NOT EXISTS (SELECT 1 FROM dependencies d "
                              "JOIN tasks p ON p.id=d.dependency WHERE d.task=t.id AND p.status!='accepted')")
                rows.extend(dict(row) for row in db.execute(query, chunk))
        rows.sort(key=lambda row: row['_scope_rowid'])
        if limit is not None:
            rows = rows[:limit]
        if ready:
            return [{key: row[key] for key in ('id','role','input_hash','attempt')} for row in rows]
        for row in rows:
            del row['_scope_rowid']
        return rows

    def ready(self, limit=16):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Ready page size must be 1..100")
        return self._rows(ready=True, limit=limit)

    def status(self):
        return self._rows()
