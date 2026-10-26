# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.5] - 2026-10-22

### Added
- The other groups DTEK lists for the house are followed besides the main group of the entry, each with its own schedule. A group DTEK adds is taken with the next update (after updating to this version, with the first one), with no reconfiguring; a group DTEK no longer lists is dropped after three answers in a row without it. A missing house, an empty group list or DTEK being down drop nothing.
- `calendar.…_other_groups`: outages and possible outages of the other groups, each event named with its group.
- "Other groups of the address in the schedule" option: the sensors, events, warnings and the `…_outages` calendar follow the main group only (default), an outage of any group, or an outage of all groups at once with the half-hours when only some are off as possible outages (a group with no schedule for the day yet is not taken as off). Combined, every event of the `…_outages` calendar names the groups off during it. What already happened is not rewritten.
- `possible_outage_warning` event, at the same ticked times as `outage_warning`, before a possible outage that starts while the power is on.
- `groups` field (the groups off at that time) in `outage_warning`, `possible_outage_warning`, `outage_end_warning`, `outage_started` and `outage_ended`.
- "Leave out groups" option (entry with an address) and "Other groups" option (entry without an address). A group taken out of "Leave out groups" is back as soon as the options are saved.
- `sensor.…_groups_status`: which followed groups are off now by their own schedules (`none`, `main`, `main_some`, `main_all`, `others_some`, `others_all`), with `groups_off`, a numeric `level`, and `today` / `tomorrow` with the whole day as runs of one status for charts of the past and the future; it switches at the edges of every group.
- `groups_changed` event with `added`, `removed` and `extra_groups`.
- `groups` attribute of `sensor.…_outages_today` / `…_outages_tomorrow`: the outages of every followed group alone, the main one first.
- `extra_groups` and `groups_mode` (the mode in effect) attributes of `sensor.…_group`; `extra_groups`, `groups_mode` and `groups` (every followed group alone) in the `get_schedule` response.

### Changed
- When the house is missing from the DTEK answer or has no groups, `groups_at_address` keeps the groups known before instead of becoming empty.
- README (Ukrainian and English): a section on several groups at one address with the setup steps and screenshots of the options and the calendar, a history graph of the groups status and a Markdown card with the schedule by group; the known limitations and the comparison updated.

## [0.1.4] - 2026-10-19

### Changed
- `hacs.json` sets `"country": "UA"`: the integration only covers DTEK KREM (Kyiv region), as the HACS default list asks of country-specific repositories.
- The HACS validation runs with no ignored checks: the brands check finds the icon in the integration's `brand/` folder.
- README (Ukrainian and English): screenshots of the dashboard cards, setup, device page and calendar, and a feedback section. Issue forms (bug, address or group, feature request), a pull request checklist and `CONTRIBUTING.md`.

## [0.1.3] - 2026-10-18

### Added
- Entry by group only: when DTEK can't be reached while adding the integration, it offers to try again or to follow a group without an address, with the schedule from the mirror. Reconfigure adds the address later (or switches an address entry to its group while DTEK is down).
- `sensor.…_dtek_connection` (diagnostic): `ok`, `mirror` or `offline`, with the last successes, failures in a row, the current interval, whether DTEK answered with the anti-bot challenge and whether DTEK shows the daily and weekly schedules.
- `sensor.…_address_status` (`none` / `stabilization` / `emergency` / `planned` / `other`) and `sensor.…_estimated_restoration` for the outage DTEK reports for the house.
- `data_status` (`current` / `stale`) and `last_verified_at` attributes on the entities computed from the schedule and on the calendar.
- `external_operator` attribute and a log warning when DTEK says another operator serves the house (`cek`).

