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

To train the random forest for the prediction API from the command line, from
the project root run:

```bash
python -m src.train
```

The script loads `data/train.parquet` and saves the trained model to
`models/availability_classifier.joblib`. Model comparisons belong in the
evaluation notebook. You can specify a different training file or model output:

```bash
python -m src.train --train-data path/to/train.parquet --model-output path/to/model.joblib
```

Start the prediction API after training:

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
not exact counts. The model predicts `bike_bin` (0, 1-2, 3-5, 6-15, 16-19,
20-25, or 26+ bikes); free-slot ranges are derived from the station capacity.
The response includes the station's total dock capacity; estimated bikes and
free slots together add up to that capacity. The station metadata is read from
`data/clean.parquet`.

## Container deployment

The Docker image builds the Vite frontend and serves it from the FastAPI
application, together with the trained model and station metadata. To build
and run it locally from the project root:

```bash
docker build -t velo-disponibility .
docker run --rm -p 8000:8000 velo-disponibility
```

Open `http://localhost:8000`. The API documentation remains available at
`http://localhost:8000/docs`.

To deploy the container on Render, push this repository to GitHub, create a
new Blueprint in the Render dashboard, and connect the repository. Render
will read `render.yaml` and build the Dockerfile. Its free web services sleep
after inactivity and may take about a minute to wake; Render describes this
plan as suitable for hobby and testing projects rather than production.
The model and station data are included in the image, so they do not depend on
Render's temporary filesystem.

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
uses `http://127.0.0.1:8000` as its default API URL during development. For
container deployments, it uses the same origin as the frontend automatically.
If the development API uses a different address or port, create
`frontend/.env.local` from `frontend/.env.example`, set `VITE_API_URL` to the
API base URL, and restart Vite. The API allows the default Vite development
origins through CORS.