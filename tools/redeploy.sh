#!/usr/bin/env bash
# Rebuild the local container from the working tree and restart it, so a
# change can be tried in the running app. This is the test loop after every
# change; it publishes nothing.
#
#   tools/redeploy.sh
#
# docker-compose.yml pulls hyprlab/tspro-backup:latest, so the image is built
# under that name first; compose then uses the local build. The next
# `docker compose pull` puts the published image back. The host port comes
# from TSPB_PORT in .env.
set -euo pipefail
cd "$(dirname "$0")/.."

docker build -t hyprlab/tspro-backup:latest .
docker compose up -d
port=$(docker compose port tspro-backup 8000 | cut -d: -f2)
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$port/login"; then
        echo "Up: http://localhost:$port ($(docker compose exec -T tspro-backup python -c 'from app.version import __version__; print(__version__)'))"
        exit 0
    fi
    sleep 1
done
echo "The container did not answer on /login. Logs:" >&2
docker compose logs --tail 40 >&2
exit 1
