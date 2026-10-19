## Що змінено / What changed

<!-- Коротко: що й навіщо. Посилання на issue, якщо є: Fixes #123 -->

## Перевірка / Checklist

- [ ] `ruff check .`, `ruff format --check .` і `pytest -q` проходять
- [ ] Нова поведінка покрита тестами в `tests/` (запити до ДТЕК — через `FakeDtek`)
- [ ] Тексти UI: `strings.json` = `translations/en.json`, оновлені `uk.json` і `ru.json`
- [ ] Зміни поведінки описані в `README.md` і `doc/README_en.md`
- [ ] Для змін у `custom_components/dtek_krem_outages/`: піднято PATCH у `manifest.json` і додано секцію в `CHANGELOG.md`
