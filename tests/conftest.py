import sys
import types
from pathlib import Path


def _install_homeassistant_stubs() -> None:
    """Install minimal Home Assistant stubs so unit tests can import the integration.

    These tests focus on pure calculation logic and should not require a full HA runtime.
    """

    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    config_entries = types.ModuleType("homeassistant.config_entries")
    helpers = types.ModuleType("homeassistant.helpers")
    helpers_event = types.ModuleType("homeassistant.helpers.event")
    ha_const = types.ModuleType("homeassistant.const")

    class HomeAssistant:  # pragma: no cover
        pass

    class State:  # pragma: no cover
        def __init__(self, state=None, attributes=None):
            self.state = state
            self.attributes = attributes or {}

    def callback(func):  # pragma: no cover
        return func

    class ConfigEntry:  # pragma: no cover
        def __init__(self, data=None, options=None, entry_id="test"):
            self.data = data or {}
            self.options = options or {}
            self.entry_id = entry_id

    def async_track_state_change_event(*args, **kwargs):  # pragma: no cover
        return None

    core.HomeAssistant = HomeAssistant
    core.State = State
    core.callback = callback

    config_entries.ConfigEntry = ConfigEntry

    helpers.event = helpers_event
    helpers_event.async_track_state_change_event = async_track_state_change_event

    ha_const.STATE_UNAVAILABLE = "unavailable"
    ha_const.STATE_UNKNOWN = "unknown"
    ha_const.STATE_ON = "on"

    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.config_entries", config_entries)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.event", helpers_event)
    sys.modules.setdefault("homeassistant.const", ha_const)


_install_homeassistant_stubs()

# Ensure repository root is on sys.path so tests can import custom_components
_repo_root = Path(__file__).resolve().parents[1]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
