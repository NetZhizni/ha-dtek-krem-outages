# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-18

### Added
- Config flow that picks the address like dtek-krem.com.ua does: settlement, street and house from DTEK's lists, with the group detected from the house; a group step when DTEK lists none or several. Reconfigure flow and options flow with automatic reload.
- Client for the DTEK KREM ajax endpoint (`getStreets`, `getHomeNum`) with the site's CSRF token, versioned schedule requests (`updateFact`) and the public mirror `Baskerville42/outage-data-ua` as a backup source.
- Schedule stored in `Store` by day in half-hour slots: finished slots keep what was in effect, the current and later slots follow the newest version, unpublished days are kept; the last known state keeps working while both sources are down.
- Events on the bus (`dtek_krem_outages_event`) and an event entity: `schedule_published`, `schedule_changed`, `outage_warning`, `outage_started`, `outage_ended`, `address_outage`, `group_changed`; deferred until Home Assistant has started.
- Sensors: group, next outage, current outage end, outage hours today and tomorrow, schedule update time, last successful update. Binary sensors for the scheduled outage and the outage DTEK reports for the address, switching at the exact times.
- Calendar with scheduled, possible (weekly schedule) and address outages.
- Services `refresh` and `get_schedule` (response), diagnostics with the street and house redacted, English and Ukrainian translations.
