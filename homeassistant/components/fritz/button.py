"""Switches for AVM Fritz!Box buttons."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Final

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ENTITY_CATEGORY_CONFIG
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .common import FritzBoxTools
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class FritzButtonDescriptionMixin:
    """Mixin to describe a Button entity."""

    press_action: Callable


@dataclass
class FritzButtonDescription(ButtonEntityDescription, FritzButtonDescriptionMixin):
    """Class to describe a Button entity."""


BUTTONS: Final = [
    FritzButtonDescription(
        key="firmware_update",
        name="Firmware Update",
        device_class=ButtonDeviceClass.UPDATE,
        entity_category=ENTITY_CATEGORY_CONFIG,
        press_action=lambda router: router.async_trigger_firmware_update(),
    ),
    FritzButtonDescription(
        key="reboot",
        name="Reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=ENTITY_CATEGORY_CONFIG,
        press_action=lambda router: router.async_trigger_reboot(),
    ),
    FritzButtonDescription(
        key="reconnect",
        name="Reconnect",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=ENTITY_CATEGORY_CONFIG,
        press_action=lambda router: router.async_trigger_reconnect(),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set buttons for device."""
    _LOGGER.debug("Setting up buttons")
    router: FritzBoxTools = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([FritzButton(router, entry.title, button) for button in BUTTONS])


class FritzButton(ButtonEntity):
    """Defines a Fritz!Box base button."""

    entity_description: FritzButtonDescription

    def __init__(
        self,
        router: FritzBoxTools,
        device_friendly_name: str,
        description: FritzButtonDescription,
    ) -> None:
        """Initialize Fritz!Box button."""
        self.entity_description = description
        self.router = router

        self._attr_name = f"{device_friendly_name} {description.name}"
        self._attr_unique_id = slugify(self._attr_name)
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, router.mac)}
        )

    async def async_press(self) -> None:
        """Triggers Fritz!Box service."""
        await self.entity_description.press_action(self.router)
