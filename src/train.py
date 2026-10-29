"""Train and save the bike-availability random forest."""

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from src.features import FEATURE_COLUMNS, TARGET_COLUMN


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TRAIN_PATH = ROOT_DIR / "data" / "train.parquet"
DEFAULT_MODEL_PATH = ROOT_DIR / "models" / "availability_classifier.joblib"


def load_training_data(train_path: Path) -> pd.DataFrame:
    """Load the training data and validate the model columns."""
    required_columns = [*FEATURE_COLUMNS, TARGET_COLUMN]
    data = pd.read_parquet(train_path)
    missing_columns = sorted(set(required_columns) - set(data.columns))
    if missing_columns:
        raise ValueError(
            f"Training data is missing required columns: {', '.join(missing_columns)}"
        )
    if data.empty:
        raise ValueError("Training data is empty.")
    if data[required_columns].isna().any().any():
        raise ValueError("Training data contains missing model features or targets.")
    return data


def train_model(train_data: pd.DataFrame, model_path: Path) -> None:
    """Fit the random forest and save it for the prediction API."""
    model = RandomForestClassifier(
        n_estimators=300,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(train_data[FEATURE_COLUMNS], train_data[TARGET_COLUMN])

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "format_version": 1,
            "model": model,
            "feature_columns": FEATURE_COLUMNS,
            "target_column": TARGET_COLUMN,
        },
        model_path,
    )
    print(f"Trained Random Forest using {len(train_data):,} rows.")
    print(f"Saved model: {model_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--train-data",
        type=Path,
        default=DEFAULT_TRAIN_PATH,
        help=f"Saved training Parquet file (default: {DEFAULT_TRAIN_PATH})",
    )
    parser.add_argument(
        "--model-output",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=f"Path for the trained random forest (default: {DEFAULT_MODEL_PATH})",
    )
    args = parser.parse_args()

    train_data = load_training_data(args.train_data)
    train_model(train_data, args.model_output)


if __name__ == "__main__":
    main()
