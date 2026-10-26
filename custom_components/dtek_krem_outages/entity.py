"""Base entity for DTEK KREM Outages."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.typing import UNDEFINED, UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONFIGURATION_URL, DOMAIN, MANUFACTURER
from .coordinator import DtekCoordinator


class DtekEntity(CoordinatorEntity[DtekCoordinator]):
    """An entity belonging to the device of a DTEK KREM Outages entry.

    The name follows the language chosen for the entry instead of the language
    of Home Assistant; the entity ID is still built the way Home Assistant
    builds it, from the name in the language it uses for entity IDs.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: DtekCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=CONFIGURATION_URL,
        )

    def _translated_name(self, translations: dict[str, str]) -> str | None:
        """Return the name from entity translations keyed like Home Assistant."""
        return translations.get(
            f"component.{DOMAIN}.entity.{self.platform_data.domain}."
            f"{self.translation_key}.name"
        )

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name in the language chosen for the entry."""
        return self._translated_name(self.coordinator.translations) or super().name

    @property
    def suggested_object_id(self) -> str | None:
        """Return the object ID part built from the usual entity ID language."""
        name = (
            self._translated_name(self.platform_data.object_id_platform_translations)
            or super().name
        )
        return None if name is UNDEFINED else name
