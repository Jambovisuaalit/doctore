from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kbo_travel_stress import KBOTravelStressInput
from kbo_stress_index import (
    KBOBullpenStressInput,
    KBORelieverWorkload,
    KBOStressInput,
    calculate_kbo_bullpen_stress,
    calculate_kbo_stress,
)


def _fresh_pen() -> KBOBullpenStressInput:
    return KBOBullpenStressInput(
        relievers=tuple(
            KBORelieverWorkload(
                pitcher_id=f"p{index}",
                role=role,
                availability="available",
                availability_confirmed=True,
            )
            for index, role in enumerate(
                ("closer", "setup", "setup", "middle", "middle", "long"),
                1,
            )
        )
    )


class KBOStressIndexTests(unittest.TestCase):
    def test_fresh_bullpen_and_same_venue_produce_zero_stress(self):
        result = calculate_kbo_stress(
            KBOStressInput(
                travel=KBOTravelStressInput(
                    door_to_door_hours=0,
                    hours_since_previous_game_end=30,
                    hours_since_arrival=0,
                    arrival_local_hour=18,
                    travel_mode="same_venue",
                    transport_confirmed=True,
                    scope="team",
                ),
                bullpen=_fresh_pen(),
            )
        )
        self.assertEqual(result.stress_index, 0.0)
        self.assertEqual(result.stress_band, "NEGLIGIBLE")

    def test_fatigued_bullpen_creates_stress_without_travel(self):
        relievers = list(_fresh_pen().relievers)
        relievers[0] = KBORelieverWorkload(
            pitcher_id="p1",
            role="closer",
            pitches_last_24h=28,
            pitches_24_to_48h=24,
            consecutive_days_used=2,
            availability="limited",
            availability_confirmed=True,
        )
        relievers[1] = KBORelieverWorkload(
            pitcher_id="p2",
            role="setup",
            pitches_last_24h=25,
            consecutive_days_used=2,
            availability="available",
            availability_confirmed=True,
        )
        bullpen_input = KBOBullpenStressInput(tuple(relievers))
        bullpen = calculate_kbo_bullpen_stress(bullpen_input)
        self.assertGreaterEqual(bullpen.stress_index, 35.0)

        result = calculate_kbo_stress(
            KBOStressInput(
                travel=KBOTravelStressInput(
                    door_to_door_hours=0,
                    hours_since_previous_game_end=30,
                    hours_since_arrival=0,
                    arrival_local_hour=18,
                    travel_mode="same_venue",
                    transport_confirmed=True,
                ),
                bullpen=bullpen_input,
            )
        )
        self.assertEqual(result.stress_index, bullpen.stress_index)
        self.assertEqual(result.dominant_component, "bullpen")

    def test_closer_workload_matters_more_than_long_reliever_workload(self):
        base = list(_fresh_pen().relievers)
        closer = base.copy()
        closer[0] = KBORelieverWorkload(
            pitcher_id="p1",
            role="closer",
            pitches_last_24h=30,
            consecutive_days_used=2,
            availability="available",
            availability_confirmed=True,
        )
        long_reliever = base.copy()
        long_reliever[-1] = KBORelieverWorkload(
            pitcher_id="p6",
            role="long",
            pitches_last_24h=30,
            consecutive_days_used=2,
            availability="available",
            availability_confirmed=True,
        )

        closer_stress = calculate_kbo_bullpen_stress(
            KBOBullpenStressInput(tuple(closer))
        )
        long_stress = calculate_kbo_bullpen_stress(
            KBOBullpenStressInput(tuple(long_reliever))
        )
        self.assertGreater(closer_stress.stress_index, long_stress.stress_index)

    def test_recent_pitch_load_exceeds_older_load(self):
        recent = list(_fresh_pen().relievers)
        older = list(_fresh_pen().relievers)
        recent[0] = KBORelieverWorkload(
            pitcher_id="p1",
            role="closer",
            pitches_last_24h=30,
            availability="available",
            availability_confirmed=True,
        )
        older[0] = KBORelieverWorkload(
            pitcher_id="p1",
            role="closer",
            pitches_48_to_72h=30,
            availability="available",
            availability_confirmed=True,
        )

        recent_stress = calculate_kbo_bullpen_stress(
            KBOBullpenStressInput(tuple(recent))
        )
        older_stress = calculate_kbo_bullpen_stress(
            KBOBullpenStressInput(tuple(older))
        )
        self.assertGreater(recent_stress.stress_index, older_stress.stress_index)

    def test_composite_adds_only_secondary_interaction(self):
        relievers = list(_fresh_pen().relievers)
        for index, role in enumerate(("closer", "setup", "setup")):
            relievers[index] = KBORelieverWorkload(
                pitcher_id=f"p{index + 1}",
                role=role,
                pitches_last_24h=25,
                consecutive_days_used=2,
                availability="available",
                availability_confirmed=True,
            )

        result = calculate_kbo_stress(
            KBOStressInput(
                travel=KBOTravelStressInput(
                    door_to_door_hours=4.5,
                    hours_since_previous_game_end=21,
                    hours_since_arrival=16,
                    arrival_local_hour=2,
                    travel_mode="team_bus",
                    transport_confirmed=True,
                    scope="team",
                ),
                bullpen=KBOBullpenStressInput(tuple(relievers)),
            )
        )
        self.assertGreater(result.stress_index, result.travel_stress_index)
        self.assertGreater(result.stress_index, result.bullpen_stress_index)
        expected = max(
            result.travel_stress_index,
            result.bullpen_stress_index,
        ) + 0.25 * min(
            result.travel_stress_index,
            result.bullpen_stress_index,
        )
        self.assertAlmostEqual(result.stress_index, round(expected, 1))

    def test_starting_pitcher_travel_cannot_be_mixed_with_team_bullpen(self):
        with self.assertRaises(ValueError):
            calculate_kbo_stress(
                KBOStressInput(
                    travel=KBOTravelStressInput(
                        door_to_door_hours=3,
                        hours_since_previous_game_end=24,
                        hours_since_arrival=18,
                        arrival_local_hour=1,
                        travel_mode="ktx",
                        transport_confirmed=True,
                        scope="starting_pitcher",
                    ),
                    bullpen=_fresh_pen(),
                )
            )


if __name__ == "__main__":
    unittest.main()
