# D3: operator-owned production risk authority (draft / HOLD)

This change is a production **authorization boundary**, not approval to bet.
Research/simulation remains the default. No provider credentials, trusted
operator keys, production model, account synchronization or live execution is
provisioned by this PR. Independent security review and human production GO
remain required by #70 and #65.

## Modes and trust boundary

Existing `python doctore_mcp/server.py` and the module launcher default to
research. The launcher accepts explicit operator arguments:

```text
python -m doctore_mcp --bet-log /absolute/private/bets.csv \
  --mode production --authority-root /absolute/private/operator-authority
```

Mode is never read from client payloads or environment variables. The public
DecisionInput contract still requires `risk_policy`; in production this can
only tighten the authenticated server policy. Missing/malformed client policy
fails input validation or blocks evaluation. Production startup refuses absent,
invalid, expired, unsigned, incorrectly permissioned or wrong-ledger policy.
A subsequent invalidation blocks evaluation and new approvals; there is no
fallback to client policy or research mode.

Production is currently POSIX only. The authority directory must be absolute,
owned by the runtime operator, mode 0700, and outside examples/model-artifact
roots readable through MCP. `authority.key` must be exactly 32 random bytes in
an operator-owned 0600 regular file; no symlink key/document is accepted.
The operator provisions this key out of band. Startup never creates one.

HMAC-SHA256 authenticates an **operator attestation**. It does not prove that a
bookmaker, portfolio feed or model is truthful. The server and signer share a
local OS trust principal and secret; process/host or same-user filesystem
compromise is outside this payload-only threat model. A separately protected
signer/public-key deployment and independently reviewed data adapters are
future hardening, not completed capabilities.

## Signed files

Each `policy.json` / `evidence.json` is exactly an object with `payload` and
`signature`. Signature is lowercase HMAC-SHA256 hex of UTF-8 canonical JSON:

```text
{"kind":"policy|evidence","payload":<payload>}
```

Canonicalization uses sorted keys, compact separators, Unicode output and
rejects NaN/infinity. The `kind` domain separation prevents using evidence as
policy. Key bytes and signatures are not returned by MCP or written to audit.
Private files are bounded to 2 MB and opened with `O_NOFOLLOW` where available.

Policy payload fields (all explicit; no implicit permissive defaults):

- `schema_version`: `doctore.production-authority.v1`;
- nonblank `policy_id`, `policy_version`, `valid_from`, `expires_at`, `currency`;
- `ledger_path_sha256`: SHA-256 of the resolved absolute CSV path;
- `risk_policy`: valid canonical `doctore.risk-policy.v1`. Production requires
  `allowed_calibration_statuses=["validated"]`, `block_unknown_correlation=true`
  and ordered drawdown warning/review/pause thresholds;
- `limits`: finite nonnegative `max_bankroll` (>0), `max_stake_amount`,
  `max_event_exposure_fraction` (0..1), `max_market_exposure_fraction` (0..1);
- `providers`: nonempty allowlists for `market`, `model`, `portfolio`, `context`.

Evidence payload fields (all required):

- `schema_version`: `doctore.production-evidence.v1`;
- `valid_from`, `expires_at`, `complete=true`, `coverage="external_only"`,
  `currency` equal to the server policy;
- `inputs`: exactly `market`, `model`, `portfolio`, `context`. Each has
  `sha256`, allowlisted `provider`, timezone-aware `observed_at`. The hash binds
  the complete canonical input, including the actual portfolio amounts and the
  exact event/market/model/settlement domain. A caller-supplied hash is not read;
- finite nonnegative `external_event_exposure_amount` and
  `external_market_exposure_amount`;
- `closed_ledger_decisions`: mapping from decision ID to SHA-256 of its complete
  current canonical string-valued CSV/settlement-overlay row, authenticated by
  the reviewed operator/source only after external closure verification.

The signed portfolio must be complete and **external-only**, excluding this
local ledger. Local reservations are added conservatively under the ledger
lock. There is no automatic external account watermark/reconciliation service.
If the operator cannot verify this coverage/completeness/provenance, they must
not publish a production attestation. Source age and each canonical input's own
freshness are independently checked at the current server clock.

