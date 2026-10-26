# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

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
