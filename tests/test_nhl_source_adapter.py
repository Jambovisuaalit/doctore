"""Offline exact-source fixtures: no real bookmaker request or credential."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from doctore_mcp.nhl_source_adapter import (
    CollectNhlTotalsInput, RawDownload, collect_live_nhl_totals, normalize_provider_totals,
    _official_games, _target_pairs, _decode_json, _utc,
)

NOW = datetime(2026, 11, 1, 16, 0, 0, tzinfo=timezone.utc)


def odds_fixture(*, line_mismatch=False, missing_update=False):
    def market(over, under, line):
        item = {"key": "totals", "last_update": "2026-11-01T15:59:00Z", "outcomes": [
            {"name": "Over", "price": over, "point": line},
            {"name": "Under", "price": under, "point": line},
        ]}
        if missing_update:
            item.pop("last_update")
        return item
    return [{
        "id": "odds-event-01", "sport_key": "icehockey_nhl",
        "commence_time": "2026-11-02T02:00:00Z",
        "home_team": "Ottawa Senators", "away_team": "Anaheim Ducks",
        "bookmakers": [
            {"key": "unibet_nl", "markets": [market(2.00, 1.82, 6.5)]},
            {"key": "pinnacle", "markets": [market(1.76, 2.17, 6.0 if line_mismatch else 6.5)]},
        ],
    }]


def schedule_fixture():
    return {"gameWeek": [{"date": "2026-11-02", "games": [{
        "id": 2026020177, "startTimeUTC": "2026-11-02T02:00:00Z",
        "homeTeam": {"placeName": {"default": "Ottawa"}, "commonName": {"default": "Senators"}},
        "awayTeam": {"placeName": {"default": "Anaheim"}, "commonName": {"default": "Ducks"}},
    }]}]}


def registry_file(directory: Path, *, different_scope=False):
    rules = {"schema_version": "doctore.nhl-book-rules.v1", "books": {
        key: {
            "reviewed": True, "market_key": "totals", "period": "full_game",
            "scope": "REGULATION_60" if different_scope and key == "unibet_nl" else "REGULATION_OT_SO",
            "source_url": "https://example.org/settlement-rules/" + key,
            "verified_at": "2026-11-01T15:50:00Z", "commission_fraction": 0.0,
        } for key in ["unibet_nl", "pinnacle"]
    }}
    path = directory / "reviewed.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    return path


class AdapterUnitTests(unittest.TestCase):
    def _collect(self, directory: Path, *, odds=None, rules=None, fake_key="fake-test-key"):
        payload = odds if odds is not None else odds_fixture()
        sources = [json.dumps(payload).encode(), json.dumps(schedule_fixture()).encode()]
        seen = []
        def fetch(url, expected_host):
            seen.append((url, expected_host))
            return RawDownload(sources[len(seen) - 1], NOW)
        env = {"DOCTORE_ODDS_API_KEY": fake_key, "DOCTORE_ODDS_EVIDENCE_ROOT": str(directory / "evidence")}
        if rules is not None:
            env["DOCTORE_NHL_SETTLEMENT_RULES"] = str(rules)
        result = collect_live_nhl_totals(CollectNhlTotalsInput(), fetch=fetch,
                                         current_time=lambda: NOW, env=env)
        return result, seen, sources

    def test_no_api_key_blocks_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, seen, _ = self._collect(Path(tmp), fake_key="")
            self.assertEqual("BLOCKED_NO_ODDS_API_KEY", result.status)
            self.assertEqual([], seen)
            self.assertEqual(0, result.recommended_stake_eur)

    def test_rule_unknown_preserves_raw_and_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, seen, raw = self._collect(Path(tmp))
            self.assertEqual("BLOCKED_UNVERIFIED_QUOTES", result.status)
            self.assertEqual(0, result.normalized_quote_count)
            self.assertEqual(2, len(result.raw_evidence))
            self.assertEqual(2, len(result.excluded))
            self.assertTrue(all(x["reason_code"] == "BOOK_MARKET_RULE_UNVERIFIED" for x in result.excluded))
            saved = Path(tmp) / "evidence" / result.raw_evidence[0]["relative_path"]
            self.assertEqual(raw[0], saved.read_bytes())
            self.assertEqual(hashlib.sha256(raw[0]).hexdigest(), result.raw_evidence[0]["raw_sha256"])
            manifest = (Path(tmp) / "evidence" / "manifest.jsonl").read_text()
            self.assertEqual(2, len(manifest.splitlines()))
            self.assertNotIn("fake-test-key", manifest)
            self.assertEqual("api.the-odds-api.com", seen[0][1])
            self.assertEqual("api-web.nhle.com", seen[1][1])

    def test_official_match_and_market_observation_time(self):
        official = _official_games([schedule_fixture()])
        rules = {k: {"scope": "REGULATION_OT_SO", "source_url": "https://example.org/rules/" + k,
                     "verified_at": "2026-11-01T15:50:00Z", "commission_fraction": 0.0}
                 for k in ["unibet_nl", "pinnacle"]}
        rows, excluded, n = normalize_provider_totals(
            odds_fixture(), official, rules, captured_at=NOW,
            raw_sha256="a" * 64, allowed_pairs=_target_pairs(["Anaheim Ducks|Ottawa Senators"]))
        self.assertEqual(1, n)
        self.assertEqual(2, len(rows))
        self.assertEqual([], excluded)
        self.assertEqual("nhl:2026020177", rows[0]["canonical_event_id"])
        self.assertEqual("2026-11-01T15:59:00+00:00", rows[0]["source_observed_at"])
        self.assertEqual("2026-11-01T16:00:00+00:00", rows[0]["captured_at"])
        self.assertTrue(rows[0]["provider_quote_id"].startswith("local:sha256:"))
        self.assertEqual("local_content_digest", rows[0]["quote_id_origin"])

    def test_missing_quote_time_cannot_be_fabricated(self):
        official = _official_games([schedule_fixture()])
        rules = {"unibet_nl": {"scope": "REGULATION_OT_SO",
                 "source_url": "https://example.org/rules", "verified_at": "2026-11-01T15:50:00Z",
                 "commission_fraction": 0}}
        rows, excluded, _ = normalize_provider_totals(
            odds_fixture(missing_update=True), official, rules, captured_at=NOW,
            raw_sha256="a" * 64, allowed_pairs=_target_pairs(["Ottawa Senators|Anaheim Ducks"]))
        self.assertEqual([], rows)
        self.assertEqual("SOURCE_TIME_MISSING_OR_DATE_ONLY", excluded[0]["reason_code"])
        with self.assertRaises(ValueError):
            _utc("2026-11-01")

    def test_unresolved_event_id_quarantined(self):
        event = odds_fixture()
        event[0]["commence_time"] = "2026-11-03T02:00:00Z"
        rows, excluded, _ = normalize_provider_totals(
            event, _official_games([schedule_fixture()]), {}, captured_at=NOW,
            raw_sha256="a" * 64, allowed_pairs=_target_pairs(["Ottawa Senators|Anaheim Ducks"]))
        self.assertEqual([], rows)
        self.assertEqual("OFFICIAL_EVENT_ID_UNRESOLVED", excluded[0]["reason_code"])

    def test_response_size_cap(self):
        with self.assertRaises(ValueError):
            _decode_json(b" " * 3_000_001)

    def test_settlement_scope_conflict_never_arbitrages(self):
        from doctore_mcp.nhl_quote_scanner import scan_nhl_totals
        rules = {k: {"scope": "REGULATION_60" if k == "unibet_nl" else "REGULATION_OT_SO",
                     "source_url": "https://example.org/rules/" + k,
                     "verified_at": "2026-11-01T15:50:00Z", "commission_fraction": 0.0}
                 for k in ["unibet_nl", "pinnacle"]}
        rows, _, _ = normalize_provider_totals(
            odds_fixture(), _official_games([schedule_fixture()]), rules,
            captured_at=NOW, raw_sha256="a" * 64,
            allowed_pairs=_target_pairs(["Anaheim Ducks|Ottawa Senators"]))
        scan = scan_nhl_totals(rows, NOW.isoformat())
        self.assertEqual(0, scan.candidate_count)
        self.assertTrue(any(x["reason_code"] == "SETTLEMENT_MISMATCH" for x in scan.pair_exclusions))

    def test_line_conflict_never_arbitrages(self):
        from doctore_mcp.nhl_quote_scanner import scan_nhl_totals
        rules = {k: {"scope": "REGULATION_OT_SO", "source_url": "https://example.org/rules/" + k,
                     "verified_at": "2026-11-01T15:50:00Z", "commission_fraction": 0.0}
                 for k in ["unibet_nl", "pinnacle"]}
        rows, _, _ = normalize_provider_totals(
            odds_fixture(line_mismatch=True), _official_games([schedule_fixture()]), rules,
            captured_at=NOW, raw_sha256="a" * 64,
            allowed_pairs=_target_pairs(["Anaheim Ducks|Ottawa Senators"]))
        scan = scan_nhl_totals(rows, NOW.isoformat())
        self.assertEqual(0, scan.candidate_count)
        self.assertTrue(any(x["reason_code"] == "ALTERNATE_LINE_MISMATCH" for x in scan.pair_exclusions))

    def test_manual_reviewed_rules_end_to_end_remains_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _, _ = self._collect(Path(tmp), rules=registry_file(Path(tmp)))
            self.assertEqual("SHADOW_SCANNED", result.status)
            self.assertEqual("SHADOW", result.execution_mode)
            self.assertEqual(0, result.recommended_stake_eur)
            self.assertEqual(2, result.normalized_quote_count)
            self.assertEqual(1, result.scan["candidate_count"])
            self.assertEqual(0, result.scan["recommended_stake_eur"])


if __name__ == "__main__":
    unittest.main()
