"""The Marstek Venus HA integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import MarstekCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek Venus HA from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = MarstekCoordinator(hass, entry)
    await coordinator.async_start_listening()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Reload entry when options are updated
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    domain_data: dict = hass.data.get(DOMAIN, {})
    coordinator: MarstekCoordinator | None = domain_data.pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_stop_listening()
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are changed."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
