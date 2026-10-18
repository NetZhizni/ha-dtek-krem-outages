"""Constants for the DTEK KREM Outages integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

DOMAIN: Final = "dtek_krem_outages"
NAME: Final = "DTEK KREM Outages"

ATTRIBUTION: Final = "Data provided by DTEK Kyiv Regional Electric Networks"
MANUFACTURER: Final = "DTEK KREM"
CONFIGURATION_URL: Final = "https://www.dtek-krem.com.ua/ua/shutdowns"
PROJECT_URL: Final = "https://github.com/NetZhizni/ha-dtek-krem-outages"

SITE_BASE_URL: Final = "https://www.dtek-krem.com.ua"
SITE_AJAX_PATH: Final = "/ua/ajax"
SITE_REFERER_PATH: Final = "/ua/shutdowns"
CSRF_COOKIE: Final = "_csrf-dtek-krem"
# Backup source: a public mirror of the same ``fact``/``preset`` objects,
# refreshed every ~5 minutes (https://github.com/Baskerville42/outage-data-ua).
MIRROR_URL: Final = (
    "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/"
    "kyiv-region.json"
)
API_TIMEOUT: Final = 20
# Any ``updateFact`` that differs from the current version and is truthy in
# PHP (not empty, not "0") makes DTEK include the schedule in its answer.
FORCE_UPDATE_FACT: Final = "01.01.2000 00:00"

# DTEK publishes local Kyiv times without an offset.
TIMEZONE: Final = "Europe/Kyiv"

# Schedule groups ("черги") in UI order.
GROUPS: Final = (
    "GPV1.1",
    "GPV1.2",
    "GPV2.1",
    "GPV2.2",
    "GPV3.1",
    "GPV3.2",
    "GPV4.1",
    "GPV4.2",
    "GPV5.1",
    "GPV5.2",
    "GPV6.1",
    "GPV6.2",
)

CONF_SETTLEMENT: Final = "settlement"
CONF_STREET: Final = "street"
CONF_HOUSE: Final = "house"
CONF_GROUP: Final = "group"
# True when the user picked the group because the address had none or several.
CONF_GROUP_MANUAL: Final = "group_manual"
CONF_UPDATE_INTERVAL: Final = "update_interval"
# Minutes before an outage starts / ends to send a warning; both are lists.
CONF_WARN_START: Final = "warn_before_start"
CONF_WARN_END: Final = "warn_before_end"
# Single number kept by entries created before the two lists above.
CONF_WARNING_MINUTES: Final = "warning_minutes"
CONF_USE_MIRROR: Final = "use_mirror"
CONF_SHOW_POSSIBLE: Final = "show_possible"
# Language of the entity names and calendar texts, independent of the language
# of Home Assistant: it is often left English while people use Ukrainian.
CONF_LANGUAGE: Final = "language"

DEFAULT_UPDATE_INTERVAL: Final = 5
MIN_UPDATE_INTERVAL: Final = 2
MAX_UPDATE_INTERVAL: Final = 60
# After failed requests the interval doubles, up to this many minutes (or the
# configured interval if longer), with some jitter so entries spread out.
RETRY_MAX_INTERVAL: Final = 15
RETRY_JITTER: Final = 0.1
DEFAULT_WARN_START: Final[tuple[int, ...]] = (30,)
DEFAULT_WARN_END: Final[tuple[int, ...]] = ()
# Minutes offered as checkboxes in the options.
WARNING_CHOICES: Final[tuple[int, ...]] = (1, 5, 10, 15, 30, 60, 120)
DEFAULT_USE_MIRROR: Final = True
DEFAULT_SHOW_POSSIBLE: Final = True
# Language code: name shown in the selector.
LANGUAGES: Final[dict[str, str]] = {
    "uk": "Українська",
    "en": "English",
    "ru": "Русский",
}
DEFAULT_LANGUAGE: Final = "uk"

DEFAULT_OPTIONS: Final[dict[str, object]] = {
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    CONF_WARN_START: list(DEFAULT_WARN_START),
    CONF_WARN_END: list(DEFAULT_WARN_END),
    CONF_USE_MIRROR: DEFAULT_USE_MIRROR,
    CONF_SHOW_POSSIBLE: DEFAULT_SHOW_POSSIBLE,
    CONF_LANGUAGE: DEFAULT_LANGUAGE,
}

# Every event goes to the bus as EVENT_BUS with ``type`` set to one of these,
# and to the event entity with the same event type.
EVENT_BUS: Final = f"{DOMAIN}_event"
EVENT_SCHEDULE_PUBLISHED: Final = "schedule_published"
EVENT_SCHEDULE_CHANGED: Final = "schedule_changed"
EVENT_OUTAGE_WARNING: Final = "outage_warning"
EVENT_OUTAGE_END_WARNING: Final = "outage_end_warning"
EVENT_OUTAGE_STARTED: Final = "outage_started"
EVENT_OUTAGE_ENDED: Final = "outage_ended"
EVENT_ADDRESS_OUTAGE: Final = "address_outage"
EVENT_GROUP_CHANGED: Final = "group_changed"
EVENT_TYPES: Final = (
    EVENT_SCHEDULE_PUBLISHED,
    EVENT_SCHEDULE_CHANGED,
    EVENT_OUTAGE_WARNING,
    EVENT_OUTAGE_END_WARNING,
    EVENT_OUTAGE_STARTED,
    EVENT_OUTAGE_ENDED,
    EVENT_ADDRESS_OUTAGE,
    EVENT_GROUP_CHANGED,
)

# Kinds of the outage DTEK reports for an address, derived from its text.
OUTAGE_KIND_STABILIZATION: Final = "stabilization"
OUTAGE_KIND_EMERGENCY: Final = "emergency"
OUTAGE_KIND_PLANNED: Final = "planned"
OUTAGE_KIND_OTHER: Final = "other"
# The outage reported when DTEK lists several for one house.
OUTAGE_KIND_SEVERITY: Final[dict[str, int]] = {
    OUTAGE_KIND_EMERGENCY: 3,
    OUTAGE_KIND_STABILIZATION: 2,
    OUTAGE_KIND_PLANNED: 1,
    OUTAGE_KIND_OTHER: 0,
}
# State of the address status sensor without an outage.
ADDRESS_STATUS_NONE: Final = "none"
ADDRESS_STATUSES: Final = (
    ADDRESS_STATUS_NONE,
    OUTAGE_KIND_STABILIZATION,
    OUTAGE_KIND_EMERGENCY,
    OUTAGE_KIND_PLANNED,
    OUTAGE_KIND_OTHER,
)
# Entities that need an address; an entry set up by group only has none.
ADDRESS_ENTITIES: Final = (
    ("binary_sensor", "address_outage"),
    ("sensor", "address_status"),
    ("sensor", "restoration"),
)

SOURCE_DTEK: Final = "dtek"
SOURCE_MIRROR: Final = "mirror"
SOURCE_STORAGE: Final = "storage"

# State of the connection sensor: what answered the last update.
CONNECTION_OK: Final = "ok"
CONNECTION_MIRROR: Final = "mirror"
CONNECTION_OFFLINE: Final = "offline"
CONNECTION_STATES: Final = (CONNECTION_OK, CONNECTION_MIRROR, CONNECTION_OFFLINE)
# ``data_status`` attribute: the schedule was confirmed by the last update,
# or entities work on what was stored before.
DATA_CURRENT: Final = "current"
DATA_STALE: Final = "stale"

STORAGE_VERSION: Final = 1
# The Store is written at most this often for routine updates.
STORAGE_SAVE_DELAY: Final = 30
# Past days kept for the calendar and the history of what was in effect.
HISTORY_DAYS: Final = 7
# Days ahead the calendar fills with the weekly schedule of possible outages.
POSSIBLE_DAYS_AHEAD: Final = 7

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

# Calendar summaries are not covered by entity translations.
CALENDAR_TEXT: Final[dict[str, dict[str, str]]] = {
    "en": {
        "outage": "Power outage",
        "possible": "Possible outage",
        "group": "Group",
        "weekly": "Weekly schedule of possible outages",
    },
    "uk": {
        "outage": "Відключення світла",
        "possible": "Можливе відключення",
        "group": "Черга",
        "weekly": "Тижневий графік можливих відключень",
    },
    "ru": {
        "outage": "Отключение света",
        "possible": "Возможное отключение",
        "group": "Очередь",
        "weekly": "Недельный график возможных отключений",
    },
}


def group_name(group: str | None) -> str | None:
    """Return the short group name used by people: ``GPV3.1`` -> ``3.1``."""
    if group is None:
        return None
    return group.removeprefix("GPV")


def signal_event(entry_id: str) -> str:
    """Return the dispatcher signal used for the events of an entry."""
    return f"{DOMAIN}_event_{entry_id}"


def storage_key(entry_id: str) -> str:
    """Return the Store key holding the schedule state of an entry."""
    return f"{DOMAIN}.{entry_id}"


def warning_thresholds(options: Mapping[str, Any], key: str) -> tuple[int, ...]:
    """Return the warning minutes of an option, largest first.

    Entries saved before the lists existed hold one number in
    ``warning_minutes``, which stands for the "before start" list.
    """
    value = options.get(key)
    if value is None:
        legacy = options.get(CONF_WARNING_MINUTES) if key == CONF_WARN_START else None
        if legacy is not None:
            value = [legacy]
        else:
            value = DEFAULT_WARN_START if key == CONF_WARN_START else DEFAULT_WARN_END
    return tuple(sorted({int(m) for m in value if int(m) > 0}, reverse=True))
