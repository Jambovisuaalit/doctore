"""Closing-line validation, CLV computation and settlement persistence."""
from __future__ import annotations

from typing import Any, Mapping
import json
import os

from .runtime import CLOSING_SNAPSHOT_PATH, content_sha256, now_iso, parse_time
from market_probability import calculate_market_probabilities
from .ledger import line_from_csv, log_lock, read_bet_rows, write_bet_rows
from .schemas import SettleBetInput, SettleBetOutput, SettlementResult, schema_errors


def closing_records() -> list[dict[str, Any]]:
    if not CLOSING_SNAPSHOT_PATH.exists():
        return []
    records: list[dict[str, Any]] = []
    with CLOSING_SNAPSHOT_PATH.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid closing snapshot JSONL at line {line_number}: {exc}") from exc
    return records


def append_closing_record(record: dict[str, Any]) -> bool:
    existing = [item for item in closing_records() if item.get("decision_id") == record["decision_id"]]
    if existing:
        same = (
            len(existing) == 1
            and existing[0].get("closing_snapshot_sha256") == record["closing_snapshot_sha256"]
            and existing[0].get("result") == record["result"]
            and existing[0].get("closing_missing_reason") == record.get("closing_missing_reason")
        )
        if same:
            return False
        raise ValueError(f"conflicting closing snapshot already exists for {record['decision_id']}")
    CLOSING_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CLOSING_SNAPSHOT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def profit_loss(result: SettlementResult, stake: float, odds: float) -> float:
    if result == SettlementResult.WIN:
        return stake * (odds - 1)
    if result == SettlementResult.LOSS:
        return -stake
    if result in {SettlementResult.PUSH, SettlementResult.VOID}:
        return 0.0
    if result == SettlementResult.HALF_WIN:
        return stake * 0.5 * (odds - 1)
    return -stake * 0.5


def settlement_domain_mismatches(row: Mapping[str, str], snapshot: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in ("event_id", "market_id", "sport", "competition", "selection", "book"):
        expected = row.get(key, "")
        if expected and snapshot.get(key) != expected:
            mismatches.append(key)
    for key in ("market_type", "target_market", "period", "settlement_rules"):
        expected = row.get(key, "")
        if expected and snapshot.get(key) != expected:
            mismatches.append(key)
    if row.get("line_json") and snapshot.get("line") != line_from_csv(row["line_json"]):
        mismatches.append("line")
    return mismatches


def _output(row, *, replayed=False, audit_hash=None, warning=None):
    from .settlement_store import token
    number = lambda key: float(row[key]) if row.get(key) not in (None, "") else None
    return SettleBetOutput(
        settled=True, idempotent_replay=replayed, decision_id=row["decision_id"],
        settlement_sha256=token(row), audit_sha256=audit_hash, projection_warning=warning,
        closing_odds=number("closing_odds"), closing_no_vig_probability=number("closing_no_vig_probability"),
        price_clv_pct=number("price_clv_pct"), clv_probability_points=number("clv_probability_points"),
        profit_loss=round(float(row["profit_loss"]), 2),
        closing_snapshot_sha256=row.get("closing_snapshot_sha256") or None,
        closing_missing_reason=row.get("closing_missing_reason") or None,
        closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH))


