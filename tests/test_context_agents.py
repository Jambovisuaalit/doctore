from doctore_mcp.context_agents import ContextGateInput, run_context_agent


def base_input(sport: str, signals: dict) -> ContextGateInput:
    return ContextGateInput(
        sport=sport,
        event_id="event-1",
        market_id="market-1",
        competition=sport.upper(),
        participants=["A", "B"],
        scheduled_start_at="2026-07-29T18:00:00+03:00",
        evaluated_at="2026-07-29T15:00:00+03:00",
        evidence=[],
        structured_signals=signals,
    )


def test_mlb_context_clear():
    result = run_context_agent(base_input("mlb", {
        "game_status": "SCHEDULED",
        "market_state": "PREGAME",
        "starting_pitcher_status": "CONFIRMED",
        "lineup_status": "CONFIRMED",
        "weather_risk": "LOW",
    }))
    assert result.status == "CLEAR"
    assert result.reason_codes == ["MLB_CONTEXT_CLEAR"]


def test_mlb_context_blocks_in_play():
    result = run_context_agent(base_input("mlb", {"market_state": "IN_PLAY"}))
    assert result.status == "BLOCKED"
    assert "MLB_MARKET_IN_PLAY" in result.reason_codes


def test_kbo_context_watch_on_travel_stress():
    result = run_context_agent(base_input("kbo", {
        "game_status": "SCHEDULED",
        "market_state": "PREGAME",
        "starting_pitcher_status": "CONFIRMED",
        "lineup_status": "CONFIRMED",
        "weather_risk": "LOW",
        "travel_stress_status": "HIGH",
    }))
    assert result.status == "WATCH"
    assert "KBO_HIGH_TRAVEL_STRESS" in result.reason_codes


def test_tennis_blocks_official_withdrawal():
    result = run_context_agent(base_input("tennis", {"official_withdrawal": True}))
    assert result.status == "BLOCKED"
    assert result.reason_codes == ["TENNIS_OFFICIAL_WITHDRAWAL"]


def test_tennis_watch_on_recent_retirement():
    result = run_context_agent(base_input("tennis", {
        "official_withdrawal": False,
        "recent_retirement": True,
        "research_complete": True,
    }))
    assert result.status == "WATCH"
    assert "TENNIS_RECENT_RETIREMENT" in result.reason_codes


def test_nba_and_soccer_fail_closed():
    for sport in ("nba", "soccer"):
        result = run_context_agent(base_input(sport, {}))
        assert result.status == "BLOCKED"
        assert result.reason_codes == ["CONTEXT_AGENT_NOT_IMPLEMENTED"]
