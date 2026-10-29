import "./style.css";

const API_BASE_URL = (
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : window.location.origin)
).replace(/\/$/, "");

const app = document.querySelector("#app");

app.innerHTML = `
  <main class="page-shell">
    <div id="loading-overlay" class="loading-overlay" role="status" aria-live="polite" hidden>
      <div class="loading-panel">
        <span class="loading-spinner" aria-hidden="true"></span>
        <span class="loading-label">Getting your availability forecast…</span>
      </div>
    </div>
    <header class="topbar">
      <a class="brand" href="/" aria-label="Vélo availability home">
        <span class="brand-mark" aria-hidden="true">V</span>
        <span>vélo<span class="brand-light">/city</span></span>
      </a>
      <span class="live-label"><span class="live-dot"></span> Availability forecast</span>
    </header>

    <section class="hero" aria-labelledby="page-title">
      <div class="hero-copy">
        <p class="eyebrow">PLAN YOUR RIDE</p>
        <h1 id="page-title">Find your next<br /><span>open seat.</span></h1>
        <p class="hero-description">
          Choose a station and a time to see the predicted bike and free-slot
          availability.
        </p>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="sun"></div>
        <div class="art-circle art-circle-one"></div>
        <div class="art-circle art-circle-two"></div>
        <div class="art-bike">
          <span class="wheel wheel-one"></span>
          <span class="wheel wheel-two"></span>
          <span class="bike-frame frame-a"></span>
          <span class="bike-frame frame-b"></span>
          <span class="bike-frame frame-c"></span>
          <span class="bike-frame frame-d"></span>
          <span class="bike-frame frame-e"></span>
          <span class="bike-frame frame-f"></span>
          <span class="bike-frame frame-g"></span>
        </div>
        <span class="art-label">RENNES · FRANCE</span>
      </div>
    </section>

    <section class="forecast-card" aria-labelledby="forecast-title">
      <div class="card-heading">
        <div>
          <p class="eyebrow">YOUR FORECAST</p>
          <h2 id="forecast-title">Where are you riding?</h2>
        </div>
        <span class="card-icon" aria-hidden="true">↗</span>
      </div>

      <form id="prediction-form">
        <div class="form-grid">
          <label class="field">
            <span class="field-label">Bike station</span>
            <span class="select-wrap">
              <span class="field-symbol" aria-hidden="true">⌖</span>
              <select id="station" name="station_id" required disabled>
                <option value="">Loading stations…</option>
              </select>
              <span class="select-arrow" aria-hidden="true">⌄</span>
            </span>
            <span id="station-capacity" class="field-hint">Loading station list…</span>
          </label>

          <label class="field">
            <span class="field-label">When do you need a bike?</span>
            <span class="input-wrap">
              <span class="field-symbol" aria-hidden="true">◷</span>
              <input id="requested-at" name="requested_at" type="datetime-local" required />
            </span>
            <span class="field-hint">Time is interpreted in your device’s local timezone.</span>
          </label>
        </div>

        <div class="form-footer">
          <p class="privacy-note"><span aria-hidden="true">✦</span> A forecast, not a live count.</p>
          <button id="submit-button" class="submit-button" type="submit" disabled>
            <span class="button-label">Check availability</span>
            <span class="button-arrow" aria-hidden="true">→</span>
          </button>
        </div>
      </form>

      <p id="status-message" class="status-message" role="status" aria-live="polite"></p>
    </section>

    <section id="result" class="result-card" aria-live="polite" hidden></section>

    <section class="day-forecast-card" aria-labelledby="week-forecast-title">
      <div class="card-heading">
        <div>
          <p class="eyebrow">WEEKLY OUTLOOK</p>
          <h2 id="week-forecast-title">Which day is busier?</h2>
          <p id="week-forecast-summary" class="chart-summary">
            Select a station to compare its typical weekday availability.
          </p>
        </div>
        <span class="card-icon" aria-hidden="true">⌁</span>
      </div>
      <p id="week-forecast-message" class="chart-message" role="status" aria-live="polite"></p>
      <div id="week-chart" class="day-chart" hidden></div>
      <p class="chart-note">
        Each point is the average estimated bikes across that day’s 24 hours. Fewer available bikes
        means the station is likely busier. This is a typical weekday pattern, not a live count.
      </p>
    </section>

    <footer class="page-footer">
      <span>Made for better city rides.</span>
      <span>Predictions are estimates and may differ from station availability.</span>
    </footer>
  </main>
`;

const form = document.querySelector("#prediction-form");
const stationSelect = document.querySelector("#station");
const stationCapacity = document.querySelector("#station-capacity");
const requestedAtInput = document.querySelector("#requested-at");
const submitButton = document.querySelector("#submit-button");
const statusMessage = document.querySelector("#status-message");
const result = document.querySelector("#result");
const loadingOverlay = document.querySelector("#loading-overlay");
const loadingLabel = loadingOverlay.querySelector(".loading-label");
const weekForecastSummary = document.querySelector("#week-forecast-summary");
const weekForecastMessage = document.querySelector("#week-forecast-message");
const weekChart = document.querySelector("#week-chart");
let stationsById = new Map();
let weekForecastRequestId = 0;
let loadingTaskCount = 0;

