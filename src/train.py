"""Compare bike-availability classifiers on saved train/test data."""

import argparse
from pathlib import Path

import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from src.features import FEATURE_COLUMNS, TARGET_COLUMN


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TRAIN_PATH = ROOT_DIR / "data" / "train.parquet"
DEFAULT_TEST_PATH = ROOT_DIR / "data" / "test.parquet"
DEFAULT_MODEL_PATH = ROOT_DIR / "models" / "availability_classifier.joblib"


def load_split_data(train_path: Path, test_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load saved train/test splits and validate their model columns."""
    required_columns = [*FEATURE_COLUMNS, TARGET_COLUMN]
    splits: list[pd.DataFrame] = []

    for split_name, path in (("train", train_path), ("test", test_path)):
        data = pd.read_parquet(path)
        missing_columns = sorted(set(required_columns) - set(data.columns))
        if missing_columns:
            raise ValueError(
                f"{split_name} data is missing required columns: {', '.join(missing_columns)}"
            )
        if data.empty:
            raise ValueError(f"{split_name} data is empty.")
        if data[required_columns].isna().any().any():
            raise ValueError(f"{split_name} data contains missing model features or targets.")
        splits.append(data)

    return splits[0], splits[1]


def evaluate_models(
    train_data: pd.DataFrame,
    test_data: pd.DataFrame,
    model_path: Path,
) -> None:
    """Fit classifiers and compare training and held-out test performance."""
    x_train = train_data[FEATURE_COLUMNS]
    y_train = train_data[TARGET_COLUMN]
    x_test = test_data[FEATURE_COLUMNS]
    y_test = test_data[TARGET_COLUMN]

    models = {
        "Logistic regression": make_pipeline(
            StandardScaler(),
            LogisticRegression(
                class_weight="balanced",
                max_iter=1000,
                random_state=42,
            ),
        ),
        "Decision tree": DecisionTreeClassifier(
            class_weight="balanced",
            random_state=42,
        ),
        "Random forest": RandomForestClassifier(
            n_estimators=300,
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        ),
    }

    majority_class = y_train.mode().iloc[0]
    train_predictions = {
        "Majority-class baseline": pd.Series(majority_class, index=y_train.index)
    }
    test_predictions = {
        "Majority-class baseline": pd.Series(majority_class, index=y_test.index)
    }

    for name, model in models.items():
        model.fit(x_train, y_train)
        train_predictions[name] = model.predict(x_train)
        test_predictions[name] = model.predict(x_test)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "format_version": 1,
            "model": models["Random forest"],
            "feature_columns": FEATURE_COLUMNS,
            "target_column": TARGET_COLUMN,
        },
        model_path,
    )

    comparison = pd.DataFrame(
        {
            "train_accuracy": {
                name: accuracy_score(y_train, prediction)
                for name, prediction in train_predictions.items()
            },
            "test_accuracy": {
                name: accuracy_score(y_test, prediction)
                for name, prediction in test_predictions.items()
            },
            "test_error_rate": {
                name: 1 - accuracy_score(y_test, prediction)
                for name, prediction in test_predictions.items()
            },
            "generalization_gap": {
                name: accuracy_score(y_train, train_predictions[name])
                - accuracy_score(y_test, prediction)
                for name, prediction in test_predictions.items()
            },
            "macro_f1": {
                name: f1_score(y_test, prediction, average="macro", zero_division=0)
                for name, prediction in test_predictions.items()
            },
        }
    ).sort_values("test_accuracy", ascending=False)

    print(f"Training rows: {len(train_data):,}")
    print(f"Test rows: {len(test_data):,}")
    print(f"Saved random forest model: {model_path}")
    print("\nModel comparison (generalization gap = train accuracy - test accuracy)")
    print(comparison.round(3).to_string())

    forest_predictions = test_predictions["Random forest"]
    class_labels = sorted(set(y_train.unique()) | set(y_test.unique()))
    print("\nRandom forest classification report")
    print(
        classification_report(
            y_test,
            forest_predictions,
            labels=class_labels,
            target_names=[str(label) for label in class_labels],
            zero_division=0,
        )
    )
    print("Random forest confusion matrix (rows: actual, columns: predicted)")
    print(confusion_matrix(y_test, forest_predictions, labels=class_labels))

    feature_importances = pd.Series(
        models["Random forest"].feature_importances_,
        index=FEATURE_COLUMNS,
        name="importance",
    ).sort_values(ascending=False)
    print("\nRandom forest feature importance")
    print(feature_importances.to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--train-data",
        type=Path,
        default=DEFAULT_TRAIN_PATH,
        help=f"Saved training Parquet file (default: {DEFAULT_TRAIN_PATH})",
    )
    parser.add_argument(
        "--test-data",
        type=Path,
        default=DEFAULT_TEST_PATH,
        help=f"Saved test Parquet file (default: {DEFAULT_TEST_PATH})",
    )
    parser.add_argument(
        "--model-output",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=f"Path for the trained random forest (default: {DEFAULT_MODEL_PATH})",
    )
    args = parser.parse_args()

    train_data, test_data = load_split_data(args.train_data, args.test_data)
    evaluate_models(train_data, test_data, args.model_output)


if __name__ == "__main__":
    main()
