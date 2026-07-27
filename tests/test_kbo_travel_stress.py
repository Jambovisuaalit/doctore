from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kbo_travel_stress import KBOTravelStressInput, calculate_kbo_travel_stress


class KBOTravelStressTests(unittest.TestCase):
    def test_same_venue_cannot_create_travel_stress(self):
        result = calculate_kbo_travel_stress(
            KBOTravelStressInput(
                door_to_door_hours=0,
                hours_since_previous_game_end=16,
                hours_since_arrival=0,
                arrival_local_hour=3,
                consecutive_away_series=3,
                previous_game_extra_innings=True,
                travel_mode="same_venue",
                transport_confirmed=True,
            )
        )
        self.assertEqual(result.stress_index, 0.0)
        self.assertEqual(result.stress_band, "NEGLIGIBLE")

    def test_confirmed_ktx_reduces_long_route_stress(self):
        common = dict(
            hours_since_previous_game_end=21,
            hours_since_arrival=16.5,
            consecutive_away_series=2,
        )
        bus = calculate_kbo_travel_stress(
            KBOTravelStressInput(
                door_to_door_hours=4.5,
                arrival_local_hour=2.0,
                travel_mode="team_bus",
                transport_confirmed=True,
                **common,
            )
        )
        ktx = calculate_kbo_travel_stress(
            KBOTravelStressInput(
                door_to_door_hours=3.3,
                arrival_local_hour=0.5,
                travel_mode="ktx",
                transport_confirmed=True,
                scope="starting_pitcher",
                **common,
            )
        )
        self.assertGreater(bus.stress_index, ktx.stress_index)
        self.assertGreaterEqual(bus.stress_index - ktx.stress_index, 20.0)

    def test_unconfirmed_ktx_is_not_credited(self):
        unconfirmed = calculate_kbo_travel_stress(
            KBOTravelStressInput(
                door_to_door_hours=4.0,
                hours_since_previous_game_end=21,
                hours_since_arrival=16,
                arrival_local_hour=1.0,
                travel_mode="ktx",
                transport_confirmed=False,
            )
        )
        bus = calculate_kbo_travel_stress(
            KBOTravelStressInput(
                door_to_door_hours=4.0,
                hours_since_previous_game_end=21,
                hours_since_arrival=16,
                arrival_local_hour=1.0,
                travel_mode="team_bus",
                transport_confirmed=True,
            )
        )
        self.assertEqual(unconfirmed.stress_index, bus.stress_index)
        self.assertIn(
            "UNCONFIRMED_TRANSPORT_MODE_TREATED_AS_TEAM_BUS",
            unconfirmed.warnings,
        )

    def test_travel_burden_decays_after_arrival(self):
        game_one = calculate_kbo_travel_stress(
            KBOTravelStressInput(
                door_to_door_hours=4.5,
                hours_since_previous_game_end=21,
                hours_since_arrival=16,
                arrival_local_hour=2.0,
                travel_mode="team_bus",
                transport_confirmed=True,
            )
        )
        game_two = calculate_kbo_travel_stress(
            KBOTravelStressInput(
                door_to_door_hours=4.5,
                hours_since_previous_game_end=45,
                hours_since_arrival=40,
                arrival_local_hour=2.0,
                travel_mode="team_bus",
                transport_confirmed=True,
            )
        )
        self.assertLess(game_two.stress_index, game_one.stress_index)
        self.assertLess(game_two.stress_index, game_one.stress_index * 0.55)

    def test_invalid_hour_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_kbo_travel_stress(
                KBOTravelStressInput(
                    door_to_door_hours=2,
                    hours_since_previous_game_end=20,
                    hours_since_arrival=10,
                    arrival_local_hour=24,
                )
            )


if __name__ == "__main__":
    unittest.main()