function localDateTimeValue(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function setStatus(message, kind = "") {
  statusMessage.textContent = message;
  statusMessage.className = `status-message ${kind}`.trim();
}

function beginLoading(message) {
  loadingTaskCount += 1;
  loadingLabel.textContent = message;
  loadingOverlay.hidden = false;
  document.body.classList.add("forecast-loading");
}

function endLoading() {
  loadingTaskCount = Math.max(0, loadingTaskCount - 1);
  if (loadingTaskCount === 0) {
    loadingOverlay.hidden = true;
    document.body.classList.remove("forecast-loading");
  }
}

function apiErrorMessage(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg).filter(Boolean).join(" ");
  }
  return fallback;
}

function formatRange(range) {
  return range.min === range.max ? `${range.min}` : `${range.min}–${range.max}`;
}

function renderResult(data) {
  const levelLabels = {
    empty: "0 bikes",
    critical: "1–2 bikes",
    moderate: "3–5 bikes",
    high: "6–15 bikes",
    very_high: "16–19 bikes",
    near_full: "20–25 bikes",
    "26_plus": "26+ bikes",
  };
  const requestedTime = new Date(data.requested_at).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const confidence = Math.round(data.class_probability * 100);

  result.innerHTML = `
    <div class="result-topline">
      <div>
        <p class="eyebrow">PREDICTED AVAILABILITY</p>
        <h2>${escapeHtml(data.station_name)}</h2>
        <p class="result-time">For ${escapeHtml(requestedTime)}</p>
      </div>
      <span class="availability-pill level-${escapeHtml(data.availability_level)}">
        <span class="pill-dot"></span>${escapeHtml(levelLabels[data.availability_level] || data.availability_level)}
      </span>
    </div>
    <div class="availability-stats">
      <article class="stat-tile capacity-tile">
        <span class="stat-icon" aria-hidden="true">⌑</span>
        <p class="stat-label">Total station docks</p>
        <p class="stat-value">${escapeHtml(data.total_slots)}</p>
        <p class="stat-unit">total capacity</p>
      </article>
      <article class="stat-tile bike-tile">
        <span class="stat-icon" aria-hidden="true">↗</span>
        <p class="stat-label">Bikes available</p>
        <p class="stat-value">${escapeHtml(formatRange(data.bikes))}</p>
        <p class="stat-unit">estimated bikes</p>
      </article>
      <article class="stat-tile slot-tile">
        <span class="stat-icon" aria-hidden="true">⌑</span>
        <p class="stat-label">Free slots</p>
        <p class="stat-value">${escapeHtml(formatRange(data.free_slots))}</p>
        <p class="stat-unit">estimated spaces</p>
      </article>
    </div>
    <div class="result-foot">
      <span>Model confidence for this category</span>
      <strong>${confidence}%</strong>
    </div>
    <p class="estimate-note">This is a category-based estimate, not a live station count.</p>
  `;
  result.hidden = false;
  result.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderWeekForecast(data) {
  const width = 840;
  const height = 350;
  const margin = { top: 24, right: 24, bottom: 64, left: 48 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maxBikes = Math.max(data.total_slots, 1);
  const x = (day) => margin.left + (day / 6) * plotWidth;
  const y = (bikes) => margin.top + plotHeight - (bikes / maxBikes) * plotHeight;
  const yTickCount = Math.min(5, maxBikes);
  const yTicks = Array.from({ length: yTickCount + 1 }, (_, index) =>
    Math.round((maxBikes * index) / yTickCount),
  );
  const busiestDay = data.weekly_predictions.reduce((busiest, prediction) =>
    prediction.average_bikes < busiest.average_bikes ? prediction : busiest,
  );
  const line = data.weekly_predictions
    .map((prediction, index) => {
      return `${index === 0 ? "M" : "L"} ${x(prediction.day_of_week).toFixed(1)} ${y(prediction.average_bikes).toFixed(1)}`;
    })
    .join(" ");
  const grid = yTicks
    .map(
      (tick) => `
        <line class="chart-grid" x1="${margin.left}" y1="${y(tick)}" x2="${width - margin.right}" y2="${y(tick)}" />
        <text class="chart-axis-label" x="${margin.left - 10}" y="${y(tick) + 4}" text-anchor="end">${tick}</text>
      `,
    )
    .join("");
  const points = data.weekly_predictions
    .map((prediction) => {
      const estimate = prediction.average_bikes.toFixed(1);
      const label = `${prediction.day_name} · ${estimate} average estimated bikes`;
      const busiestClass =
        prediction.day_of_week === busiestDay.day_of_week ? " is-busiest" : "";
      return `
        <g class="chart-point${busiestClass}" tabindex="0" role="img" aria-label="${escapeHtml(label)}">
          <title>${label}</title>
          <circle class="chart-dot" cx="${x(prediction.day_of_week)}" cy="${y(prediction.average_bikes)}" r="5" />
        </g>
      `;
    })
    .join("");
  const xLabels = data.weekly_predictions
    .map(
      (prediction) => `
        <text class="chart-axis-label" x="${x(prediction.day_of_week)}" y="${height - 34}" text-anchor="middle">${escapeHtml(prediction.day_name.slice(0, 3))}</text>
      `,
    )
    .join("");

  weekForecastSummary.textContent =
    `${data.station_name} · ${data.total_slots} total docks · lowest average: ${busiestDay.day_name} (${busiestDay.average_bikes.toFixed(1)} bikes)`;
  weekChart.innerHTML = `
    <svg class="forecast-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Average estimated bikes by weekday for ${escapeHtml(data.station_name)}">
      ${grid}
      <path class="chart-line" d="${line}" />
      ${points}
      ${xLabels}
      <text class="chart-axis-title" transform="translate(15 ${margin.top + plotHeight / 2}) rotate(-90)" text-anchor="middle">Average available bikes</text>
      <text class="chart-axis-title" x="${margin.left + plotWidth / 2}" y="${height - 7}" text-anchor="middle">Day of week</text>
    </svg>
  `;
  weekChart.hidden = false;
  weekForecastMessage.textContent = "";
}

async function loadWeekForecast() {
  const requestId = ++weekForecastRequestId;
  const stationId = Number(stationSelect.value);
  if (!stationId) {
    weekChart.hidden = true;
    weekForecastSummary.textContent = "Select a station to compare its typical weekday availability.";
    weekForecastMessage.textContent = "";
    weekForecastMessage.classList.remove("error");
    return;
  }

  weekChart.hidden = true;
  weekForecastMessage.textContent = "";
  weekForecastMessage.classList.remove("error");
  beginLoading("Loading the weekly forecast…");

  try {
    const response = await fetch(`${API_BASE_URL}/predict/week`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ station_id: stationId }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(payload.detail, "Could not load the weekly forecast."));
    }
    if (requestId === weekForecastRequestId) {
      renderWeekForecast(payload);
    }
  } catch (error) {
    if (requestId === weekForecastRequestId) {
      weekForecastMessage.textContent = error.message;
      weekForecastMessage.classList.add("error");
    }
  } finally {
    endLoading();
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

async function loadStations() {
  try {
    const response = await fetch(`${API_BASE_URL}/stations`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(payload.detail, "Could not load bike stations."));
    }
    if (!Array.isArray(payload) || payload.length === 0) {
      throw new Error("The API did not return any bike stations.");
    }

    stationsById = new Map(payload.map((station) => [station.station_id, station]));
    stationSelect.replaceChildren(new Option("Select a station", ""));
    for (const station of payload) {
      stationSelect.add(
        new Option(`${station.station_name} · ${station.station_id}`, station.station_id),
      );
    }
    stationSelect.disabled = false;
    submitButton.disabled = false;
    stationCapacity.textContent = `${payload.length} stations available`;
    setStatus("");
  } catch (error) {
    stationSelect.replaceChildren(new Option("Could not load stations", ""));
    stationCapacity.textContent = "The prediction service could not be reached.";
    setStatus(
      `${error.message} Check that the API is running and VITE_API_URL points to it.`,
      "error",
    );
  }
}

stationSelect.addEventListener("change", async () => {
  const stationId = Number(stationSelect.value);
  if (!stationId) {
    stationCapacity.textContent = "Select a station to continue.";
    loadWeekForecast();
    return;
  }

  const station = stationsById.get(stationId);
  if (station) {
    stationCapacity.textContent = `${station.total_slots} total docks`;
    loadWeekForecast();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  result.hidden = true;
  beginLoading("Getting your availability forecast…");
  submitButton.disabled = true;
  submitButton.classList.add("is-loading");
  submitButton.querySelector(".button-label").textContent = "Getting forecast…";
  setStatus("Checking the forecast…");

  try {
    const response = await fetch(`${API_BASE_URL}/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        station_id: Number(stationSelect.value),
        requested_at: new Date(requestedAtInput.value).toISOString(),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(apiErrorMessage(payload.detail, "Could not get a prediction."));
    }

    renderResult(payload);
    setStatus("");
  } catch (error) {
    setStatus(
      `${error.message} Check that the API is running at ${API_BASE_URL}.`,
      "error",
    );
  } finally {
    endLoading();
    submitButton.disabled = false;
    submitButton.classList.remove("is-loading");
    submitButton.querySelector(".button-label").textContent = "Check availability";
  }
});

requestedAtInput.value = localDateTimeValue(new Date());
stationCapacity.textContent = "Select a station to continue.";
loadStations();
