"""Shared model feature definitions and request-time feature engineering."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


FEATURE_COLUMNS = [
    "idstation",
    "lat",
    "lon",
    "slots_total",
    "hour",
    "day_of_week",
    "is_weekend",
]
TARGET_COLUMN = "bike_bin"
LOCAL_TIMEZONE = ZoneInfo("Europe/Paris")


def build_feature_row(
    station_id: int,
    latitude: float,
    longitude: float,
    total_slots: int,
    requested_at: datetime,
) -> pd.DataFrame:
    """Create one classifier input row using the cleaning notebook's time zone."""
    local_time = requested_at.astimezone(LOCAL_TIMEZONE)
    day_of_week = local_time.weekday()
    return pd.DataFrame(
        [
            {
                "idstation": station_id,
                "lat": latitude,
                "lon": longitude,
                "slots_total": total_slots,
                "hour": local_time.hour,
                "day_of_week": day_of_week,
                "is_weekend": int(day_of_week >= 5),
            }
        ],
        columns=FEATURE_COLUMNS,
    )