"""Strict tennis identity/freshness gate; never match names or infer source time."""
from datetime import datetime


def _time(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("timezone required")
    return t


def validate_tennis_event(context, market, evaluated_at):
    try:
        if isinstance(context, dict) and context.get("research_only") is True:
            return ["TENNIS_RESEARCH_ONLY"]
        if not isinstance(context, dict) or not isinstance(context.get("tennis_event"), dict):
            return ["TENNIS_EVENT_EVIDENCE_MISSING"]
        event = context["tennis_event"]
        registry = context.get("identity_registry", {})
        mappings = registry.get("mappings", [])
        matches = [m for m in mappings if m.get("book") == market["book"]
                   and m.get("book_market_id") == market["book_market_id"]]
        if len(matches) != 1:
            return ["TENNIS_IDENTITY_UNVERIFIED"]
        mapping = matches[0]
        required = ("source", "source_event_id", "tour", "format", "tournament_id", "round", "event_start_at", "book_event_id")
        if (mapping.get("status") != "APPROVED" or not str(mapping.get("reviewer", "")).strip()
                or mapping.get("canonical_event_id") != market["event_id"]):
            return ["TENNIS_IDENTITY_UNVERIFIED"]
        if any(not event.get(k) or event.get(k) != mapping.get(k) for k in required):
            return ["TENNIS_EVENT_IDENTITY_MISMATCH"]
        if event["tour"] not in ("atp", "wta") or event["format"] != "singles":
            return ["TENNIS_FORMAT_UNSUPPORTED"]
        source_ids, book_ids = event["source_player_ids"], event["book_player_ids"]
        if (len(source_ids) != 2 or len(set(source_ids)) != 2 or not all(isinstance(x, str) and x.strip() for x in source_ids)
                or len(book_ids) != 2 or len(set(book_ids)) != 2 or not all(isinstance(x, str) and x.strip() for x in book_ids)
                or source_ids != mapping["source_player_ids"] or book_ids != mapping["book_player_ids"]):
            return ["TENNIS_PLAYER_ID_MISMATCH"]
        if event.get("status") != "scheduled":
            return ["TENNIS_EVENT_NOT_PREMATCH"]
        now = _time(evaluated_at)
        start = _time(event["event_start_at"])
        if start != _time(market["event_start_at"]) or now >= start:
            return ["TENNIS_EVENT_IDENTITY_MISMATCH"]
        # Snapshot generation and event modification are separate concepts.
        if event.get("freshness_basis") == "provider_generated_at":
            if event.get("source") != "sportradar":
                return ["TENNIS_EVENT_FRESHNESS_UNVERIFIED"]
            digest = event.get("source_snapshot_sha256", "")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                return ["TENNIS_EVENT_FRESHNESS_UNVERIFIED"]
            freshness_at = event.get("provider_generated_at")
        else:
            freshness_at = event.get("source_updated_at")
        if not freshness_at:
            return ["TENNIS_EVENT_FRESHNESS_UNVERIFIED"]
        updated, received = _time(freshness_at), _time(event["received_at"])
        if not (updated <= received <= now) or (now-updated).total_seconds() > 120:
            return ["TENNIS_EVENT_STALE"]
        if not mapping.get("valid_until") or _time(mapping["valid_until"]) < now:
            return ["TENNIS_IDENTITY_EXPIRED"]
        return []
    except (KeyError, TypeError, ValueError, AttributeError):
        return ["TENNIS_EVENT_EVIDENCE_INVALID"]
