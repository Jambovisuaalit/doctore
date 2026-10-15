#!/usr/bin/env python3
'''Run MLB v2 source acquisition with authoritative v4 schedule resolution.'''
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

import acquire_mlb_v2_sources as base
from mlb_v2_schedule_resolution_v4 import (
    hydrate_schedule_candidate_v4,
    normalize_schedule_games_v4,
)


if __name__ == '__main__':
    base.normalize_schedule_games = normalize_schedule_games_v4
    base.hydrate_schedule_candidate = hydrate_schedule_candidate_v4
    raise SystemExit(base.main())
