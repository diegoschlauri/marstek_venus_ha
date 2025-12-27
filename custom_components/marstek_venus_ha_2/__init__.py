"""The Marstek Venus HA integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import MarstekCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek Venus HA from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = MarstekCoordinator(hass, entry)
    await coordinator.async_start_listening()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "trigger_update"):
        async def _handle_trigger_update(call):
            entry_id = call.data.get("entry_id")
            if entry_id:
                c: MarstekCoordinator | None = hass.data.get(DOMAIN, {}).get(entry_id)
                if c is not None:
                    await c.async_request_update(reason="service")
                return
            for value in hass.data.get(DOMAIN, {}).values():
                if isinstance(value, MarstekCoordinator):
                    await value.async_request_update(reason="service")

        hass.services.async_register(DOMAIN, "trigger_update", _handle_trigger_update)

    # Reload entry when options are updated
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    domain_data: dict = hass.data.get(DOMAIN, {})
    coordinator: MarstekCoordinator | None = domain_data.pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_stop_listening()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)
