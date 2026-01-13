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

- to test the config flow you need to create a few template sensors for pv power, battery soc, etc. and add them to the config. the given configuration.yaml should provide some initial setup to make the setup flow work with battery prefix: "bat1". you can directly start here http://localhost:8123/config/integrations/integration/marstek_venus_ha