### Changed
- The `show*` flags of the DTEK answer are followed like the website follows them. While the weekly schedule is hidden (`showTablePlan: false`, as on 2026-10-18), the calendar doesn't fill days with possible outages. While the schedule of the day is hidden (`showTableFact` / `showTableSchedule`), the days from now on are cleared with a `schedule_changed` event, the mirror copy is not used, and the whole schedule is asked for once it is shown again. Without `showCurOutageParam` the outage of the house is left out.
- After failed requests the update interval doubles up to 15 minutes (or the configured interval if longer), with jitter, and is back to normal after a success.
- README is Ukrainian by default; the English version moved to `doc/README_en.md`. Both have a comparison with groove-max/ha-dtek-monitor and aavdberg/ha-dtek, a troubleshooting table and new examples.

### Fixed
- A house that DTEK lists as several records (one per outage) was dropped and looked missing. Its groups are merged and the most severe outage is reported.
- The house is found when DTEK changes its spelling only in case, spaces or Latin look-alike letters.
- The options did not open (`500 Internal Server Error`, `ValueError: unable to serialize schema` in the log): the warning checkboxes turned the ticked minutes into numbers with a function inside the form schema, which Home Assistant cannot send to the frontend. The options step converts them now.

## [0.1.2] - 2026-10-18

### Fixed
- `Unexpected error while loading the streets` (`RuntimeError: Session is closed`) in the config flow: the shared DTEK client kept using its HTTP session after Home Assistant closed it. The client now creates a new session (and asks for a new CSRF token) when the current one is closed.

## [0.1.1] - 2026-10-18

### Added
- Language of entity names: Ukrainian (default), English or Russian, chosen with the house and changeable in the options. Entity names and calendar texts follow it instead of the Home Assistant language, which is often left English while the interface is Ukrainian. Entity IDs are still English (`sensor.home_next_outage`). Existing entries switch to Ukrainian names.
- Russian translation of the config and options flows, entities, services and errors.

- Warnings before an outage starts and before it ends (power returns) are checkboxes in the options now (1, 5, 10, 15, 30, 60, 120 minutes), e.g. 30 and 5 together. The new event `outage_end_warning` fires before an outage ends; `outage_warning` fires once for each ticked time (one event when a new outage starts sooner than several of them). The old single number is read as the "before start" time, so existing entries keep their 30 minutes.

### Changed
- The two outage binary sensors have the `problem` device class: `on` (an outage) shows as *Problem* and `off` as *OK* instead of *On* / *Off*, which read as the power being on.

### Fixed
- Street step: DTEK lists some places under several keys (e.g. `с. Софіївська Борщагівка` with all its streets and `Софіївська Борщагівка` with only `Без вулиці`). The streets of every key with the same name are offered now, labelled with their settlement, and the entry keeps the key that owns the chosen street.
- A typed street or settlement matches without its prefix (`миру` → `вул. Миру`, `Бориспіль` → `м. Бориспіль`) when that is unambiguous.

## [0.1.0] - 2026-10-18

### Added
- Config flow that picks the address like dtek-krem.com.ua does: settlement, street and house from DTEK's lists, with the group detected from the house; a group step when DTEK lists none or several. Reconfigure flow and options flow with automatic reload.
- Client for the DTEK KREM ajax endpoint (`getStreets`, `getHomeNum`) with the site's CSRF token, versioned schedule requests (`updateFact`) and the public mirror `Baskerville42/outage-data-ua` as a backup source.
- Schedule stored in `Store` by day in half-hour slots: finished slots keep what was in effect, the current and later slots follow the newest version, unpublished days are kept; the last known state keeps working while both sources are down.
- Events on the bus (`dtek_krem_outages_event`) and an event entity: `schedule_published`, `schedule_changed`, `outage_warning`, `outage_started`, `outage_ended`, `address_outage`, `group_changed`; deferred until Home Assistant has started.
- Sensors: group, next outage, current outage end, outage hours today and tomorrow, schedule update time, last successful update. Binary sensors for the scheduled outage and the outage DTEK reports for the address, switching at the exact times.
- Calendar with scheduled, possible (weekly schedule) and address outages.
- Services `refresh` and `get_schedule` (response), diagnostics with the street and house redacted, English and Ukrainian translations.