## Publication, rotation and locking

Use the operator-only publisher, never an MCP operation:

```text
python -m doctore_mcp.operator_authority \
  --authority-root /absolute/private/operator-authority \
  --bet-log /absolute/private/bets.csv --kind policy \
  --payload /absolute/private/reviewed-policy-payload.json
```

Use `--kind evidence` for a reviewed evidence payload. The utility signs and
publishes under the same ledger lock used by approval. It fsyncs the temporary
0600 file, atomically replaces the document and fsyncs the directory. Operators
must use this path for rotation; manual uncoordinated edits are outside the
supported trusted-operator procedure. Rotation is not an environment override.

Every production evaluation uses authenticated current files and the server
clock. Approval re-reads them inside the ledger lock, recomputes the current
bound and adds existing reservations before admitting another row. Policy
version/hash change makes the submitted prior canonical decision unequal and
requires a fresh evaluation and explicit human review. A completed identical
approval retry returns the recorded fact without a second reservation; changed
facts for that decision ID are rejected.

Approval audit JSON (mode, version, policy/evidence/effective-policy hashes,
applied extra caps and request hash) commits in the **same atomic CSV row** as
the reservation. File fsync, atomic replace and parent-directory fsync provide
old-or-new publication. A pre-replace failure admits no row; a retry after an
already published row is idempotent. Existing placement/settlement journals and
replay blockers remain in use. Rejected attempts are returned as machine-readable
errors/decision diagnostics; they are not yet a separate durable denial journal.

## Non-relaxable bounds

Upper limits (caps, fractional Kelly, sizing weight, freshness and drawdown
thresholds) intersect by minimum. Qualification minima intersect by maximum.
Calibration states intersect; empty intersection blocks. Human review is always
required; unknown-correlation blocking combines with OR. Signed bankroll is
bounded by the operator maximum, never raised or fabricated by the caller.

The canonical core still computes no-vig, EV and fractional Kelly. Additional
production bounds are:

```text
remaining_event  = max(0, bankroll * max_event_fraction - verified_event_liability)
remaining_market = max(0, bankroll * max_market_fraction - verified_market_liability)
final_stake = floor_to_increment(min(canonical_stake, max_stake_amount,
                                    remaining_event, remaining_market))
```

If the extra bound is zero or below minimum stake, production returns BLOCKED
with `D3_EXPOSURE_LIMIT` and zero stake. No probability or EV is adjusted.
For bankroll 10,000, event cap 2%, event liability 100 and canonical stake 180,
remaining event capacity is 100; even an absolute cap of 150 yields 100. With
liability 250, event capacity is zero and the result blocks. A stricter client
per-bet cap of 0.1% yields at most 10. Negative EV still follows the unchanged
canonical PASS result, never promoted by this layer.

## Caller-reported execution and settlement do not release authority

Production reserves at least the approved amount (or a higher reported actual
amount). Until an exact row hash appears in authenticated closure evidence,
client-reported result/void, smaller placement or backdated `placed_at` never
release capacity. The reservation-only view treats these rows as pending and
reserves daily/rolling turnover conservatively, regardless of caller time.
Actual ledger execution facts remain unchanged for audit. This may hold capacity
longer than necessary; clearing it requires reviewed authenticated source data,
not a client timestamp, result flag or an automatic expiry.

Historical/mixed-currency/missing-identity ledger rows fail production closed.
There is no silent production migration, cancellation or rollback of liabilities.

## Compatibility and remaining gates

All 14 MCP tool names and D1 decision-input schemas remain. Research calculations
and approval semantics remain as before. Outputs add explicit `execution_mode`
and optional risk authority provenance. Decision audit accepts an additive
`risk_authority` object and D3 reason codes. CSV readers retain prior headers;
new rows include `risk_authority_json`. These are additive output/storage changes.

Before release: exact-SHA CI + 14/14 transport tests, adversarial/concurrency and
recovery checks, independent review, real provider/portfolio attestation process,
operator key management review and explicit human GO. HMAC operator assertions
are not independent validation of model calibration, profitability or external
portfolio completeness. Until these gates pass: **production HOLD**.
