# Як долучитися

**Українська** | [English](#contributing)

Дякуємо, що хочете допомогти! Найкорисніше, що можна зробити:

- **Повідомити про помилку** через [шаблони issue](https://github.com/NetZhizni/ha-dtek-krem-outages/issues/new/choose). Для проблем з адресою чи чергою є окремий шаблон.
- **Поставити питання чи поділитися** автоматизацією або карткою в [Discussions](https://github.com/NetZhizni/ha-dtek-krem-outages/discussions).
- **Запропонувати зміну** через pull request.

## Розробка

```bash
pip install -r requirements_test.txt   # pytest-homeassistant-custom-component, ruff
ruff check .
ruff format --check .
pytest -q
```

Правила:

- Код, коментарі, докстрінги й логи — англійською, докстрінги у стилі Google, рядок до 88 символів, `from __future__ import annotations` у кожному модулі. Константи — лише в `const.py`.
- Нова поведінка — з тестами в `tests/`. Запити до ДТЕК у тестах ідуть через `FakeDtek` з `tests/conftest.py`, а не в мережу.
- Тексти UI: `strings.json` і `translations/en.json` однакові, `translations/uk.json` і `translations/ru.json` оновлюються разом з ними (це перевіряє тест).
- Зміни поведінки описуються в обох README: `README.md` (українська) і `doc/README_en.md` (англійська).
- Зміна в `custom_components/dtek_krem_outages/` піднімає PATCH-версію в `manifest.json` і додає секцію `## [X.Y.Z] - YYYY-MM-DD` у `CHANGELOG.md`.
- Інтеграція звертається до ДТЕК так само, як сторінка сайту, з чесним User-Agent. Зміни, що обходять перевірку від ботів чи імітують браузер, не приймаються.

---

# Contributing

[Українська](#як-долучитися) | **English**

Thanks for helping! The most useful things are:

- **Report a bug** using the [issue templates](https://github.com/NetZhizni/ha-dtek-krem-outages/issues/new/choose). Address and group problems have their own template.
- **Ask a question or share** an automation or dashboard in [Discussions](https://github.com/NetZhizni/ha-dtek-krem-outages/discussions).
- **Propose a change** with a pull request.

## Development

```bash
pip install -r requirements_test.txt   # pytest-homeassistant-custom-component, ruff
ruff check .
ruff format --check .
pytest -q
```

Rules:

- Code, comments, docstrings and logs are in English: Google-style docstrings, 88-character lines, `from __future__ import annotations` in every module. Constants live only in `const.py`.
- New behaviour comes with tests in `tests/`. DTEK requests in tests go through `FakeDtek` in `tests/conftest.py`, never to the network.
- UI texts: `strings.json` and `translations/en.json` are identical, and `translations/uk.json` and `translations/ru.json` are updated with them (a test checks this).
- Behaviour changes are documented in both READMEs: `README.md` (Ukrainian) and `doc/README_en.md` (English).
- A change in `custom_components/dtek_krem_outages/` bumps the PATCH version in `manifest.json` and adds a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md`.
- The integration talks to DTEK the way the site's own page does, with an honest User-Agent. Changes that bypass the bot check or imitate a browser are not accepted.
