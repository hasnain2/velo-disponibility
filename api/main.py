"""FastAPI service for bike-availability predictions."""

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sklearn.ensemble import RandomForestClassifier
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from src.features import (
    FEATURE_COLUMNS,
    LOCAL_TIMEZONE,
    TARGET_COLUMN,
    build_feature_row,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT_DIR / "models" / "availability_classifier.joblib"
STATION_DATA_PATH = ROOT_DIR / "data" / "clean.parquet"
FRONTEND_DIST_PATH = ROOT_DIR / "frontend" / "dist"
APP_TITLE = "Velo availability API"

AVAILABILITY_BANDS: dict[int, tuple[str, int, int | None]] = {
    0: ("empty", 0, 0),
    1: ("critical", 1, 2),
    2: ("moderate", 3, 5),
    3: ("high", 6, 15),
    4: ("very_high", 16, 19),
    5: ("near_full", 20, 25),
    6: ("26_plus", 26, None),
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
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST_PATH / "assets", check_dir=False),
    name="frontend-assets",
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


class DayForecastRequest(BaseModel):
    station_id: int = Field(gt=0, description="Station identifier from the bike network")
    forecast_date: date = Field(description="Calendar date in the station's local timezone")


class WeekForecastRequest(BaseModel):
    station_id: int = Field(gt=0, description="Station identifier from the bike network")


class CountRange(BaseModel):
    min: int
    max: int


class PredictionResponse(BaseModel):
    station_id: int
    station_name: str
    total_slots: int
    requested_at: datetime
    prediction_type: Literal["availability_band"]
    predicted_bike_bin: int
    availability_level: Literal[
        "empty",
        "critical",
        "moderate",
        "high",
        "very_high",
        "near_full",
        "26_plus",
    ]
    bikes: CountRange
    free_slots: CountRange
    class_probability: float = Field(ge=0, le=1)


class StationResponse(BaseModel):
    station_id: int
    station_name: str
    total_slots: int


class HourlyForecast(BaseModel):
    hour: int = Field(ge=0, le=23)
    predicted_bike_bin: int
    availability_level: Literal[
        "empty",
        "critical",
        "moderate",
        "high",
        "very_high",
        "near_full",
        "26_plus",
    ]
    bikes: CountRange
    free_slots: CountRange
    class_probability: float = Field(ge=0, le=1)


class DayForecastResponse(BaseModel):
    station_id: int
    station_name: str
    total_slots: int
    forecast_date: date
    hourly_predictions: list[HourlyForecast]


class WeekdayForecast(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    day_name: Literal[
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    average_bikes: float = Field(ge=0)


class WeekForecastResponse(BaseModel):
    station_id: int
    station_name: str
    total_slots: int
    weekly_predictions: list[WeekdayForecast]


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
        total_slots=capacity,
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


@app.post("/predict/day", response_model=DayForecastResponse)
def predict_day(request: DayForecastRequest) -> DayForecastResponse:
    """Predict bike and free-slot ranges for every local hour of a day."""
    model, stations = load_predictor()
    station = stations.get(request.station_id)
    if station is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown station_id: {request.station_id}",
        )

    timestamps = [
        datetime.combine(request.forecast_date, time(hour), tzinfo=LOCAL_TIMEZONE)
        for hour in range(24)
    ]
    features = pd.concat(
        [
            build_feature_row(
                station_id=request.station_id,
                latitude=float(station["lat"]),
                longitude=float(station["lon"]),
                total_slots=int(station["slots_total"]),
                requested_at=requested_at,
            )
            for requested_at in timestamps
        ],
        ignore_index=True,
    )
    predicted_bins = model.predict(features)
    probabilities = model.predict_proba(features)
    capacity = int(station["slots_total"])
    hourly_predictions = []

    for hour, predicted_bin, class_probabilities in zip(
        range(24), predicted_bins, probabilities, strict=True
    ):
        predicted_bin = int(predicted_bin)
        try:
            level, bike_minimum, bike_maximum = AVAILABILITY_BANDS[predicted_bin]
        except KeyError as error:
            raise RuntimeError(
                f"Model returned unknown bike_bin class: {predicted_bin}"
            ) from error

        bike_minimum = min(bike_minimum, capacity)
        bike_maximum = capacity if bike_maximum is None else min(bike_maximum, capacity)
        probability_by_class = {
            int(class_label): float(probability)
            for class_label, probability in zip(
                model.classes_, class_probabilities, strict=True
            )
        }
        hourly_predictions.append(
            HourlyForecast(
                hour=hour,
                predicted_bike_bin=predicted_bin,
                availability_level=level,
                bikes=CountRange(min=bike_minimum, max=bike_maximum),
                free_slots=CountRange(
                    min=capacity - bike_maximum,
                    max=capacity - bike_minimum,
                ),
                class_probability=probability_by_class[predicted_bin],
            )
        )

    return DayForecastResponse(
        station_id=request.station_id,
        station_name=str(station["name"]),
        total_slots=capacity,
        forecast_date=request.forecast_date,
        hourly_predictions=hourly_predictions,
    )


@app.post("/predict/week", response_model=WeekForecastResponse)
def predict_week(request: WeekForecastRequest) -> WeekForecastResponse:
    """Estimate average bike availability for each weekday at a station."""
    model, stations = load_predictor()
    station = stations.get(request.station_id)
    if station is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown station_id: {request.station_id}",
        )

    today = datetime.now(LOCAL_TIMEZONE).date()
    monday = today - timedelta(days=today.weekday())
    timestamps = [
        datetime.combine(
            monday + timedelta(days=day_of_week),
            time(hour),
            tzinfo=LOCAL_TIMEZONE,
        )
        for day_of_week in range(7)
        for hour in range(24)
    ]
    features = pd.concat(
        [
            build_feature_row(
                station_id=request.station_id,
                latitude=float(station["lat"]),
                longitude=float(station["lon"]),
                total_slots=int(station["slots_total"]),
                requested_at=requested_at,
            )
            for requested_at in timestamps
        ],
        ignore_index=True,
    )
    probabilities = model.predict_proba(features)
    capacity = int(station["slots_total"])
    expected_bikes_by_class = []
    for class_label in model.classes_:
        try:
            _, bike_minimum, bike_maximum = AVAILABILITY_BANDS[int(class_label)]
        except KeyError as error:
            raise RuntimeError(
                f"Model returned unknown bike_bin class: {class_label}"
            ) from error
        bike_minimum = min(bike_minimum, capacity)
        bike_maximum = capacity if bike_maximum is None else min(bike_maximum, capacity)
        expected_bikes_by_class.append((bike_minimum + bike_maximum) / 2)

    expected_bikes_by_hour = [
        sum(
            float(probability) * expected_bikes
            for probability, expected_bikes in zip(
                class_probabilities, expected_bikes_by_class, strict=True
            )
        )
        for class_probabilities in probabilities
    ]
    weekdays = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    weekly_predictions = [
        WeekdayForecast(
            day_of_week=day_of_week,
            day_name=day_name,
            average_bikes=sum(
                expected_bikes_by_hour[day_of_week * 24 : (day_of_week + 1) * 24]
            )
            / 24,
        )
        for day_of_week, day_name in enumerate(weekdays)
    ]

    return WeekForecastResponse(
        station_id=request.station_id,
        station_name=str(station["name"]),
        total_slots=capacity,
        weekly_predictions=weekly_predictions,
    )


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    """Serve the compiled frontend in the single-container deployment."""
    index_path = FRONTEND_DIST_PATH / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Frontend has not been built.")
    return FileResponse(index_path)