"""FastAPI service for bike-availability predictions."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from sklearn.ensemble import RandomForestClassifier
from starlette.middleware.cors import CORSMiddleware

from src.features import FEATURE_COLUMNS, TARGET_COLUMN, build_feature_row


ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT_DIR / "models" / "availability_classifier.joblib"
STATION_DATA_PATH = ROOT_DIR / "data" / "clean.parquet"
APP_TITLE = "Velo availability API"

AVAILABILITY_BANDS: dict[int, tuple[str, int, int | None]] = {
    0: ("empty", 0, 0),
    1: ("critical", 1, 2),
    2: ("moderate", 3, 5),
    3: ("high", 6, None),
}

app = FastAPI(title=APP_TITLE, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class PredictionRequest(BaseModel):
    station_id: int = Field(gt=0, description="Station identifier from the bike network")
    requested_at: datetime = Field(
        description="Timezone-aware timestamp to predict availability for"
    )

    @field_validator("requested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include a timezone offset.")
        return value


class CountRange(BaseModel):
    min: int
    max: int


class PredictionResponse(BaseModel):
    station_id: int
    station_name: str
    requested_at: datetime
    prediction_type: Literal["availability_band"]
    predicted_bike_bin: int
    availability_level: Literal["empty", "critical", "moderate", "high"]
    bikes: CountRange
    free_slots: CountRange
    class_probability: float = Field(ge=0, le=1)


class StationResponse(BaseModel):
    station_id: int
    station_name: str
    total_slots: int


@lru_cache(maxsize=1)
def load_predictor() -> tuple[RandomForestClassifier, dict[int, dict[str, object]]]:
    """Load the trained model and station metadata once per application process."""
    if not MODEL_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="Model is not trained. Run `python -m src.train` first.",
        )
    if not STATION_DATA_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="Cleaned station data is missing. Run the data-cleaning notebook first.",
        )

    artifact = joblib.load(MODEL_PATH)
    if (
        not isinstance(artifact, dict)
        or artifact.get("format_version") != 1
        or artifact.get("feature_columns") != FEATURE_COLUMNS
        or artifact.get("target_column") != TARGET_COLUMN
        or "model" not in artifact
    ):
        raise RuntimeError(f"Unsupported or invalid model artifact: {MODEL_PATH}")

    stations = pd.read_parquet(STATION_DATA_PATH)
    required_station_columns = {
        "idstation",
        "nom",
        "lat",
        "lon",
        "slots_total",
        "lastupdate",
    }
    missing_columns = sorted(required_station_columns - set(stations.columns))
    if missing_columns:
        raise RuntimeError(
            f"Cleaned station data is missing columns: {', '.join(missing_columns)}"
        )

    latest_stations = (
        stations.sort_values("lastupdate")
        .drop_duplicates("idstation", keep="last")
        .set_index("idstation")
    )
    station_lookup = {
        int(station_id): {
            "name": str(row["nom"]),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "slots_total": int(row["slots_total"]),
        }
        for station_id, row in latest_stations.iterrows()
    }
    return artifact["model"], station_lookup


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the API process is responsive."""
    return {"status": "ok"}


@app.get("/stations", response_model=list[StationResponse])
def list_stations() -> list[StationResponse]:
    """List stations that can be used for a prediction request."""
    _, stations = load_predictor()
    return [
        StationResponse(
            station_id=station_id,
            station_name=str(station["name"]),
            total_slots=int(station["slots_total"]),
        )
        for station_id, station in sorted(
            stations.items(),
            key=lambda item: str(item[1]["name"]).casefold(),
        )
    ]


@app.post("/predict", response_model=PredictionResponse)
def predict_availability(request: PredictionRequest) -> PredictionResponse:
    """Predict an availability band for a station and requested timestamp."""
    model, stations = load_predictor()
    station = stations.get(request.station_id)
    if station is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown station_id: {request.station_id}",
        )

    features = build_feature_row(
        station_id=request.station_id,
        latitude=float(station["lat"]),
        longitude=float(station["lon"]),
        total_slots=int(station["slots_total"]),
        requested_at=request.requested_at,
    )
    predicted_bin = int(model.predict(features)[0])
    try:
        level, bike_minimum, bike_maximum = AVAILABILITY_BANDS[predicted_bin]
    except KeyError as error:
        raise RuntimeError(f"Model returned unknown bike_bin class: {predicted_bin}") from error

    capacity = int(station["slots_total"])
    bike_minimum = min(bike_minimum, capacity)
    bike_maximum = capacity if bike_maximum is None else min(bike_maximum, capacity)
    probabilities = model.predict_proba(features)[0]
    probability_by_class = {
        int(class_label): float(probability)
        for class_label, probability in zip(model.classes_, probabilities, strict=True)
    }

    return PredictionResponse(
        station_id=request.station_id,
        station_name=str(station["name"]),
        requested_at=request.requested_at,
        prediction_type="availability_band",
        predicted_bike_bin=predicted_bin,
        availability_level=level,
        bikes=CountRange(min=bike_minimum, max=bike_maximum),
        free_slots=CountRange(
            min=capacity - bike_maximum,
            max=capacity - bike_minimum,
        ),
        class_probability=probability_by_class[predicted_bin],
    )