# Transactional settlement revisions

Settlement state and audit history now commit together in SQLite (stdlib).
Database location: `<DOCTORE_BET_LOG>.settlements.sqlite3`. FULL synchronous mode,
a single database transaction and the existing ledger lock protect each write.
SQLite stores only settlement authority; approval and placement persistence retain
their existing contracts. This is not a full ledger database migration.

`read_bet_rows` overlays SQLite settlement state on CSV rows, so stale exports
cannot resurrect open liabilities or overwrite a corrected result. A missing CSV
when the settlement database exists fails closed. Legacy CSV settlements remain
readable and their pre-correction fields become the first audit before-image.
Historical LEGACY_UNCONFIRMED bets still need genuine placement migration before
settlement or revision; no placement evidence is invented.

CSV and closing JSONL are export projections. Export failures return a successful
settlement plus `projection_warning`; do not interpret that as a rolled-back write.
Retry the identical request to repair projections. SQLite remains authoritative.
Consumers reading raw CSV directly must wait for a clean export; they do not get
the overlay automatically. Do not delete the database to repair exports.

## Original settlement

The existing `doctore_settle_bet` call remains. It now returns
`settlement_sha256`, `audit_sha256` and optional `projection_warning`.
Identical requests are idempotent. A changed ordinary settlement is rejected.

## Correct a result

Call the same tool with the decision_id, corrected result, and this revision:

```json
{
  "confirmed": true,
  "action": "CORRECT_RESULT",
  "request_id": "unique-review-id",
  "expected_settlement_sha256": "<current settlement_sha256>",
  "reason": "Why the original result was wrong",
  "reviewer": "Person who verified the correction",
  "source_reference": "Bookmaker receipt or official result evidence"
}
```

The result must change. Closing evidence is preserved; do not supply a closing
snapshot or missing reason in a result correction. P/L is recalculated using
confirmed actual stake/odds. Original settled_at is preserved; recorded_at marks
the correction. Reviewer labels are declarations, not authenticated identities.
The host must require actual human instruction before invoking a revision.

## Add a previously missing close

Use action `ADD_CLOSING`, an exact-domain closing_market_snapshot, the unchanged
result and a fresh revision token. Close capture must be between actual placement
and original event start, and no later than the supplied settlement time.
The close is historical, not a current price. No missing reason may accompany it.
The prior missing reason remains in audit history; current CLV becomes computable.
Result and P/L remain unchanged. Replacing existing closing evidence and reopening
bets are intentionally unsupported, pending separate explicit policies.

## Audit and concurrency

Each event retains before/after settlement fields, reviewer/source/reason,
request identity, exact supplied close (if any), server recorded_at, previous audit
hash and its own content hash. A unique request ID binds facts and enables retry.
Reusing an ID with different facts or revising a stale version fails. The database
commits state and audit together; failure between their inserts rolls both back.
JSONL exports retain legacy records plus append-only SQLite events. Old records
are not edited to hide corrections. Existing filesystem permissions are the
security boundary; hashes are not a defense against an administrator rewriting
both data and hashes.

Back up the original CSV, placement JSONL, closing JSONL and the SQLite database
as one application backup while holding the ledger lock or using SQLite's backup
API. CSV-only backups no longer represent authoritative settlement history.
Use a local filesystem supporting SQLite locking; network filesystem durability
is not claimed. Production migration/restore on real user records was not run.