def export_projections(rows):
    """Exports may fail after commit; authoritative reads always use SQLite."""
    from .settlement_store import history
    import tempfile
    write_bet_rows(rows)
    existing = closing_records()
    legacy = [r for r in existing if "audit_sha256" not in r]
    records = legacy + history()
    CLOSING_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=CLOSING_SNAPSHOT_PATH.parent, prefix=CLOSING_SNAPSHOT_PATH.name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, CLOSING_SNAPSHOT_PATH)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def settle_bet(params: SettleBetInput) -> SettleBetOutput:
    from .settlement_store import commit, replay, token
    revision = params.revision
    request_id = "revision:" + revision.request_id if revision else "initial:" + params.decision_id
    request_sha = content_sha256(params.model_dump(mode="json"))
    with log_lock():
        rows = read_bet_rows()
        matching = [row for row in rows if row["decision_id"] == params.decision_id]
        if len(matching) != 1:
            raise ValueError("expected exactly one logged row for decision")
        row = matching[0]
        if row["placement_status"] != "PLACED":
            raise ValueError("actual placement must be confirmed before settlement")
        old_request = replay(request_id, request_sha)
        if old_request:
            warning = None
            try:
                export_projections(rows)
            except (OSError, ValueError) as exc:
                warning = "SQLite committed; projection repair required: " + str(exc)
            historical = dict(row, **old_request["after"])
            return _output(historical, replayed=True, audit_hash=old_request["audit_sha256"], warning=warning)
        if revision:
            if not row.get("result"):
                raise ValueError("revision requires an already settled bet")
            if token(row) != revision.expected_settlement_sha256:
                raise ValueError("settlement version conflict; refresh state and review again")
        elif row.get("result"):
            # Legacy settled CSVs remain readable, but changes require revision.
            same = (row["result"] == params.result.value
                    and (row.get("closing_snapshot_sha256") or None) ==
                        (content_sha256(params.closing_market_snapshot) if params.closing_market_snapshot else None)
                    and (row.get("closing_missing_reason") or None) == params.closing_missing_reason)
            if not same:
                raise ValueError("bet is already settled with different closing data")
            return _output(row, replayed=True)

        snapshot = params.closing_market_snapshot
        settled_at = params.settled_at or now_iso()
        if revision and revision.action == "CORRECT_RESULT":
            if snapshot is not None or params.closing_missing_reason is not None:
                raise ValueError("result correction preserves closing evidence; use ADD_CLOSING separately")
            if params.result.value == row["result"]:
                raise ValueError("result correction must change result")
            closing = {key: row.get(key) for key in
                ("closing_odds", "closing_no_vig_probability", "price_clv_pct", "clv_probability_points", "closing_snapshot_sha256", "closing_missing_reason")}
        else:
            if revision:
                if revision.action != "ADD_CLOSING" or snapshot is None:
                    raise ValueError("ADD_CLOSING requires a closing snapshot")
                if row.get("closing_snapshot_sha256"):
                    raise ValueError("closing evidence already exists; replacement needs a separate audited workflow")
                if params.result.value != row["result"]:
                    raise ValueError("ADD_CLOSING cannot change result")
            fair = odds = sha = None
            if snapshot is None:
                if not params.closing_missing_reason or not params.closing_missing_reason.strip():
                    raise ValueError("closing_missing_reason is required without closing data")
            else:
                if params.closing_missing_reason is not None:
                    raise ValueError("closing_missing_reason cannot accompany closing data")
                errors = schema_errors("market", snapshot)
                if errors:
                    raise ValueError("invalid closing market snapshot: " + "; ".join(errors))
                mismatches = settlement_domain_mismatches(row, snapshot)
                if row.get("event_start_at") and parse_time(row["event_start_at"]) != parse_time(snapshot["event_start_at"]):
                    mismatches.append("event_start_at")
                if mismatches:
                    raise ValueError("closing snapshot domain mismatch: " + ", ".join(mismatches))
                captured = parse_time(snapshot["captured_at"])
                if captured > parse_time(snapshot["event_start_at"]):
                    raise ValueError("closing snapshot was captured after event start")
                if captured > parse_time(settled_at):
                    raise ValueError("closing snapshot was captured after settlement")
                if captured < parse_time(row["placed_at"]):
                    raise ValueError("closing snapshot cannot precede actual placement")
                fair = calculate_market_probabilities(snapshot)["no_vig_probability"]
                odds = float(snapshot["decimal_odds"])
                sha = content_sha256(snapshot)
            closing = dict(closing_odds=odds, closing_no_vig_probability=fair,
                price_clv_pct=float(row["odds_taken"]) / odds - 1 if odds is not None else None,
                clv_probability_points=fair - float(row["market_no_vig_at_bet"]) if fair is not None else None,
                closing_snapshot_sha256=sha, closing_missing_reason=params.closing_missing_reason)
        event_start = row.get("event_start_at") or (snapshot or {}).get("event_start_at")
        if not event_start:
            raise ValueError("legacy bet lacks event_start_at; provide exact-domain closing data")
        if parse_time(settled_at) < parse_time(row["placed_at"]):
            raise ValueError("settled_at cannot be before actual placement")
        if parse_time(settled_at) < parse_time(event_start):
            raise ValueError("settled_at cannot be before event start")
        after = dict(row, **closing)
        after.update(result=params.result.value,
            profit_loss=profit_loss(params.result, float(row["actual_stake"]), float(row["odds_taken"])),
            event_start_at=event_start, settled_at=row["settled_at"] if revision else settled_at)
        record, repeated = commit(row, after, request_id=request_id, request_sha=request_sha,
            expected_token=revision.expected_settlement_sha256 if revision else token(row),
            audit=dict(schema_version="doctore.settlement-audit.v1",
                action=revision.action if revision else "SETTLE", revision=revision.model_dump() if revision else None,
                market_snapshot=snapshot, result=params.result.value,
                closing_snapshot_sha256=closing["closing_snapshot_sha256"]))
        row.update(record["after"])
        warning = None
        try:
            export_projections(rows)
        except (OSError, ValueError) as exc:
            warning = "SQLite committed; projection repair required: " + str(exc)
        return _output(row, replayed=repeated, audit_hash=record["audit_sha256"], warning=warning)
