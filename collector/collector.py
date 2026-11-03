"""Poll the Rennes Métropole Le Vélo STAR real-time API and append to SQLite.

Runs forever: one poll every INTERVAL_MIN minutes (default 20).
Everything is stored locally in DB_PATH. Standard library only.
"""
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = os.environ.get(
    "API_URL",
    "https://data.rennesmetropole.fr/api/explore/v2.1/catalog/datasets/"
    "etat-des-stations-le-velo-star-en-temps-reel/records",
)
DB_PATH = os.environ.get("DB_PATH", "/data/bikes.sqlite")
INTERVAL_MIN = int(os.environ.get("INTERVAL_MIN", "20"))
EXPECTED_STATIONS = int(os.environ.get("EXPECTED_STATIONS", "57"))
HEARTBEAT = Path(os.environ.get("HEARTBEAT_PATH", "/data/last_ok"))
PAGE = 100  # the API caps `limit` at 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    fetched_at   TEXT NOT NULL,   -- our clock (UTC)
    lastupdate   TEXT NOT NULL,   -- source refresh time
    idstation    TEXT NOT NULL,
    nom          TEXT,
    lon          REAL,
    lat          REAL,
    etat         TEXT,
    slots_total  INTEGER,         -- nombreemplacementsactuels
    slots_free   INTEGER,         -- nombreemplacementsdisponibles
    bikes        INTEGER,         -- nombrevelosdisponibles
    consistent   INTEGER,         -- 1 if slots_free + bikes == slots_total
    PRIMARY KEY (idstation, lastupdate)
);
CREATE INDEX IF NOT EXISTS idx_readings_time ON readings (lastupdate);
"""

log = logging.getLogger("collector")


def fetch_all():
    """Fetch every station, paginating until total_count is reached."""
    rows, offset, total = [], 0, None
    while total is None or offset < total:
        qs = urllib.parse.urlencode({"limit": PAGE, "offset": offset})
        req = urllib.request.Request(
            f"{API_URL}?{qs}", headers={"User-Agent": "bike-forecast-student-project"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"HTTP {e.code} for {req.full_url} -> {body}") from None
        total = payload["total_count"]
        batch = payload["results"]
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
    return rows, total


def parse(rec, fetched_at):
    coords = rec.get("coordonnees") or {}
    etat = rec.get("etat")
    if isinstance(etat, list):
        etat = ",".join(etat)
    total = rec.get("nombreemplacementsactuels")
    free = rec.get("nombreemplacementsdisponibles")
    bikes = rec.get("nombrevelosdisponibles")
    consistent = None
    if None not in (total, free, bikes):
        consistent = int(free + bikes == total)
    return (
        fetched_at, rec["lastupdate"], str(rec["idstation"]), rec.get("nom"),
        coords.get("lon"), coords.get("lat"), etat, total, free, bikes, consistent,
    )


def poll(conn):
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    recs, total = fetch_all()
    if len(recs) != EXPECTED_STATIONS or total != EXPECTED_STATIONS:
        log.warning("expected %d stations, got %d (total_count=%s)",
                    EXPECTED_STATIONS, len(recs), total)
    rows = [parse(r, fetched_at) for r in recs]
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    inserted = conn.total_changes - before
    bad = sum(1 for r in rows if r[-1] == 0)
    if inserted == 0:
        log.warning("0 new rows: source lastupdate did not advance (stale feed?)")
    if bad:
        log.warning("%d stations where slots_free + bikes != slots_total", bad)
    log.info("fetched=%d inserted=%d", len(rows), inserted)
    HEARTBEAT.write_text(fetched_at)


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    interval = INTERVAL_MIN * 60
    while True:
        try:
            poll(conn)
        except Exception:
            log.exception("poll failed, will retry next cycle")
        # wait for the next boundary on the wall clock, in short steps, so a
        # suspend/resume of the PC doesn't leave the loop sleeping for long
        next_due = (int(time.time()) // interval + 1) * interval
        while time.time() < next_due:
            time.sleep(min(30, max(1, next_due - time.time())))


if __name__ == "__main__":
    main()