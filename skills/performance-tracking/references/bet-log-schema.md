# Bet log schema

Required decision-time fields:

- bet_id, event_id, decision_at, event_start_at;
- sport, competition, market_id, market_type, period, selection, line;
- book, odds_taken_decimal, stake, units, bankroll_before;
- model_name, model_version, model_probability, sizing_probability;
- no_vig_market_probability, break_even_probability, expected_ev, edge_vs_market_pp;
- data_quality_status, candidate_tier, full_kelly, Kelly fraction, price threshold;
- correlation group and binding cap.

Settlement fields:

- closing odds and closing no-vig probability;
- result, profit/loss, void reason, notes.

Never overwrite the decision-time snapshot with closing values.
