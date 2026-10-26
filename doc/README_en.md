<img src="https://raw.githubusercontent.com/NetZhizni/ha-dtek-krem-outages/main/custom_components/dtek_krem_outages/brand/icon.png" alt="DTEK KREM Outages" width="96" align="right">

# DTEK KREM Outages

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/validate.yml/badge.svg)](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/validate.yml)
[![Tests](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/tests.yml/badge.svg)](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/tests.yml)

[Українська](../README.md) | **English**

Home Assistant integration for the power outage schedules of [DTEK Kyiv Regional Electric Networks](https://www.dtek-krem.com.ua/ua/shutdowns) (DTEK KREM, Kyiv region). It shows your group, the schedule for today and tomorrow and the outages reported for your address, and fires events when the schedule changes or an outage is about to start.

> Data provided by [DTEK KREM](https://www.dtek-krem.com.ua/ua/shutdowns). This project is not affiliated with DTEK.

## What it is

You pick your settlement, street and house the same way as on the DTEK website. The integration finds your group ("черга"), polls DTEK every few minutes and creates a device with sensors, a calendar and an event entity. It is configured entirely in the UI.

The schedule changes often, sometimes several times a day. So the integration:

- **keeps the current state** in Home Assistant storage: the schedule by day, its DTEK version, the weekly schedule of possible outages and the outage reported for the address. A restart, or both data sources being down (common during blackouts), doesn't lose the schedule: entities keep working on what is stored, and the `data_status` attribute tells that the last update did not confirm it;
- **applies a new version only to the future**: half-hours that already passed keep what was in effect, the current and later half-hours take the new values. Days DTEK doesn't list (tomorrow before it is published) are kept;
- **shows what the DTEK website shows**: when the page hides the schedule of the day or the weekly schedule of possible outages, the entities and the calendar hide it too;
- **announces changes**: `schedule_published` (a new day appeared, usually tomorrow) and `schedule_changed` (the rest of a day changed), with the new and the previous outages;
- **warns before outages**: `outage_warning` before a scheduled outage starts and `outage_end_warning` before it ends (power returns), each at the times you tick (e.g. 30 and 5 minutes). `outage_started` and `outage_ended` come at the exact times, without waiting for the next poll.

## What it looks like

<img src="https://raw.githubusercontent.com/NetZhizni/ha-dtek-krem-outages/main/doc/images/dashboard.png" alt="Markdown, Entities and Calendar cards with the integration's data" width="640">

Setup: settlement → street → house, the same as on the DTEK site.

<img src="https://raw.githubusercontent.com/NetZhizni/ha-dtek-krem-outages/main/doc/images/setup.gif" alt="Adding the integration: choosing the settlement, street and house" width="400">

| Device | Calendar |
|---|---|
| <img src="https://raw.githubusercontent.com/NetZhizni/ha-dtek-krem-outages/main/doc/images/device.png" alt="Device page with the sensors" width="380"> | <img src="https://raw.githubusercontent.com/NetZhizni/ha-dtek-krem-outages/main/doc/images/calendar.png" alt="Outage calendar with an event" width="480"> |

Screenshots are from a Home Assistant instance with the Ukrainian UI.

## How it gets the data

| Source | What | When |
|---|---|---|
| [dtek-krem.com.ua](https://www.dtek-krem.com.ua/ua/shutdowns) | Houses of your street with their group and current outage, the actual schedule (`fact`), the weekly schedule (`preset`) and the flags telling what of it the page shows | Every update |
| [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua) (public mirror of the same `fact`/`preset`, updated about every 5 min) | Schedule only, no address data | Only when DTEK fails, and only if its version is newer; always for an entry without an address |

The DTEK pages are behind an anti-bot JavaScript challenge, but the endpoint the shutdowns page loads its data from (`POST /ua/ajax`) is not. The integration uses that endpoint like the page does: with the site's CSRF token, one request per entry per update and an honest User-Agent. It sends the version it already has, and DTEK includes the schedule only when there is a newer one, so most answers are a few kilobytes. The integration does not get around the anti-bot challenge and does not pretend to be a browser.

After a failed request the update interval doubles (5 → 10 → 15 min by default, with a little random jitter) and returns to normal after the first successful answer. This keeps the integration from flooding DTEK while the site isn't answering.

## Installation

> Home Assistant version requirement:
>
> - Core $\geq$ 2025.8

### Method 1: [HACS](https://hacs.xyz/) (recommended)

[![Open your Home Assistant instance and open the DTEK KREM Outages repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=NetZhizni&repository=ha-dtek-krem-outages&category=integration)

Or add the repository by hand:

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/NetZhizni/ha-dtek-krem-outages` with type **Integration**.
2. In the HACS search box, type **DTEK KREM Outages** → open it → **Download**.
3. Restart Home Assistant.

### Method 2: Git clone from GitHub

```bash
cd /config
git clone https://github.com/NetZhizni/ha-dtek-krem-outages.git
mkdir -p custom_components
cp -r ha-dtek-krem-outages/custom_components/dtek_krem_outages custom_components/
```

Restart Home Assistant afterwards. To switch to a release later, `git fetch --tags && git checkout <version>` in the clone and copy the folder again.

### Method 3: Manual installation via [Samba](https://github.com/home-assistant/addons/tree/master/samba) / [FTPS](https://github.com/hassio-addons/addon-ftp)

1. Download the latest release from [Releases](https://github.com/NetZhizni/ha-dtek-krem-outages/releases).
2. Copy `custom_components/dtek_krem_outages` into `config/custom_components`.
3. Restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up a new DTEK KREM Outages integration instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dtek_krem_outages)

**Settings → Devices & services → Add integration → DTEK KREM Outages**, then:

1. **Settlement**: start typing, e.g. `Бориспіль`. The list is the one DTEK uses (about 1200 settlements).
2. **Street**: villages without street names have `Без вулиці`. DTEK lists some places under several spellings (`с. Софіївська Борщагівка` and `Софіївська Борщагівка`). The streets of all of them are shown, the ones of another spelling with it in brackets, so the settlement you picked does not matter.
3. **House**: as DTEK lists it (`43`, `8 а`, `1/2`, ...). Optionally give the entry a short **Name**, e.g. `Home`: entity IDs are built from it (`sensor.home_next_outage`). The examples below assume that name. **Language of entity names**: Ukrainian (default), English or Russian, see the options below.
4. **Group**: asked only when DTEK lists no group or several groups for the house. Otherwise the group is detected, and if DTEK later moves the house to another group the entry follows it (`group_changed` event). A group you chose yourself is never replaced.

Each address can be added once; add several entries for several addresses. **⋮ → Reconfigure** changes the address or group.

### When DTEK is unavailable

When the list of settlements can't be loaded from DTEK while adding the entry, the integration offers two choices:

- **Try again**;
- **Follow a group without an address**: you choose the group (the DTEK website shows it after you enter the address), and the schedule comes from the mirror. There is no address data then (group detection and changes, outages at the address), so the address entities are not created. The entry gets a title like `Черга 3.1` (`Group 3.1` in English). Once DTEK is back, the address can be added with **⋮ → Reconfigure**.

### Options

| Option | Default | Description |
|---|---|---|
| Update interval | 5 min | Minutes between requests to DTEK, at least 2. After failures it grows for a while, up to 15 min (or your interval if it is longer) |
| Warn before an outage starts | 30 min | Checkboxes (1, 5, 10, 15, 30, 60, 120 min): when `outage_warning` fires, one event per ticked time; nothing ticked turns it off |
| Warn before an outage ends (power returns) | none | The same for `outage_end_warning` |
| Use the backup source | on | Take the schedule from the mirror when DTEK can't be reached. Not offered for an entry without an address, where the mirror is the only source |
| Show possible outages in the calendar | on | Fill the next 7 days without an actual schedule with the weekly schedule of possible outages, while DTEK shows that schedule on its website |
| Language of entity names | Українська | Language of the entity names and calendar events (Ukrainian, English or Russian), whatever the language of Home Assistant. Entity IDs stay in English |

The entry reloads by itself after saving.

## Entities

Each entry creates one device:

| Entity | State |
|---|---|
| `sensor.…_group` | Group, e.g. `3.1`. Attributes: `group_id` (`GPV3.1`), `groups_at_address`, `manual`, the address, `external_operator` |
| `sensor.…_next_outage` | Start of the next scheduled outage (timestamp). Attributes: `end`, `duration_minutes` |
| `sensor.…_outage_end` | End of the outage in progress; `unknown` when there is none |
| `sensor.…_outages_today` | Scheduled outage time today, hours. Attributes: `outages_text` (`12:00–14:00, 18:00–20:30`), `outages`, `possible_text`, `schedule`, `published` |
| `sensor.…_outages_tomorrow` | The same for tomorrow; `unknown` until DTEK publishes it |
| `sensor.…_schedule_updated` | When DTEK last changed the schedule. Attributes: `version`, `source` (`dtek` / `mirror` / `storage`) |
| `sensor.…_address_status` | What DTEK reports for the house: `none` (no outage), `stabilization`, `emergency`, `planned` or `other`. Attributes: `reason`, `start`, `end`, `active` (now between start and end), `external_operator`. `unavailable` when DTEK itself can't be reached |
| `sensor.…_estimated_restoration` | When DTEK expects the power back at the address (timestamp); `unknown` without an outage. Attribute: `reason` |
| `sensor.…_last_update` | Last time a source answered (diagnostic). Attribute: `last_error` |
| `sensor.…_dtek_connection` | What answered the last update (diagnostic): `ok` (DTEK), `mirror` (only the mirror) or `offline` (nothing, stored data in use). Attributes: `last_success`, `last_dtek_success`, `consecutive_failures`, `update_interval_minutes`, `blocked` (DTEK answered with the anti-bot challenge), `last_error`, `daily_schedule_shown`, `weekly_schedule_shown` |
| `binary_sensor.…_scheduled_outage` | `on` (shown as *Problem*) during a scheduled outage. Attributes: `start`, `end`, `next_start`, `next_end` |
| `binary_sensor.…_address_outage` | `on` (shown as *Problem*) while an outage DTEK reports for the house lasts: stabilization, emergency or planned works, with its own start and end. Attributes: `reason`, `kind`, `start`, `end`. `unavailable` when DTEK itself can't be reached |
| `calendar.…_outages` | Scheduled outages, possible outages and non-stabilization works reported for the address |
| `event.…_outage_events` | Every event below (`event_type` is the event type, attributes are its data) |

An entry without an address has no `address_status`, `estimated_restoration` and `address_outage`.

The entities computed from the schedule (`next_outage`, `outage_end`, `outages_today`, `outages_tomorrow`, `scheduled_outage`, the calendar) have two more attributes:

- `data_status`: `current` when the last update got the schedule from DTEK or the mirror, `stale` when no source answered and the entities work on what is stored;
- `last_verified_at`: when a source last confirmed the schedule.

All times are Kyiv time. Sensors switch at the exact moment an outage starts or ends and at midnight, not only on updates.

When DTEK reports several outages for a house at once, the most severe one is shown (emergency, then stabilization, then planned works). If DTEK marks the house as served by another operator, `external_operator` is `true` and a warning goes to the log: the DTEK schedule may not apply to such a house.

## Events

Every event is fired on the bus as `dtek_krem_outages_event` with `type`, and on the event entity with the same data.

Every event has `type`, `group` (`GPV3.1`), `group_name` (`3.1`), `settlement`, `street`, `house` (`null` for an entry without an address), `config_entry_id`, `entry_title`, plus:

| `type` | When | Fields |
|---|---|---|
| `schedule_published` | A day got its schedule for the first time (usually tomorrow, in the evening) | `date`, `day` (`today` / `tomorrow` / `other`), `outages` (`[{start, end}]`), `outages_text`, `outage_minutes`, `possible`, `schedule`, `schedule_updated`, `source` |
| `schedule_changed` | The schedule of a day changed from now on | the same, plus `previous_outages`, `previous_outages_text`, `previous_outage_minutes` |
| `outage_warning` | N minutes before a scheduled outage starts, once for each ticked time, or at once (a single event) if a new outage starts sooner | `start`, `end`, `duration_minutes`, `minutes` (left) |
| `outage_end_warning` | N minutes before a scheduled outage ends and the power returns, once for each ticked time (not for a time longer than the outage) | `start`, `end`, `duration_minutes`, `minutes` (left) |
| `outage_started` | A scheduled outage starts | `start`, `end`, `duration_minutes` |
| `outage_ended` | A scheduled outage ends | `start`, `end`, `duration_minutes`, `next_start`, `next_end` |
| `address_outage` | DTEK reports an outage for the house, changes its end, or clears it | `status` (`new` / `updated` / `cleared`), `reason`, `kind` (`stabilization` / `emergency` / `planned` / `other`), `start`, `end`, `previous_end` |
| `group_changed` | DTEK moved the house to another group | `previous_group`, `previous_group_name` |

Rules:

- **First run**: the current state is recorded silently, no schedule events.
- **Changes in the past only** (DTEK rewrites a finished half-hour) fire nothing.
- **DTEK hides the schedule of the day** (the page stops showing the table): the rest of the day and the following days are cleared and `schedule_changed` fires with no outages. When the table is back, the integration asks for the whole schedule at once and another `schedule_changed` fires.
- **After a restart**, changes published while Home Assistant was down are announced. Events wait until Home Assistant has started, so automations receive them.
- `outage_started` / `outage_ended` are not fired for an edge that passed while Home Assistant was down. A warning is not repeated after a restart. When the integration wakes up late, inside several ticked times at once, it sends one event, not one per time.

## Services

| Service | Description |
|---|---|
| `dtek_krem_outages.refresh` | Update now. `config_entry_id` is optional; fails when no source answered |
| `dtek_krem_outages.get_schedule` | Returns `{entries: [{group, days: {date: {outages, outages_text, outage_minutes, possible, schedule}}, weekly, address_outage, source, connection, data_status, publication, ...}]}` |

## Examples

### New or changed schedule → Telegram

```yaml
alias: "Outage schedule → Telegram"
triggers:
  - trigger: event
    event_type: dtek_krem_outages_event
    event_data:
      type: schedule_published
  - trigger: event
    event_type: dtek_krem_outages_event
    event_data:
      type: schedule_changed
actions:
  - action: telegram_bot.send_message
    data:
      message: >-
        {{ '🆕 Schedule for' if trigger.event.data.type == 'schedule_published'
           else '✏️ Changed schedule for' }}
        {{ trigger.event.data.day if trigger.event.data.day != 'other'
           else trigger.event.data.date }}
        (group {{ trigger.event.data.group_name }}):
        {{ trigger.event.data.outages_text or 'no outages' }}
        {%- if trigger.event.data.previous_outages_text is defined %}
        (was: {{ trigger.event.data.previous_outages_text or 'no outages' }})
        {%- endif %}
mode: queued
```

### Warning on the phone

Tick the times in the options (e.g. 30 and 5 minutes before the start); `minutes` tells which one fired. Use `type: outage_end_warning` the same way for the power coming back.

```yaml
alias: "Outage soon → phone"
triggers:
  - trigger: event
    event_type: dtek_krem_outages_event
    event_data:
      type: outage_warning
conditions:
  # Don't warn from a schedule no source has confirmed.
  - condition: state
    entity_id: binary_sensor.home_scheduled_outage
    attribute: data_status
    state: current
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "⚡ Outage in {{ trigger.event.data.minutes }} min"
      message: >-
        {{ as_timestamp(trigger.event.data.start) | timestamp_custom('%H:%M') }}–{{
           as_timestamp(trigger.event.data.end) | timestamp_custom('%H:%M') }}
mode: queued
```

### Emergency works at the address

```yaml
alias: "Emergency outage at home"
triggers:
  - trigger: event
    event_type: dtek_krem_outages_event
    event_data:
      type: address_outage
conditions:
  - "{{ trigger.event.data.status != 'cleared' }}"
  - "{{ trigger.event.data.kind != 'stabilization' }}"
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "🚧 {{ trigger.event.data.reason }}"
      message: >-
        Until {{ as_timestamp(trigger.event.data.end) | timestamp_custom('%d.%m %H:%M')
                 if trigger.event.data.end else 'unknown' }}
mode: queued
```

Instead of the bus event you can trigger on the event entity; the data is then in `trigger.to_state.attributes`:

```yaml
triggers:
  - trigger: state
    entity_id: event.home_outage_events
    attribute: event_type
    to: outage_warning
```

### Calendar reminder of planned works

A calendar trigger fires at an offset from the start of an event. Works at the address are the only calendar events with a `location`:

```yaml
alias: "Planned works tomorrow → phone"
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.home_outages
    offset: "-12:00:00"
conditions:
  - "{{ trigger.calendar_event.location | default('', true) != '' }}"
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "🛠 {{ trigger.calendar_event.summary }}"
      message: >-
        {{ as_timestamp(trigger.calendar_event.start) | timestamp_custom('%d.%m %H:%M') }}–{{
           as_timestamp(trigger.calendar_event.end) | timestamp_custom('%H:%M') }}
mode: queued
```

### DTEK silent for an hour

```yaml
alias: "No connection to DTEK"
triggers:
  - trigger: state
    entity_id: sensor.home_dtek_connection
    to: offline
    for: "01:00:00"
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "📡 No connection to DTEK"
      message: >-
        The schedule from {{ as_timestamp(state_attr('sensor.home_dtek_connection', 'last_success'))
                             | timestamp_custom('%d.%m %H:%M') }} may be out of date.
```

### Lovelace card

```yaml
type: markdown
content: |
  **Group {{ states('sensor.home_group') }}**

  Today: {{ state_attr('sensor.home_outages_today', 'outages_text') or 'no outages' }}

  Tomorrow: {% if state_attr('sensor.home_outages_tomorrow', 'published') -%}
  {{ state_attr('sensor.home_outages_tomorrow', 'outages_text') or 'no outages' }}
  {%- else %}not published yet{% endif %}

  {% if is_state('binary_sensor.home_scheduled_outage', 'on') -%}
  ⚫ Power back at {{ as_timestamp(states('sensor.home_outage_end')) | timestamp_custom('%H:%M') }}
  {%- elif states('sensor.home_next_outage') not in ['unknown', 'unavailable'] -%}
  🟢 Next outage {{ as_timestamp(states('sensor.home_next_outage')) | timestamp_custom('%d.%m %H:%M') }}
  {%- endif %}

  {% if state_attr('sensor.home_next_outage', 'data_status') == 'stale' -%}
  ⚠️ No connection to DTEK, showing the stored schedule
  {%- endif %}

  <sub>Data: DTEK KREM, updated {{ as_timestamp(states('sensor.home_schedule_updated')) | timestamp_custom('%d.%m %H:%M') }}</sub>
```

For a week view, use the standard **Calendar** card with `calendar.home_outages`.

## Troubleshooting

| What you see | What to do |
|---|---|
| The integration is not in the list | Restart Home Assistant. Check that `manifest.json` is right in `config/custom_components/dtek_krem_outages/` |
| Your settlement, street or house is missing | Check the address on [dtek-krem.com.ua](https://www.dtek-krem.com.ua/ua/shutdowns): the list is the same. Kyiv city is served by another operator (DTEK KEM / Yasno) |
| "DTEK is unavailable" while adding | Try again later, or add the entry by group only and the address later with **Reconfigure** |
| `sensor.…_dtek_connection` shows `mirror` or `offline` | DTEK is not answering right now; `blocked: true` means it answered with the anti-bot challenge. The integration retries by itself, at most every 15 min. Don't remove and re-add the entry: the stored schedule keeps working anyway |
| No possible outages in the calendar | DTEK doesn't show the weekly schedule right now (`weekly_schedule_shown: false` on `sensor.…_dtek_connection`), or the "Show possible outages" option is off |
| The schedule suddenly says "no outages" | If `daily_schedule_shown` is `false`, DTEK hid the schedule on its website; the integration shows it again as soon as it is back |
| `external_operator: true` | DTEK says another operator serves the house, and its schedule may not apply to the address |

## Diagnostics

**Devices & services → DTEK KREM Outages → ⋮ → Download diagnostics**. The street and house number are redacted; the settlement, group and schedule stay.

## Known limitations

- The integration depends on the DTEK website. If DTEK changes the endpoint or puts it behind the anti-bot challenge too, the schedule still comes from the mirror, but the address data (group detection, `address_outage`) stops until the integration is updated.
- The mirror updates about every 5 minutes and can lag behind DTEK.
- The schedule has half-hour precision, like on the DTEK website. On DST change days the missing or repeated hour follows the wall clock.
- One group per entry. If the house has several groups (entrances on different lines), choose yours; add several entries for several groups.
- Only DTEK KREM (Kyiv region). Kyiv city is served by DTEK KEM / Yasno, which this integration does not cover.

## Comparison with other integrations

Two more Home Assistant integrations cover DTEK KREM. The comparison is based on their code as of 2026-10-18: [groove-max/ha-dtek-monitor](https://github.com/groove-max/ha-dtek-monitor) version 1.7.0 and [aavdberg/ha-dtek](https://github.com/aavdberg/ha-dtek) version 0.1.3. Both are developed actively, so check their repositories for the current state.

| | **DTEK KREM Outages** (this one) | **DTEK Monitor** (groove-max) | **DTEK Outages** (aavdberg) |
|---|---|---|---|
| Operators | DTEK KREM | DTEK OEM, KREM, DNEM, KEM | DTEK DNEM, KEM, KREM, OEM |
| How it gets the data | `POST /ua/ajax` with the CSRF token from the cookie, honest User-Agent | Loads the `/ua/shutdowns` page with `curl_cffi`, which imitates Chrome (TLS fingerprint, headers), then `/ua/ajax` | Loads the `/ua/shutdowns` page with `aiohttp` and a browser User-Agent, then `/ua/ajax` |
| Third-party dependencies | none | `curl_cffi` | none |
| Backup source | Baskerville42 mirror | none | none |
| Hourly schedule of the group | yes, 7 days of history | yes, 8 days ahead | no, only outages at the address |
| Weekly schedule of possible outages | yes, when DTEK shows it | yes, when DTEK shows it | no |
| Outages at the address | kind, reason, start, estimated restoration | kind, description, start, end | reason, next outage, restoration |
| House with several groups | a step to choose your group | all groups together, each calendar event knows its own | the first group listed |
| Sensors switch | at the exact start and end of a scheduled outage | from the address status, on every poll (5 min) | on every poll (15 min) |
| Events and warnings | 8 event types, warnings N min before the start and the end | none | none |
| Services | `refresh`, `get_schedule` | none | none |
| When DTEK doesn't answer | keeps working on the stored schedule, `data_status: stale`, mirror | "live" calendars are empty, a separate "last known schedule" calendar | entities become unavailable |
| Setup without access to DTEK | yes, by group only (schedule from the mirror) | no | yes, manual group entry |
| DTEK personal account | no | no | yes, phone and password sign-in |
| UI languages | Ukrainian, English, Russian; a separate choice of the entity name language | Ukrainian, English | English, Dutch, Ukrainian |
| Minimum HA version | 2025.8 | 2026.3 | 2026.9 |
| License | MIT | PolyForm Noncommercial 1.0.0 (not an OSI open-source license) | MIT |

Some notes on the table:

- On KREM the `/ua/shutdowns` page is behind the Incapsula JavaScript challenge. On 2026-10-18 a plain request to it got a 212-byte stub without a CSRF token. DTEK Monitor gets through by imitating a browser. DTEK Outages looks for the token in that very page, so for KREM it depends on Incapsula letting it through. This integration doesn't load the page.
- DTEK Outages tells the outage kind by the `type` code: `1` planned works, `2` emergency. On KREM the scheduled stabilization outages have code `2` too, so they show as emergencies. This integration and DTEK Monitor tell the kind by the text of the reason.
- DTEK Monitor covers four operators and is very strict about data freshness. Besides the outages at the address, DTEK Outages shows personal account data: balance, meter, contract.

### What was taken from these projects

Version 0.1.3 brought over ideas (not code) from both projects:

- from DTEK Monitor:
  - the DTEK page flags: a hidden daily or weekly schedule is not shown;
  - a house DTEK lists as several records, one per outage;
  - the other operator mark (`external_operator`);
  - the DTEK connection sensor and the `data_status` / `last_verified_at` attributes;
  - a longer interval after failures, with random jitter;
  - separate sensors for the address status and the estimated restoration;
- from DTEK Outages:
  - an entry by group only when DTEK is unavailable;
  - house numbers found regardless of case, spaces and Latin letters;
  - the calendar reminder example.

Deliberately left out:

- **Imitating a browser for other operators.** This integration won't get around the anti-bot challenge.
- **The personal account.** It would mean storing the phone number and password of the account.
- **Several groups in one entry.** A flat is fed by one line; add several entries if you need several groups.

## Attribution

Outage data is provided by DTEK Kyiv Regional Electric Networks; every entity carries the attribution `Data provided by DTEK Kyiv Regional Electric Networks`. The backup copy comes from [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua).

## Releases

The `Tag & Release` workflow runs on every push to `main` and reads `version` from `custom_components/dtek_krem_outages/manifest.json`, the only place the version is kept. It first runs the tests, hassfest and HACS validation. If they pass and the tag or GitHub release for that version doesn't exist yet, the workflow creates whichever is missing, and HACS offers that release as an update. The release notes are the version's section in `CHANGELOG.md`. To publish a release:

1. Bump `version` in `manifest.json`.
2. Add a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md` (a test checks it exists).
3. Push to `main`.

## Feedback

- A bug, an address that can't be found or a wrong group: [open an issue](https://github.com/NetZhizni/ha-dtek-krem-outages/issues/new/choose), there is a template for each case.
- Questions, ideas, your automations and dashboards: [Discussions](https://github.com/NetZhizni/ha-dtek-krem-outages/discussions).
- Want to help with the code: see [CONTRIBUTING.md](../CONTRIBUTING.md).

If the integration is useful to you, star the repository: it helps others find it.

## License

[MIT](../LICENSE)
