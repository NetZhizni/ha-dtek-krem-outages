# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-31

Two changes break what worked before: the main group no longer changes by itself (Repairs offers the change instead), and the `last_verified_at` attribute is gone.

### Added
- Repairs: when DTEK lists other groups for the house without the main group of the entry in three answers in a row (about 15 min with a 5 min interval; answers during a stabilization outage don't count), the repair "DTEK lists other groups for …" offers to change the main group to one of them. Its fix flow keeps the past schedule, asks for the whole schedule of the new group at once and fires `group_changed`; the group then counts as chosen by you. The repair goes away by itself once DTEK lists the main group again, and it can be ignored to keep your group. Groups left out in the options are not offered. The answers counted are stored, so the repair is back right after a restart.

### Changed
- **Breaking:** the main group no longer moves by itself, whether you chose it or it was detected; Repairs offers the change instead. In 0.1.7 a main group detected automatically moved to the group DTEK listed alone in three answers in a row, and stayed there when its own group was listed again.
- Diagnostics: `main_missing` (answers in a row without the main group) and `group_suggestions` (the groups Repairs offers) instead of `main_candidate`.
- README (Ukrainian and English): a section on changing the main group in Repairs, also in the configuration steps, the events, the known limitations and the troubleshooting table; the state of `sensor.…_last_update` instead of `last_verified_at`.

### Removed
- **Breaking:** the `last_verified_at` attribute of the entities computed from the schedule (`sensor.…_groups_status`, `…_next_outage`, `…_outage_end`, `…_outages_today`, `…_outages_tomorrow`, `binary_sensor.…_scheduled_outage` and both calendars). It changed with every update, so every update wrote these entities again: a state change each time, and `state` triggers without `to:` firing every few minutes (0.1.7 only kept it out of the recorder). The same time is the state of `sensor.…_last_update` and the `last_success` attribute of `sensor.…_dtek_connection`; `data_status` stays.

## [0.1.7] - 2026-10-31

### Added
- `power` in the `today` / `tomorrow` runs of `sensor.…_groups_status`: `on`, `off` or `maybe` by the schedule the entities follow, so by the "Other groups of the address in the schedule" option; `null` when that schedule has no such day.
- Config flow: when DTEK reports a stabilization outage for the house and lists its group alone, the group step offers every group with that one chosen. Keeping it leaves the group to DTEK as before; another one counts as chosen by you and is never replaced.
- Diagnostics show the counters of the groups (answers in a row without a group, answers listing only another group), whether the whole schedule is asked for, and the past of the other groups.
- CI runs the tests on the oldest Home Assistant supported, 2025.8.0, too (`requirements_test_min.txt`).

### Fixed
- The other groups of the house were dropped while DTEK reported a stabilization outage for it, and came back when it ended, each time with a `groups_changed` event both ways: during such an outage DTEK lists only the group of that outage. While it lasts, no group is dropped now, one already missing from the answers before included, and the main group doesn't move; a group DTEK adds is still taken. Emergency outages and planned works don't shorten the group list.
- A main group detected automatically moved to another group after a single answer that listed only that group, e.g. right after a stabilization outage of the other group, and stayed there when its own group was listed again. It moves now after three answers in a row (about 15 min with a 5 min interval) and never during a stabilization outage; `group_changed` no longer comes on the first update.
- The past outages of a group DTEK no longer lists vanished from `calendar.…_other_groups`. They stay for 7 days now, like the past schedule of the main group, also after a restart and when the group comes back. A group ticked in "Leave out groups" leaves the calendar with its past, as before.
- An answer of DTEK without the house cleared the outage reported for it, with `address_outage` events `cleared` and then `new` when the house was back. Such an answer changes nothing now, and the address entities are unavailable until DTEK lists the house again.
- An outage at the address whose start DTEK corrected while it was going on was shown twice in the calendar: until the correction and again with the new start. One of the same kind overlapping it is the same outage now, with an `updated` event.
- The entities with `last_verified_at` wrote all their attributes to the recorder again with every update, and so did the connection sensor with `last_success` and `last_dtek_success`. These attributes are no longer recorded.
- The timer of outage edges and warnings could go off between the two requests of an update and work on a half applied answer. It is off from the first answer until the update ends, which evaluates what it would have met.

### Changed
- `refresh` asks DTEK again only a minute after the last update of an entry; a call sooner gives the result of that update.
- The mirror is asked for with `If-None-Match`: an unchanged file is not downloaded again.
- README (Ukrainian and English): the "Schedule by group" card goes by `power`. With the main group alone, or in the default mode, an outage of the main group now reads "no power" instead of "maybe no power"; which groups are off is named only when there are several; while works at the address are going on, the current period says the power is on by the group schedule only; a day the schedule of the entities doesn't have yet reads "not published yet". Both Markdown cards show the times in Kyiv time like the schedule, whatever the time zone of Home Assistant. A note on entity IDs that start with the name of the area for entities added by updates when the device is in an area, also in the troubleshooting table. The rules for the main group and for a stabilization outage, the corrected start of address works, a missing house, `possible_outage_warning` (the schedule of the day, not the weekly one) and `last_verified_at` in the recorder are described, the stabilization outage in the known limitations too.

## [0.1.6] - 2026-10-26

### Added
- Outages DTEK reported for the house stay in the `…_outages` calendar for 7 days after DTEK stops showing them, since DTEK often adds and removes them after the fact. One removed while it was going on ends when DTEK removed it, one removed after its end keeps its end, one called off before it started is not kept, and one DTEK shows again is current again. The history survives restarts.
- `address_history` in the `get_schedule` response and the diagnostics.

### Changed
- README (Ukrainian and English): a section on the address works in the calendar; both Markdown card examples show the emergency, planned or other works reported for the house while they last or when they are ahead.
- README (Ukrainian and English): the integration is in the HACS default list, so the badge says so and installing it no longer needs adding the repository by hand.

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
