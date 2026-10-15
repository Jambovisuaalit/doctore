#!/usr/bin/env python3
"""Acquire complete authoritative MLB offense history for one regular season."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"scripts"))

import acquire_mlb_v2_sources as base
from mlb_v2_schedule_resolution_v4 import normalize_schedule_games_v4, hydrate_schedule_candidate_v4
from mlb_v2_source_acquisition import ScheduleResolutionError, canonical_bytes, sha256_bytes
from mlb_v4_bullpen_history import BullpenHistorySupplementError, authoritative_played_domain_game
from mlb_v4_offense_history import OffenseHistoryError, normalize_offense_history_source

PLAYED_SCHEDULE_EXCLUSION_REASONS={"NON_NINE_INNING_DOMAIN","COMPLETED_EARLY_DOMAIN"}


def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument("--season",type=int,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--workers",type=int,default=6)
    return p.parse_args()


def fetch_live(game_pk: int) -> tuple[bytes,dict]:
    raw=base.fetch_bytes(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live")
    return raw,json.loads(raw.decode("utf-8"))


def classify_candidate(candidate: dict, season: int):
    game=dict(candidate)
    if not game.get("needs_hydration"):
        return game,True,"STANDARD_TARGET_DOMAIN",None
    pk=int(game["game_pk"])
    try:
        live_bytes,live=fetch_live(pk)
    except Exception as exc:
        return None,False,None,{"game_pk":pk,"stage":"classification","reason":"LIVE_FETCH_FAILED","detail":str(exc)}
    live_sha=sha256_bytes(live_bytes)
    try:
        resolved=hydrate_schedule_candidate_v4(game,live)
    except ScheduleResolutionError as exc:
        if exc.code not in {"NON_NINE_INNING_DOMAIN","COMPLETED_EARLY_DOMAIN","CANCELLED_UNPLAYED_DOMAIN","TIED_FINAL_DOMAIN"}:
            return None,False,None,{"game_pk":pk,"stage":"classification","reason":exc.code,"detail":exc.detail}
        try:
            special,reason=authoritative_played_domain_game(live,expected_game_pk=pk,expected_season=season)
        except BullpenHistorySupplementError as err:
            return None,False,None,{"game_pk":pk,"stage":"classification","reason":err.code,"detail":err.detail}
        if special is None:
            return None,False,reason,{"game_pk":pk,"stage":"skip","reason":reason,"detail":"authoritative unplayed event"}
        special["live_hydration_sha256"]=live_sha
        return special,False,reason,None
    resolved["live_hydration_sha256"]=live_sha
    return resolved,True,"STANDARD_TARGET_DOMAIN",None


def classify_schedule_exclusion(exclusion: dict, season: int):
    pk=int(exclusion["game_pk"])
    try:
        live_bytes,live=fetch_live(pk)
        special,reason=authoritative_played_domain_game(live,expected_game_pk=pk,expected_season=season)
    except (RuntimeError,UnicodeDecodeError,json.JSONDecodeError,BullpenHistorySupplementError) as exc:
        code=exc.code if isinstance(exc,BullpenHistorySupplementError) else "LIVE_CLASSIFICATION_FAILED"
        detail=exc.detail if isinstance(exc,BullpenHistorySupplementError) else str(exc)
        return None,None,{"game_pk":pk,"stage":"classification","reason":code,"detail":detail}
    if special is None:
        return None,reason,{"game_pk":pk,"stage":"skip","reason":reason,"detail":"authoritative unplayed event"}
    special["live_hydration_sha256"]=sha256_bytes(live_bytes)
    return special,reason,None


def acquire_one(item):
    game,target_eligible,role=item
    pk=int(game["game_pk"])
    try:
        ts=base.fetch_bytes(f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live/timestamps")
        box=base.fetch_bytes(f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore")
        record=normalize_offense_history_source(
            game,timestamps_bytes=ts,boxscore_bytes=box,
            live_hydration_sha256=game.get("live_hydration_sha256"),
            target_domain_eligible=target_eligible,domain_role=role,
        )
    except (RuntimeError,OffenseHistoryError) as exc:
        return None,{"game_pk":pk,"stage":"source","reason":"OFFENSE_SOURCE_FAILED","detail":str(exc)}
    return record,None


def main() -> int:
    args=parse_args()
    if not 1900<=args.season<=2100: raise SystemExit("invalid --season")
    if not 1<=args.workers<=16: raise SystemExit("--workers must be 1..16")
    out=args.output_dir
    out.mkdir(parents=True,exist_ok=False)
    schedule_url="https://statsapi.mlb.com/api/v1/schedule?"+urlencode({"sportId":1,"season":args.season,"gameType":"R"})
    schedule_raw=base.fetch_bytes(schedule_url)
    schedule=json.loads(schedule_raw.decode("utf-8"))
    candidates,exclusions,stats=normalize_schedule_games_v4(schedule,args.season)

    classified=[]
    skips=[]
    rejects=[]
    seen=set()
    for candidate in candidates:
        game,target,role,problem=classify_candidate(candidate,args.season)
        if problem:
            (skips if problem["stage"]=="skip" else rejects).append(problem)
        if game is not None:
            pk=int(game["game_pk"])
            if pk in seen: raise RuntimeError(f"duplicate classified gamePk {pk}")
            seen.add(pk); classified.append((game,target,role))

    for exclusion in exclusions:
        if exclusion.get("reason") not in PLAYED_SCHEDULE_EXCLUSION_REASONS:
            continue
        game,role,problem=classify_schedule_exclusion(exclusion,args.season)
        if problem:
            (skips if problem["stage"]=="skip" else rejects).append(problem)
        if game is not None:
            pk=int(game["game_pk"])
            if pk in seen: continue
            seen.add(pk); classified.append((game,False,role))

    unresolved=[e for e in exclusions if e.get("reason") in {"DUPLICATE_STRICT_FINAL_CONFLICT","NO_STRICT_PLAYED_FINAL_ROW"}]
    if unresolved:
        rejects.extend({"game_pk":e.get("game_pk"),"stage":"schedule","reason":e.get("reason"),"detail":e.get("detail","")} for e in unresolved)

    records=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(acquire_one,item):int(item[0]["game_pk"]) for item in classified}
        done=0
        for future in as_completed(futures):
            record,reject=future.result()
            if record is not None: records.append(record)
            if reject is not None: rejects.append(reject)
            done+=1
            if done%250==0 or done==len(futures):
                print(f"season={args.season} completed={done}/{len(futures)} records={len(records)} rejects={len(rejects)}",flush=True)

    records.sort(key=lambda r:(r["official_date"],r["event_start_at"],r["game_pk"]))
    rejects.sort(key=lambda r:(r.get("game_pk") or -1,r["reason"]))
    skips.sort(key=lambda r:(r.get("game_pk") or -1,r["reason"]))
    if len({r["game_pk"] for r in records})!=len(records): raise RuntimeError("duplicate offense records")

    jsonl=b"".join(canonical_bytes(r) for r in records)
    records_name=f"mlb-v4-offense-history-{args.season}.jsonl"
    (out/records_name).write_bytes(jsonl)
    rejects_bytes=canonical_bytes({"schema_version":"doctore.mlb-offense-history-rejects.v1","season":args.season,"rejects":rejects})
    skips_bytes=canonical_bytes({"schema_version":"doctore.mlb-offense-history-skips.v1","season":args.season,"skips":skips})
    (out/"rejects.json").write_bytes(rejects_bytes)
    (out/"skips.json").write_bytes(skips_bytes)
    counts=Counter(r["domain_role"] for r in records)
    manifest={
        "schema_version":"doctore.mlb-offense-history-manifest.v1",
        "season":args.season,
        "created_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source":"MLB StatsAPI",
        "schedule_sha256":sha256_bytes(schedule_raw),
        "schedule_resolution_stats":stats,
        "classified_played_games":len(classified),
        "normalized_records":len(records),
        "target_domain_records":sum(1 for r in records if r["target_domain_eligible"]),
        "supplemental_played_records":sum(1 for r in records if not r["target_domain_eligible"]),
        "domain_role_counts":dict(sorted(counts.items())),
        "skip_count":len(skips),
        "reject_count":len(rejects),
        "records_file":records_name,
        "records_sha256":sha256_bytes(jsonl),
        "rejects_sha256":sha256_bytes(rejects_bytes),
        "skips_sha256":sha256_bytes(skips_bytes),
        "policy":"authoritative_complete_played_offense_history_v1",
        "workers":args.workers,
    }
    raw=canonical_bytes(manifest)
    (out/"manifest.json").write_bytes(raw)
    (out/"manifest.sha256").write_text(sha256_bytes(raw)+"\n", encoding="utf-8")
    print(json.dumps(manifest,indent=2,sort_keys=True))
    return 0 if not rejects and len(records)==len(classified) else 1


if __name__=="__main__":
    raise SystemExit(main())
