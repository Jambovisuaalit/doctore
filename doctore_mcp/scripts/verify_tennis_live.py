#!/usr/bin/env python3
"""Explicit opt-in live read; not part of CI. Prints metadata, never bet advice."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import json
from doctore_mcp.tennis_data import TennisDataInput, fetch_tennis_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tour', choices=('atp', 'wta'), required=True)
    parser.add_argument('--command', choices=('get_scoreboard', 'get_rankings', 'get_calendar', 'get_player_info'), required=True)
    parser.add_argument('--player-id')
    args = parser.parse_args()
    params = dict(command=args.command, tour=args.tour)
    if args.command == 'get_rankings': params['limit'] = 3
    if args.player_id: params['player_id'] = args.player_id
    result = fetch_tennis_data(TennisDataInput(**params))
    data = result.data or {}
    summary = result.model_dump(exclude={'data'})
    summary['counts'] = {key: len(data[key]) for key in ('tournaments', 'rankings') if key in data}
    if args.command == 'get_rankings' and data:
        summary['ranked_players'] = [{key: row.get(key) for key in ('id', 'name', 'rank')} for row in data['rankings']]
    if args.command == 'get_player_info' and data:
        summary['player_id'] = data.get('id')
        summary['player_name'] = data.get('name')
    summary['top_level_source_fields'] = sorted(data)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if result.status == 'OK' else 1


if __name__ == '__main__':
    raise SystemExit(main())
