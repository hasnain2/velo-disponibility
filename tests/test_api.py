"""Tests for bike availability prediction API behavior."""

import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from pydantic import ValidationError

from api.main import PredictionRequest, list_stations, predict_availability


class FixedClassifier:
    classes_ = [2]

    def __init__(self) -> None:
        self.features: pd.DataFrame | None = None

    def predict(self, features: pd.DataFrame) -> list[int]:
        self.features = features
        return [2]

    def predict_proba(self, features: pd.DataFrame) -> list[list[float]]:
        return [[1.0]]


class PredictionEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = FixedClassifier()
        self.stations = {
            5505: {
                "name": "Sainte-Anne",
                "lat": 48.114219,
                "lon": -1.680534,
                "slots_total": 24,
            }
        }
        self.predictor_patch = patch(
            "api.main.load_predictor",
            return_value=(self.model, self.stations),
        )
        self.predictor_patch.start()
        self.addCleanup(self.predictor_patch.stop)

    def test_predict_returns_bike_and_free_slot_ranges(self) -> None:
        request = PredictionRequest(
            station_id=5505,
            requested_at=datetime.fromisoformat("2026-10-28T15:00:00+01:00"),
        )

        response = predict_availability(request)

        self.assertEqual(response.station_name, "Sainte-Anne")
        self.assertEqual(response.predicted_bike_bin, 2)
        self.assertEqual(response.availability_level, "moderate")
        self.assertEqual(response.bikes.model_dump(), {"min": 3, "max": 5})
        self.assertEqual(response.free_slots.model_dump(), {"min": 19, "max": 21})
        self.assertEqual(response.class_probability, 1.0)
        self.assertIsNotNone(self.model.features)
        assert self.model.features is not None
        self.assertEqual(self.model.features.iloc[0]["hour"], 15)
        self.assertEqual(self.model.features.iloc[0]["day_of_week"], 2)
        self.assertEqual(self.model.features.iloc[0]["is_weekend"], 0)

    def test_unknown_station_returns_404(self) -> None:
        request = PredictionRequest(
            station_id=9999,
            requested_at=datetime.fromisoformat("2026-10-28T15:00:00+01:00"),
        )

        with self.assertRaises(HTTPException) as error:
            predict_availability(request)

        self.assertEqual(error.exception.status_code, 404)

    def test_timestamp_must_include_timezone(self) -> None:
        with self.assertRaises(ValidationError):
            PredictionRequest(
                station_id=5505,
                requested_at="2026-10-28T15:00:00",
            )

    def test_station_list_returns_selectable_station_metadata(self) -> None:
        stations = list_stations()

        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].station_id, 5505)
        self.assertEqual(stations[0].station_name, "Sainte-Anne")
        self.assertEqual(stations[0].total_slots, 24)


if __name__ == "__main__":
    unittest.main()