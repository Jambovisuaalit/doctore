"""SQLite authority for settlement state and append-only revision history.

CSV/JSONL are projections. This does not migrate approval/placement authority.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from .runtime import BET_LOG_PATH, content_sha256, now_iso

FIELDS = ("closing_odds", "closing_no_vig_probability", "price_clv_pct", "clv_probability_points",
          "result", "profit_loss", "closing_snapshot_sha256", "settled_at", "event_start_at", "closing_missing_reason")


def path():
    return BET_LOG_PATH.with_suffix(BET_LOG_PATH.suffix + ".settlements.sqlite3")


def state(row):
    # CSV normalizes None to empty and numbers to decimal strings.
    return {k: "" if row.get(k) is None else str(row.get(k, "")) for k in FIELDS}


def token(row):
    return content_sha256(state(row))


@contextmanager
def connect():
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS settlement_state (decision_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS settlement_audit (seq INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_sha TEXT NOT NULL, payload TEXT NOT NULL)")
        yield connection
    finally:
        connection.close()


def overlay(rows):
    if not path().exists():
        return rows
    with connect() as db:
        patches = dict(db.execute("SELECT decision_id, payload FROM settlement_state"))
    ids = {r["decision_id"] for r in rows}
    if set(patches) - ids:
        raise ValueError("settlement database references missing ledger decisions; restore ledger before use")
    for row in rows:
        if row["decision_id"] in patches:
            row.update(json.loads(patches[row["decision_id"]]))
    return rows


def history():
    if not path().exists():
        return []
    with connect() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM settlement_audit ORDER BY seq")]


def replay(request_id, request_sha):
    if not path().exists():
        return None
    with connect() as db:
        row = db.execute("SELECT request_sha,payload FROM settlement_audit WHERE request_id=?", (request_id,)).fetchone()
    if row is None:
        return None
    if row[0] != request_sha:
        raise ValueError("settlement request_id already used with different facts")
    return json.loads(row[1])


def commit(before, after, *, request_id, request_sha, expected_token, audit):
    decision_id = before["decision_id"]
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute("SELECT request_sha,payload FROM settlement_audit WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing[0] != request_sha:
                    raise ValueError("settlement request_id conflict")
                db.execute("COMMIT")
                return json.loads(existing[1]), True
            current = db.execute("SELECT payload FROM settlement_state WHERE decision_id=?", (decision_id,)).fetchone()
            current_state = json.loads(current[0]) if current else state(before)
            if content_sha256(current_state) != expected_token:
                raise ValueError("settlement version conflict; refresh state and review again")
            previous = db.execute("SELECT payload FROM settlement_audit ORDER BY seq DESC LIMIT 1").fetchone()
            prior_hash = json.loads(previous[0])["audit_sha256"] if previous else None
            record = dict(audit, decision_id=decision_id, request_id=request_id,
                          recorded_at=now_iso(), before=current_state, after=state(after),
                          previous_audit_sha256=prior_hash)
            record["audit_sha256"] = content_sha256(record)
            db.execute("INSERT INTO settlement_audit(request_id,request_sha,payload) VALUES (?,?,?)",
                       (request_id, request_sha, json.dumps(record, sort_keys=True)))
            db.execute("INSERT INTO settlement_state VALUES (?,?) ON CONFLICT(decision_id) DO UPDATE SET payload=excluded.payload",
                       (decision_id, json.dumps(state(after), sort_keys=True)))
            db.execute("COMMIT")
            return record, False
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
