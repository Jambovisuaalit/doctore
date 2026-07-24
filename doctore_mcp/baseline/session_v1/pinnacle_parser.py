"""Original session-v1 Pinnacle parser, archived without behavioral changes."""
import csv
import io

BASEBALL_SCHEMA = [
    "away", "home", "time",
    "ml_away", "ml_home",
    "rl_away_label", "rl_away_price",
    "rl_home_label", "rl_home_price",
    "total_line", "total_over", "total_under",
    "btn", "href",
]

BASKETBALL_SCHEMA = [
    "away", "home", "time",
    "spread_away_label", "spread_away_price",
    "spread_home_label", "spread_home_price",
    "ml_away", "ml_home",
    "total_line", "total_over", "total_under",
    "btn", "href",
]

SCHEMAS = {
    "mlb": BASEBALL_SCHEMA, "kbo": BASEBALL_SCHEMA, "npb": BASEBALL_SCHEMA,
    "wnba": BASKETBALL_SCHEMA, "nba": BASKETBALL_SCHEMA,
}


def parse_pinnacle_table(raw_text: str, sport: str) -> list[dict]:
    schema = SCHEMAS[sport.lower()]
    reader = csv.reader(io.StringIO(raw_text), delimiter="\t")
    games = []
    for row in reader:
        if len(row) != len(schema):
            continue
        game = dict(zip(schema, row))
        for key in game:
            if key not in ("away", "home", "time", "href") and "label" not in key:
                try:
                    game[key] = float(game[key])
                except ValueError:
                    pass
        games.append(game)
    return games
