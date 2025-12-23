# Dev Instance

This folder contains a small, self-contained Home Assistant Docker Compose setup for local development/testing of this integration.

## What it does

- Runs Home Assistant in Docker (see `docker-compose.yaml`).
- Uses `./config` as the HA configuration volume.
- Allows you to sync the integration from `../custom_components/` into `./config/custom_components/`.

## Usage

From the repository root:

```bash
./dev-instance/start.sh
```

Then open Home Assistant:

- `http://localhost:8123`

## Notes

- The HA config folder (`dev-instance/config`) is not meant to be committed (see `.gitignore`).
- If you want a clean HA state, stop the container and remove/reset the contents of `dev-instance/config`.
