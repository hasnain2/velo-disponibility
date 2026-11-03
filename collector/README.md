# Bike collector

    docker compose up -d --build     # start (restarts automatically after reboot)
    docker compose logs -f           # watch it
    docker compose ps                # STATUS shows healthy / unhealthy

Data: ./data/bikes.sqlite, table `readings` (one row per station per source refresh).

    sqlite3 data/bikes.sqlite "select count(*), min(lastupdate), max(lastupdate) from readings;"

Make sure Docker starts at boot: `sudo systemctl enable docker`
