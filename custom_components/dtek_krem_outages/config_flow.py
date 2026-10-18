"""Config flow for DTEK KREM Outages."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import DtekError, DtekNotFoundError, House, async_get_client
from .const import (
    CONF_GROUP,
    CONF_GROUP_MANUAL,
    CONF_HOUSE,
    CONF_LANGUAGE,
    CONF_SETTLEMENT,
    CONF_SHOW_POSSIBLE,
    CONF_STREET,
    CONF_UPDATE_INTERVAL,
    CONF_USE_MIRROR,
    CONF_WARN_END,
    CONF_WARN_START,
    DEFAULT_LANGUAGE,
    DEFAULT_OPTIONS,
    DOMAIN,
    GROUPS,
    LANGUAGES,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    WARNING_CHOICES,
    group_name,
    warning_thresholds,
)

_LOGGER = logging.getLogger(__name__)

_UK_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_SETTLEMENT_PREFIX = re.compile(r"^(м\.|с\.|смт|с-ще|селище|хут\.|х\.)\s*")
_STREET_PREFIX = re.compile(
    r"^(вулиця|вул\.?|провулок|пров\.|проспект|просп\.|бульвар|бульв\.|бул\.|"
    r"площа|пл\.|узвіз|шосе|туп\.)\s*",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Casefold and collapse the whitespace."""
    return " ".join(text.split()).casefold()


def place_name(settlement: str) -> str:
    """Return the settlement name without its ``м.``/``с.``/``смт`` prefix."""
    return _SETTLEMENT_PREFIX.sub("", _normalize(settlement))


def _street_name(street: str) -> str:
    """Return the street name without its ``вул.``/``пров.`` prefix."""
    return _STREET_PREFIX.sub("", _normalize(street))


def _collation_key(text: str) -> tuple[int, ...]:
    """Sort key following the Ukrainian alphabet (і, ї, є, ґ in place)."""
    return tuple(
        1000 + _UK_ALPHABET.index(char) if char in _UK_ALPHABET else ord(char)
        for char in text.casefold()
    )


def settlement_sort_key(name: str) -> tuple[tuple[int, ...], str]:
    """Sort settlements by name, ignoring the ``м.``/``с.``/``смт`` prefix."""
    return _collation_key(_SETTLEMENT_PREFIX.sub("", name)), name


def house_sort_key(number: str) -> list[Any]:
    """Natural sort for house numbers: 2, 10, 10а, 10/2, ..."""
    return [
        int(part) if part.isdigit() else _collation_key(part)
        for part in re.split(r"(\d+)", number)
    ]


def match_choice(value: Any, choices: Iterable[str]) -> str | None:
    """Return the choice equal to ``value``, ignoring case and spaces."""
    if not isinstance(value, str):
        return None
    wanted = _normalize(value)
    for choice in choices:
        if _normalize(choice) == wanted:
            return choice
    return None


def match_settlement(value: Any, streets: Mapping[str, list[str]]) -> str | None:
    """Return the settlement typed in ``value``, with or without its prefix.

    Without the prefix the name can fit several settlements; the one with the
    most streets wins, the street step lists the streets of the others too.
    """
    if (settlement := match_choice(value, streets)) is not None:
        return settlement
    if not isinstance(value, str):
        return None
    wanted = place_name(value)
    candidates = [name for name in streets if place_name(name) == wanted]
    return max(candidates, key=lambda name: len(streets[name]), default=None)


def street_choices(
    streets: Mapping[str, list[str]], settlement: str
) -> dict[str, tuple[str, str]]:
    """Return the street options of a settlement as label: (settlement, street).

    DTEK lists some places under several keys, e.g. ``с. Софіївська
    Борщагівка`` with 151 streets and ``Софіївська Борщагівка`` with just
    ``Без вулиці``. The streets of the keys with the same name (ignoring the
    prefix) are offered too, labelled with their settlement.
    """
    choices = {street: (settlement, street) for street in streets.get(settlement, [])}
    name = place_name(settlement)
    for other, names in streets.items():
        if other != settlement and place_name(other) == name:
            for street in names:
                choices[f"{street} ({other})"] = (other, street)
    return choices


def match_street(value: Any, choices: Mapping[str, tuple[str, str]]) -> str | None:
    """Return the label of the street typed in ``value``.

    The settlement in brackets and the ``вул.``/``пров.`` prefix may be left
    out when that leaves one street, looking at the chosen settlement first.
    """
    if (label := match_choice(value, choices)) is not None:
        return label
    if not isinstance(value, str) or not (wanted := _street_name(value)):
        return None
    for key, typed in ((_normalize, _normalize(value)), (_street_name, wanted)):
        candidates = [
            label for label, (_, street) in choices.items() if key(street) == typed
        ]
        own = [label for label in candidates if choices[label][1] == label]
        for found in (own, candidates):
            if len(found) == 1:
                return found[0]
    return None


