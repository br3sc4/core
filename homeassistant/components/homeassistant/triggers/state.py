"""Offer state listening automation rules."""
from __future__ import annotations

from datetime import timedelta
import logging

import voluptuous as vol

from homeassistant import exceptions
from homeassistant.const import CONF_ATTRIBUTE, CONF_FOR, CONF_PLATFORM, MATCH_ALL
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, State, callback
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    template,
)
from homeassistant.helpers.event import (
    Event,
    async_track_same_state,
    async_track_state_change_event,
    process_state_match,
)
from homeassistant.helpers.typing import ConfigType

# mypy: allow-incomplete-defs, allow-untyped-calls, allow-untyped-defs
# mypy: no-check-untyped-defs

_LOGGER = logging.getLogger(__name__)

CONF_ENTITY_ID = "entity_id"
CONF_FROM = "from"
CONF_TO = "to"

BASE_SCHEMA = cv.TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_PLATFORM): "state",
        vol.Required(CONF_ENTITY_ID): cv.entity_ids_or_uuids,
        vol.Optional(CONF_FOR): cv.positive_time_period_template,
        vol.Optional(CONF_ATTRIBUTE): cv.match_all,
    }
)

TRIGGER_STATE_SCHEMA = BASE_SCHEMA.extend(
    {
        # These are str on purpose. Want to catch YAML conversions
        vol.Optional(CONF_FROM): vol.Any(str, [str], None),
        vol.Optional(CONF_TO): vol.Any(str, [str], None),
    }
)

TRIGGER_ATTRIBUTE_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Optional(CONF_FROM): cv.match_all,
        vol.Optional(CONF_TO): cv.match_all,
    }
)


async def async_validate_trigger_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType:
    """Validate trigger config."""
    if not isinstance(config, dict):
        raise vol.Invalid("Expected a dictionary")

    # We use this approach instead of vol.Any because
    # this gives better error messages.
    if CONF_ATTRIBUTE in config:
        config = TRIGGER_ATTRIBUTE_SCHEMA(config)
    else:
        config = TRIGGER_STATE_SCHEMA(config)

    registry = er.async_get(hass)
    config[CONF_ENTITY_ID] = er.async_resolve_entity_ids(
        registry, cv.entity_ids_or_uuids(config[CONF_ENTITY_ID])
    )

    return config


async def async_attach_trigger(
    hass: HomeAssistant,
    config,
    action,
    automation_info,
    *,
    platform_type: str = "state",
) -> CALLBACK_TYPE:
    """Listen for state changes based on configuration."""
    entity_ids = config[CONF_ENTITY_ID]
    if (from_state := config.get(CONF_FROM)) is None:
        from_state = MATCH_ALL
    if (to_state := config.get(CONF_TO)) is None:
        to_state = MATCH_ALL
    time_delta = config.get(CONF_FOR)
    template.attach(hass, time_delta)
    # If neither CONF_FROM or CONF_TO are specified,
    # fire on all changes to the state or an attribute
    match_all = CONF_FROM not in config and CONF_TO not in config
    unsub_track_same = {}
    period: dict[str, timedelta] = {}
    match_from_state = process_state_match(from_state)
    match_to_state = process_state_match(to_state)
    attribute = config.get(CONF_ATTRIBUTE)
    job = HassJob(action)

    trigger_data = automation_info["trigger_data"]
    _variables = automation_info["variables"] or {}

    @callback
    def state_automation_listener(event: Event):
        """Listen for state changes and calls action."""
        entity: str = event.data["entity_id"]
        from_s: State | None = event.data.get("old_state")
        to_s: State | None = event.data.get("new_state")

        if from_s is None:
            old_value = None
        elif attribute is None:
            old_value = from_s.state
        else:
            old_value = from_s.attributes.get(attribute)

        if to_s is None:
            new_value = None
        elif attribute is None:
            new_value = to_s.state
        else:
            new_value = to_s.attributes.get(attribute)

        # When we listen for state changes with `match_all`, we
        # will trigger even if just an attribute changes. When
        # we listen to just an attribute, we should ignore all
        # other attribute changes.
        if attribute is not None and old_value == new_value:
            return

        if (
            not match_from_state(old_value)
            or not match_to_state(new_value)
            or (not match_all and old_value == new_value)
        ):
            return

        @callback
        def call_action():
            """Call action with right context."""
            hass.async_run_hass_job(
                job,
                {
                    "trigger": {
                        **trigger_data,
                        "platform": platform_type,
                        "entity_id": entity,
                        "from_state": from_s,
                        "to_state": to_s,
                        "for": time_delta if not time_delta else period[entity],
                        "attribute": attribute,
                        "description": f"state of {entity}",
                    }
                },
                event.context,
            )

        if not time_delta:
            call_action()
            return

        trigger_info = {
            "trigger": {
                "platform": "state",
                "entity_id": entity,
                "from_state": from_s,
                "to_state": to_s,
            }
        }
        variables = {**_variables, **trigger_info}

        try:
            period[entity] = cv.positive_time_period(
                template.render_complex(time_delta, variables)
            )
        except (exceptions.TemplateError, vol.Invalid) as ex:
            _LOGGER.error(
                "Error rendering '%s' for template: %s", automation_info["name"], ex
            )
            return

        def _check_same_state(_, _2, new_st: State | None) -> bool:
            if new_st is None:
                return False

            cur_value: str | None
            if attribute is None:
                cur_value = new_st.state
            else:
                cur_value = new_st.attributes.get(attribute)

            if CONF_FROM in config and CONF_TO not in config:
                return cur_value != old_value

            return cur_value == new_value

        unsub_track_same[entity] = async_track_same_state(
            hass,
            period[entity],
            call_action,
            _check_same_state,
            entity_ids=entity,
        )

    unsub = async_track_state_change_event(hass, entity_ids, state_automation_listener)

    @callback
    def async_remove():
        """Remove state listeners async."""
        unsub()
        for async_remove in unsub_track_same.values():
            async_remove()
        unsub_track_same.clear()

    return async_remove
