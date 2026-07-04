# TS Pro Backup v1.3.1

**Maintenance release.** The project has moved to a new home under the
**hyprlab** account on both GitHub and Docker Hub. There are no code or
behaviour changes — this release only updates the repository and image
coordinates.

## What changed

- Source now lives at
  [`hyprlab/tspro-backup`](https://github.com/hyprlab/tspro-backup).
- The published image is now
  [`hyprlab/tspro-backup`](https://hub.docker.com/r/hyprlab/tspro-backup).

## How to upgrade

Point your `docker-compose.yml` at the new image and pull:

```yaml
    image: hyprlab/tspro-backup:latest
```

```bash
docker compose pull && docker compose up -d
```

## License

[AGPL-3.0-or-later](LICENSE).