def build_unique_id(settlement: str, street: str, house: str) -> str:
    """Return the unique ID of an address."""
    return f"{settlement}|{street}|{house}"


def build_title(settlement: str, street: str, house: str) -> str:
    """Generate an entry title like ``м. Бориспіль, вул. Нечая Івана, 43``."""
    if street.casefold() == "без вулиці":
        return f"{settlement}, {house}"
    return f"{settlement}, {street}, {house}"


def _select(options: list[str], *, custom_value: bool = True) -> SelectSelector:
    """A searchable dropdown; typed values are matched against the list."""
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=custom_value,
            sort=False,
        )
    )


def _language_select() -> SelectSelector:
    """A dropdown of the languages of the entity names."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=code, label=label)
                for code, label in LANGUAGES.items()
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _checked(options: Mapping[str, Any], key: str) -> list[str]:
    """Return the minutes ticked in a warning option, as selector values."""
    return [str(minutes) for minutes in warning_thresholds(options, key)]


def _warning_select(options: Mapping[str, Any], key: str) -> Any:
    """Checkboxes of the warning minutes, plus any other minutes already saved."""
    minutes = sorted({*WARNING_CHOICES, *warning_thresholds(options, key)})
    return vol.All(
        SelectSelector(
            SelectSelectorConfig(
                options=[str(m) for m in minutes],
                multiple=True,
                mode=SelectSelectorMode.LIST,
                translation_key="warning_minutes",
            )
        ),
        lambda value: sorted({int(m) for m in value}, reverse=True),
    )


def _options_schema(options: Mapping[str, Any]) -> dict[vol.Marker, Any]:
    values = {**DEFAULT_OPTIONS, **options}
    return {
        vol.Required(
            CONF_UPDATE_INTERVAL, default=values[CONF_UPDATE_INTERVAL]
        ): vol.All(
            NumberSelector(
                NumberSelectorConfig(
                    min=MIN_UPDATE_INTERVAL,
                    max=MAX_UPDATE_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Coerce(int),
        ),
        vol.Required(CONF_WARN_START, default=_checked(options, CONF_WARN_START)): (
            _warning_select(options, CONF_WARN_START)
        ),
        vol.Required(CONF_WARN_END, default=_checked(options, CONF_WARN_END)): (
            _warning_select(options, CONF_WARN_END)
        ),
        vol.Required(
            CONF_USE_MIRROR, default=values[CONF_USE_MIRROR]
        ): BooleanSelector(),
        vol.Required(
            CONF_SHOW_POSSIBLE, default=values[CONF_SHOW_POSSIBLE]
        ): BooleanSelector(),
        vol.Required(CONF_LANGUAGE, default=values[CONF_LANGUAGE]): vol.All(
            _language_select(), vol.In(LANGUAGES)
        ),
    }


class DtekKremConfigFlow(ConfigFlow, domain=DOMAIN):
    """Choose an address step by step: settlement, street, house, group."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._streets: dict[str, list[str]] | None = None
        self._settlement: str | None = None
        self._street: str | None = None
        self._houses: dict[str, House] | None = None
        self._house: str | None = None
        self._name: str | None = None
        self._language: str = DEFAULT_LANGUAGE
        self._groups: list[str] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DtekKremOptionsFlow:
        """Return the options flow."""
        return DtekKremOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the settlement."""
        errors: dict[str, str] = {}
        if self._streets is None:
            client = await async_get_client(self.hass)
            try:
                self._streets = await client.async_get_streets()
            except DtekError as err:
                _LOGGER.debug("Cannot load the streets from DTEK: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while loading the streets")
                errors["base"] = "unknown"
            if self._streets is None:
                return self.async_show_form(
                    step_id="user", data_schema=vol.Schema({}), errors=errors
                )
            # The submitted form was the empty retry form.
            user_input = None

        if user_input is not None:
            settlement = match_settlement(
                user_input.get(CONF_SETTLEMENT), self._streets
            )
            if settlement is None:
                errors[CONF_SETTLEMENT] = "unknown_settlement"
            else:
                if settlement != self._settlement:
                    self._street = None
                    self._houses = None
                self._settlement = settlement
                return await self.async_step_street()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SETTLEMENT,
                        description={"suggested_value": self._settlement},
                    ): _select(sorted(self._streets, key=settlement_sort_key))
                }
            ),
            errors=errors,
        )

    async def async_step_street(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the street."""
        choices = street_choices(self._streets or {}, self._settlement or "")
        errors: dict[str, str] = {}
        if user_input is not None and CONF_STREET in user_input:
            label = match_street(user_input[CONF_STREET], choices)
            if label is None:
                errors[CONF_STREET] = "unknown_street"
            else:
                address = choices[label]
                if address != (self._settlement, self._street):
                    self._houses = None
                self._settlement, self._street = address
                return await self.async_step_house()

        return self.async_show_form(
            step_id="street",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_STREET, description={"suggested_value": self._street}
                    ): _select(sorted(choices, key=_collation_key))
                }
            ),
            errors=errors,
            description_placeholders={"settlement": self._settlement},
        )

    async def async_step_house(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the house; DTEK tells its group."""
        settlement, street_name = self._settlement or "", self._street or ""
        errors: dict[str, str] = {}
        if self._houses is None:
            client = await async_get_client(self.hass)
            try:
                street = await client.async_get_street(settlement, street_name)
            except DtekNotFoundError:
                errors["base"] = "no_houses"
            except DtekError as err:
                _LOGGER.debug("Cannot load the houses from DTEK: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while loading the houses")
                errors["base"] = "unknown"
            else:
                if street.houses:
                    self._houses = street.houses
                else:
                    errors["base"] = "no_houses"
        if self._houses is None:
            # Submitting again retries; going back needs a new flow.
            return self.async_show_form(
                step_id="house",
                data_schema=vol.Schema({}),
                errors=errors,
                description_placeholders=self._placeholders(),
            )

        if user_input is not None and CONF_HOUSE in user_input:
            house = match_choice(user_input[CONF_HOUSE], self._houses)
            if house is None:
                errors[CONF_HOUSE] = "unknown_house"
            else:
                self._house = house
                self._name = (user_input.get(CONF_NAME) or "").strip() or None
                if user_input.get(CONF_LANGUAGE) in LANGUAGES:
                    self._language = user_input[CONF_LANGUAGE]
                groups = self._houses[house].groups
                if len(groups) == 1:
                    return await self._async_finish(groups[0], manual=False)
                self._groups = groups
                return await self.async_step_group()

        schema: dict[vol.Marker, Any] = {
            vol.Required(
                CONF_HOUSE, description={"suggested_value": self._house}
            ): _select(sorted(self._houses, key=house_sort_key)),
            vol.Optional(
                CONF_NAME, description={"suggested_value": self._name}
            ): TextSelector(),
        }
        if self.source != SOURCE_RECONFIGURE:
            # Reconfiguring keeps the options; the language is one of them.
            schema[vol.Required(CONF_LANGUAGE, default=self._language)] = (
                _language_select()
            )
        return self.async_show_form(
            step_id="house",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_group(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the group when DTEK lists none or several for the house."""
        if user_input is not None and user_input.get(CONF_GROUP) in GROUPS:
            return await self._async_finish(user_input[CONF_GROUP], manual=True)
        choices = self._groups or list(GROUPS)
        return self.async_show_form(
            step_id="group",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GROUP, default=choices[0]): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=g, label=group_name(g) or g)
                                for g in choices
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            description_placeholders={
                **self._placeholders(),
                "groups": ", ".join(group_name(g) or g for g in self._groups) or "—",
            },
        )

    def _placeholders(self) -> dict[str, str]:
        return {
            "settlement": self._settlement or "",
            "street": self._street or "",
            "house": self._house or "",
        }

    async def _async_finish(self, group: str, *, manual: bool) -> ConfigFlowResult:
        settlement = self._settlement or ""
        street = self._street or ""
        house = self._house or ""
        data = {
            CONF_SETTLEMENT: settlement,
            CONF_STREET: street,
            CONF_HOUSE: house,
            CONF_GROUP: group,
            CONF_GROUP_MANUAL: manual,
        }
        unique_id = build_unique_id(settlement, street, house)
        auto_title = build_title(settlement, street, house)

        if self.source != SOURCE_RECONFIGURE:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._name or auto_title,
                data=data,
                options={**DEFAULT_OPTIONS, CONF_LANGUAGE: self._language},
            )

        entry = self._get_reconfigure_entry()
        if any(
            other.unique_id == unique_id and other.entry_id != entry.entry_id
            for other in self._async_current_entries(include_ignore=False)
        ):
            return self.async_abort(reason="already_configured")
        title = self._name or entry.title
        old_title = build_title(
            entry.data[CONF_SETTLEMENT], entry.data[CONF_STREET], entry.data[CONF_HOUSE]
        )
        if not self._name and entry.title == old_title:
            title = auto_title
        # The coordinator notices the new address or group in its Store and
        # starts over with a silent baseline.
        return self.async_update_reload_and_abort(
            entry, unique_id=unique_id, title=title, data=data
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or group of an entry."""
        entry = self._get_reconfigure_entry()
        self._settlement = entry.data[CONF_SETTLEMENT]
        self._street = entry.data[CONF_STREET]
        self._house = entry.data[CONF_HOUSE]
        return await self.async_step_user()


class DtekKremOptionsFlow(OptionsFlowWithReload):
    """Handle the options; the entry reloads after saving."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    key: user_input.get(key, value)
                    for key, value in DEFAULT_OPTIONS.items()
                }
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_options_schema(self.config_entry.options)),
        )
