"""CASABOT Sensor Platform"""
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import CasabotCoordinator, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up CASABOT sensor from config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CasabotSensor(coordinator)], True)


class CasabotSensor(CoordinatorEntity, SensorEntity):
    """CASABOT Suggestions Sensor.

    State = number of total suggestions.
    Attributes = summary counts.
    """

    def __init__(self, coordinator: CasabotCoordinator):
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_name = "CASABOT Suggestions"
        self._attr_unique_id = "casabot_suggestions"
        self._attr_icon = "mdi:robot"
        self._attr_native_unit_of_measurement = "suggestions"

    @property
    def native_value(self):
        """State = total suggestions count."""
        if self.coordinator.data:
            return self.coordinator.data.get("total", 0)
        return 0

    @property
    def extra_state_attributes(self):
        """Full details for dashboard cards."""
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        suggestions = data.get("suggestions", [])
        return {
            "auto_ready": data.get("auto_ready", 0),
            "strong": data.get("strong", 0),
            "behaviours": data.get("behaviours", 0),
            "pending": sum(1 for s in suggestions if s.get("approval") == "pending"),
            "approved": sum(1 for s in suggestions if s.get("approval") == "approved"),
            "last_error": data.get("last_error"),
        }

    @property
    def available(self):
        """Return True if coordinator updated successfully."""
        return self.coordinator.last_update_success