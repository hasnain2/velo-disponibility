"""Tests for bike availability prediction API behavior."""

import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from pydantic import ValidationError

from api.main import (
    DayForecastRequest,
    PredictionRequest,
    WeekForecastRequest,
    list_stations,
    predict_availability,
    predict_day,
    predict_week,
)


class FixedClassifier:
    def __init__(self, predicted_class: int = 2) -> None:
        self.classes_ = [predicted_class]
        self.predicted_class = predicted_class
        self.features: pd.DataFrame | None = None

    def predict(self, features: pd.DataFrame) -> list[int]:
        self.features = features
        return [self.predicted_class for _ in range(len(features))]

    def predict_proba(self, features: pd.DataFrame) -> list[list[float]]:
        self.features = features
        if len(self.classes_) == 1:
            return [[1.0] for _ in range(len(features))]

        probabilities = []
        for day_of_week in features["day_of_week"]:
            class_three_probability = (int(day_of_week) + 1) / 7
            row = [0.0] * len(self.classes_)
            row[3] = class_three_probability
            row[4] = 1 - class_three_probability
            probabilities.append(row)
        return probabilities


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
        self.assertEqual(response.total_slots, 24)
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

    def test_prediction_bins_return_bike_and_free_slot_ranges(self) -> None:
        expected_ranges = {
            0: ("empty", {"min": 0, "max": 0}, {"min": 24, "max": 24}),
            1: ("critical", {"min": 1, "max": 2}, {"min": 22, "max": 23}),
            2: ("moderate", {"min": 3, "max": 5}, {"min": 19, "max": 21}),
            3: ("high", {"min": 6, "max": 15}, {"min": 9, "max": 18}),
            4: ("very_high", {"min": 16, "max": 19}, {"min": 5, "max": 8}),
            5: ("near_full", {"min": 20, "max": 24}, {"min": 0, "max": 4}),
            6: ("26_plus", {"min": 24, "max": 24}, {"min": 0, "max": 0}),
        }
        request = PredictionRequest(
            station_id=5505,
            requested_at=datetime.fromisoformat("2026-10-28T15:00:00+01:00"),
        )

        for predicted_bin, (level, bikes, free_slots) in expected_ranges.items():
            with self.subTest(predicted_bin=predicted_bin):
                self.model.predicted_class = predicted_bin
                self.model.classes_ = [predicted_bin]
                response = predict_availability(request)

                self.assertEqual(response.availability_level, level)
                self.assertEqual(response.total_slots, 24)
                self.assertEqual(response.bikes.model_dump(), bikes)
                self.assertEqual(response.free_slots.model_dump(), free_slots)
                self.assertEqual(response.bikes.min + response.free_slots.max, 24)
                self.assertEqual(response.bikes.max + response.free_slots.min, 24)

    def test_day_forecast_returns_all_24_hours(self) -> None:
        response = predict_day(
            DayForecastRequest(
                station_id=5505,
                forecast_date="2026-10-28",
            )
        )

        self.assertEqual(response.forecast_date.isoformat(), "2026-10-28")
        self.assertEqual(response.total_slots, 24)
        self.assertEqual(len(response.hourly_predictions), 24)
        self.assertEqual(
            [prediction.hour for prediction in response.hourly_predictions],
            list(range(24)),
        )
        for prediction in response.hourly_predictions:
            self.assertEqual(prediction.bikes.model_dump(), {"min": 3, "max": 5})
            self.assertEqual(prediction.free_slots.model_dump(), {"min": 19, "max": 21})

    def test_week_forecast_returns_average_availability_for_each_weekday(self) -> None:
        self.model.classes_ = list(range(7))
        response = predict_week(WeekForecastRequest(station_id=5505))

        self.assertEqual(response.station_name, "Sainte-Anne")
        self.assertEqual(response.total_slots, 24)
        assert self.model.features is not None
        self.assertEqual(len(self.model.features), 7 * 24)
        self.assertEqual(
            self.model.features.groupby("day_of_week").size().tolist(),
            [24] * 7,
        )
        self.assertEqual(
            [prediction.day_name for prediction in response.weekly_predictions],
            [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ],
        )
        self.assertAlmostEqual(response.weekly_predictions[0].average_bikes, 16.5)
        self.assertAlmostEqual(response.weekly_predictions[-1].average_bikes, 10.5)

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