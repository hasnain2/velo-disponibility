# Velo availability

## Project layout

- `data/raw/` contains collected readings; `data/clean.parquet` is the prepared dataset.
- `notebooks/` contains exploratory and data-cleaning work.
- `src/` contains reusable feature and model code.
- `models/` is reserved for saved model artifacts.
- `api/` contains the service entry point, and `tests/` contains automated tests.
- `frontend/` contains the Vite web interface for requesting and viewing forecasts.

## Evaluate a model

Run all cells in `notebooks/data_cleaning.ipynb` first. Its final cell saves the
cleaned data and the exact stratified train/test split as
`data/clean.parquet`, `data/train.parquet`, and `data/test.parquet`.

Then open `notebooks/model_evaluation.ipynb` to compare logistic regression,
decision tree, and random forest accuracy and macro F1 using those saved split
files.

To run the same three-model comparison from the command line, from the project
root run:

```bash
python -m src.train
```

The script loads `data/train.parquet` and `data/test.parquet` and compares
logistic regression, a decision tree, and a random forest. It reports training
and test accuracy, test error rate, the generalization gap, and test macro F1.
You can specify different saved split files:

```bash
python -m src.train --train-data path/to/train.parquet --test-data path/to/test.parquet
```

Training also writes the selected random-forest model to
`models/availability_classifier.joblib`. Start the prediction API after training:

```bash
uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.
`POST /predict` accepts a station ID and timezone-aware prediction timestamp:

```json
{
  "station_id": 5505,
  "requested_at": "2026-10-28T15:00:00+01:00"
}
```

The response predicts an availability band and bike/free-slot count ranges,
not exact counts. The model predicts `bike_bin` (0 bikes, 1-2, 3-5, or 6+);
free-slot ranges are derived from the station capacity. The station metadata is
read from `data/clean.parquet`.

## Web frontend

The Vite frontend is in `frontend/`. It loads station choices from `GET /stations`,
lets the user select a station and local date/time, then sends a request to
`POST /predict` and displays the estimated bike and free-slot ranges.

Install Node.js 20 or newer (which includes npm) before starting the frontend.

Start the API in one terminal:

```bash
./.venv/bin/uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, install the frontend dependencies and start Vite:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). The page
uses `http://127.0.0.1:8000` as its default API URL. If the API uses a different
address or port, create `frontend/.env.local` from `frontend/.env.example` and
set `VITE_API_URL` to the API base URL, for example
`VITE_API_URL=http://127.0.0.1:18765`; restart Vite after changing it. The API
allows the default Vite development origins through CORS.