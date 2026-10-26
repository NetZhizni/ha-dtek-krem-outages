<img src="https://raw.githubusercontent.com/NetZhizni/ha-dtek-krem-outages/main/custom_components/dtek_krem_outages/brand/icon.png" alt="DTEK KREM Outages" width="96" align="right">

# DTEK KREM Outages

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/validate.yml/badge.svg)](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/validate.yml)
[![Tests](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/tests.yml/badge.svg)](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/tests.yml)

**English** | [Українська](https://github.com/NetZhizni/ha-dtek-krem-outages/blob/main/doc/README_uk.md)

Home Assistant integration for the power outage schedules of [DTEK Kyiv Regional Electric Networks](https://www.dtek-krem.com.ua/ua/shutdowns) (DTEK KREM, Kyiv region): your group, the schedule for today and tomorrow, outages reported for your address, and events when the schedule changes or an outage is about to start.

> Data provided by [DTEK KREM](https://www.dtek-krem.com.ua/ua/shutdowns). This project is not affiliated with DTEK.

## What it is

You pick your settlement, street and house the same way as on the DTEK website. The integration finds your group ("черга"), polls DTEK every few minutes and creates a device with sensors, a calendar and an event entity. It is configured entirely in the UI.

The schedule changes often, sometimes several times a day. So the integration:

- **keeps the current state** in Home Assistant storage: the schedule by day, its DTEK version, the weekly schedule of possible outages and the outage reported for the address. A restart, or both data sources being down (common during blackouts), doesn't lose the schedule; entities keep working on what is stored;
- **applies a new version only to the future**: half-hours that already passed keep what was in effect, the current and later half-hours take the new values. Days DTEK doesn't list (tomorrow before it is published) are kept;
- **announces changes**: `schedule_published` (a new day appeared, usually tomorrow) and `schedule_changed` (the rest of a day changed), with the new and the previous outages;
- **warns before outages**: `outage_warning` N minutes before a scheduled outage, `outage_started` and `outage_ended` at the exact times, without waiting for the next poll.

## How it gets the data

| Source | What | When |
|---|---|---|
| [dtek-krem.com.ua](https://www.dtek-krem.com.ua/ua/shutdowns) | Houses of your street with their group and current outage, the actual schedule (`fact`) and the weekly schedule (`preset`) | Every update |
| [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua) (public mirror of the same `fact`/`preset`, updated about every 5 min) | Schedule only, no address data | Only when DTEK fails, and only if its version is newer |

The DTEK pages are behind an anti-bot JavaScript challenge, but the endpoint the shutdowns page loads its data from (`POST /ua/ajax`) is not. The integration uses that endpoint like the page does, including the site's CSRF token, with one request per entry per update and an honest User-Agent. It sends the version it already has, and DTEK includes the schedule only when there is a newer one, so most answers are a few kilobytes.

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
2. **Street**: villages without street names have `Без вулиці`.
3. **House**: as DTEK lists it (`43`, `8 а`, `1/2`, ...). Optionally give the entry a short **Name**, e.g. `Home`: entity IDs are built from it (`sensor.home_next_outage`). The examples below assume that name.
4. **Group**: asked only when DTEK lists no group or several groups for the house. Otherwise the group is detected, and if DTEK later moves the house to another group the entry follows it (`group_changed` event). A group you chose yourself is never replaced.

Each address can be added once; add several entries for several addresses. **⋮ → Reconfigure** changes the address or group.

### Options

| Option | Default | Description |
|---|---|---|
| Update interval | 5 min | Minutes between requests to DTEK, at least 2 |
| Warning before an outage | 30 min | When `outage_warning` fires; 0 turns warnings off |
| Use the backup source | on | Take the schedule from the mirror when DTEK can't be reached |
| Show possible outages in the calendar | on | Fill the next 7 days without an actual schedule with the weekly schedule of possible outages |

The entry reloads by itself after saving.

## Entities

Each entry creates one device:

| Entity | State |
|---|---|
| `sensor.…_group` | Group, e.g. `3.1`. Attributes: `group_id` (`GPV3.1`), `groups_at_address`, `manual`, the address |
| `sensor.…_next_outage` | Start of the next scheduled outage (timestamp). Attributes: `end`, `duration_minutes` |
| `sensor.…_outage_end` | End of the outage in progress; `unknown` when there is none |
| `sensor.…_outages_today` | Scheduled outage time today, hours. Attributes: `outages_text` (`12:00–14:00, 18:00–20:30`), `outages`, `possible_text`, `schedule`, `published` |
| `sensor.…_outages_tomorrow` | The same for tomorrow; `unknown` until DTEK publishes it |
| `sensor.…_schedule_updated` | When DTEK last changed the schedule. Attributes: `version`, `source` (`dtek` / `mirror` / `storage`) |
| `sensor.…_last_update` | Last time a source answered (diagnostic). Attribute: `last_error` |
| `binary_sensor.…_scheduled_outage` | `on` during a scheduled outage. Attributes: `start`, `end`, `next_start`, `next_end` |
| `binary_sensor.…_address_outage` | `on` while DTEK reports an outage for the house: stabilization, emergency or planned works, with its own start and end. Attributes: `reason`, `kind`, `start`, `end`. `unavailable` when DTEK itself can't be reached |
| `calendar.…_outages` | Scheduled outages, possible outages and non-stabilization works reported for the address |
| `event.…_outage_events` | Every event below (`event_type` is the event type, attributes are its data) |

All times are Kyiv time. Sensors switch at the exact moment an outage starts or ends and at midnight, not only on updates.

## Events

Every event is fired on the bus as `dtek_krem_outages_event` with `type`, and on the event entity with the same data.

Every event has `type`, `group` (`GPV3.1`), `group_name` (`3.1`), `settlement`, `street`, `house`, `config_entry_id`, `entry_title`, plus:

| `type` | When | Fields |
|---|---|---|
| `schedule_published` | A day got its schedule for the first time (usually tomorrow, in the evening) | `date`, `day` (`today` / `tomorrow` / `other`), `outages` (`[{start, end}]`), `outages_text`, `outage_minutes`, `possible`, `schedule`, `schedule_updated`, `source` |
| `schedule_changed` | The schedule of a day changed from now on | the same, plus `previous_outages`, `previous_outages_text`, `previous_outage_minutes` |
| `outage_warning` | N minutes before a scheduled outage, or at once if a new outage starts sooner | `start`, `end`, `duration_minutes`, `minutes` (left) |
| `outage_started` | A scheduled outage starts | `start`, `end`, `duration_minutes` |
| `outage_ended` | A scheduled outage ends | `start`, `end`, `duration_minutes`, `next_start`, `next_end` |
| `address_outage` | DTEK reports an outage for the house, changes its end, or clears it | `status` (`new` / `updated` / `cleared`), `reason`, `kind` (`stabilization` / `emergency` / `planned` / `other`), `start`, `end`, `previous_end` |
| `group_changed` | DTEK moved the house to another group | `previous_group`, `previous_group_name` |

Rules:

- **First run**: the current state is recorded silently, no schedule events.
- **Changes in the past only** (DTEK rewrites a finished half-hour) fire nothing.
- **After a restart**, changes published while Home Assistant was down are announced. Events wait until Home Assistant has started, so automations receive them.
- `outage_started` / `outage_ended` are not fired for an edge that passed while Home Assistant was down. A warning is not repeated after a restart.

## Services

| Service | Description |
|---|---|
| `dtek_krem_outages.refresh` | Update now. `config_entry_id` is optional; fails when no source answered |
| `dtek_krem_outages.get_schedule` | Returns `{entries: [{group, days: {date: {outages, outages_text, outage_minutes, possible, schedule}}, weekly, address_outage, source, ...}]}` |

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

```yaml
alias: "Outage soon → phone"
triggers:
  - trigger: event
    event_type: dtek_krem_outages_event
    event_data:
      type: outage_warning
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

  <sub>Data: DTEK KREM, updated {{ as_timestamp(states('sensor.home_schedule_updated')) | timestamp_custom('%d.%m %H:%M') }}</sub>
```

For a week view, use the standard **Calendar** card with `calendar.home_outages`.

## Diagnostics

**Devices & services → DTEK KREM Outages → ⋮ → Download diagnostics**. The street and house number are redacted; the settlement, group and schedule stay.

## Known limitations

- The integration depends on the DTEK website. If DTEK changes the endpoint or puts it behind the anti-bot challenge too, the schedule still comes from the mirror, but the address data (group detection, `address_outage`) stops until the integration is updated.
- The mirror updates about every 5 minutes and can lag behind DTEK.
- The schedule has half-hour precision, like on the DTEK website. On DST change days the missing or repeated hour follows the wall clock.
- Only DTEK KREM (Kyiv region). Kyiv city is served by DTEK KEM / Yasno, which this integration does not cover.

## Attribution

Outage data is provided by DTEK Kyiv Regional Electric Networks; every entity carries the attribution `Data provided by DTEK Kyiv Regional Electric Networks`. The backup copy comes from [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua).

## Releases

The `Tag & Release` workflow runs on every push to `main` and reads `version` from `custom_components/dtek_krem_outages/manifest.json`, the only place the version is kept. It first runs the tests, hassfest and HACS validation; if they pass and the tag or GitHub release for that version doesn't exist yet, it creates whichever is missing, and HACS offers that release as an update. The release notes are the version's section in `CHANGELOG.md`. To publish a release:

1. Bump `version` in `manifest.json`.
2. Add a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md` (a test checks it exists).
3. Push to `main`.

## License

[MIT](LICENSE)
