# CLAUDE.md

Інструкції для Claude Code в цьому репозиторії.

## Правила роботи

- **Жодних `git commit` і `git push`** (а також тегів, релізів, PR). Комітить і пушить користувач сам. Після змін лише вивести в чаті підсумок і, за потреби, запропонований текст коміт-повідомлення.
- **PATCH-версія піднімається при кожній зміні інтеграції** (`custom_components/dtek_krem_outages/`): `0.1.0` → `0.1.1`.
  - Спершу перевір `git diff HEAD -- custom_components/dtek_krem_outages/manifest.json`. Якщо `version` там уже змінено, але не закомічено, версію **не чіпати**: усі незакомічені зміни йдуть в одну версію.
  - Версія живе лише в `custom_components/dtek_krem_outages/manifest.json` → `"version"`. Код читає її під час роботи (`async_get_integration`), окремої константи `VERSION` немає й не додавати.
  - Разом з версією додати секцію `## [X.Y.Z] - YYYY-MM-DD` в `CHANGELOG.md` (формат Keep a Changelog). Якщо секція для поточної незакоміченої версії вже є, дописувати в неї. Її наявність перевіряє `tests/test_manifest.py`, а `release.yml` бере з неї нотатки релізу.
  - MINOR/MAJOR піднімати лише на прохання користувача.

## Про проєкт

**DTEK KREM Outages** — кастомна інтеграція Home Assistant (HACS) для графіків відключень ДТЕК Київські регіональні електромережі (https://www.dtek-krem.com.ua/ua/shutdowns). Домен `dtek_krem_outages`, `iot_class: cloud_polling`, без зовнішніх `requirements`. Мінімальна версія HA — `2025.8.0` (`hacs.json`). Репозиторій: `NetZhizni/ha-dtek-krem-outages`.

## Структура

```
custom_components/dtek_krem_outages/
  __init__.py        setup/unload/remove запису; сервіси реєструються один раз в async_setup
  api.py             DtekClient (aiohttp, CSRF Yii2, getStreets/getHomeNum, дзеркало), Fact/Preset/House/AddressOutage
  schedule.py        чиста логіка: 48 півгодинних слотів на день, інтервали, злиття, виявлення змін
  coordinator.py     DataUpdateCoordinator: ДТЕК → дзеркало, злиття зі Store, події, таймери
  config_flow.py     user (нас. пункт) → street → house → group; reconfigure; OptionsFlowWithReload
  entity.py          базовий DtekEntity
  sensor.py          група, наступне відключення, кінець поточного, години сьогодні/завтра, оновлення
  binary_sensor.py   відключення за графіком, відключення за адресою
  calendar.py        фактичні, можливі (тижневий графік) і адресні відключення
  event.py           event-сутність з усіма типами подій
  services.py        refresh, get_schedule (з response)
  diagnostics.py     діагностика (вулиця й будинок приховані)
  const.py           усі константи, дефолти опцій
  strings.json, translations/en.json, translations/uk.json
  services.yaml, icons.json, manifest.json
  brand/             icon.png, icon@2x.png (HA роздає їх локально)
tests/               pytest + pytest-homeassistant-custom-component; FakeDtek у conftest.py,
                     реальні відповіді в fixtures/ (home_num.json, streets.json, mirror.json)
.github/workflows/   tests.yml (ruff + pytest), validate.yml (hassfest + HACS), release.yml (тег і реліз)
```

## Ключова логіка

- **Доступ до ДТЕК.** Сторінки сайту закриті JS-челенджем Incapsula, але `POST /ua/ajax` — ні: ним користується сама сторінка. Перший POST без токена дає HTTP 400 і кукі `_csrf-dtek-krem` (Yii2: підписане, не зашифроване, всередині серіалізований токен). Заголовок `X-CSRF-Token` = `base64url(mask + (mask XOR token))`. Обходити Incapsula чи імітувати браузер не можна: User-Agent чесний. Перевірені факти — у докстрінгу `api.py`.
- **Версія графіка.** `getHomeNum` повертає `fact`/`preset` лише якщо `updateFact` «істинний» у PHP (не `""` і не `"0"`) і відрізняється від поточного `fact.update`. Координатор шле збережену версію, а `FORCE_UPDATE_FACT` — коли графіка ще немає або змінилась черга.
- **Злиття.** День — рядок з 48 символів (`1` світло, `0` відключення, `?` можливе). `merge_days`: минулі дні й завершені слоти сьогодні не змінюються, поточний і наступні беруть нові значення, дні, яких немає в новій відповіді, лишаються. Події — лише для змін від поточного слота (`future_changes`). Межі інтервалів — в UTC (порівняння datetime з однаковим tzinfo йде за настінним часом і ламається на DST), у вивід — київський час.
- **Стан.** `Store` (`storage_key(entry_id)`) містить адресу, чергу, версію, дні (історія 7 днів), тижневий графік, адресне відключення, видані попередження. Store іншої адреси ігнорується; іншої черги — лишається лише історія. Без жодного джерела координатор працює на збереженому і не кидає `UpdateFailed`, якщо базовий стан уже є.
- **Джерела.** Основне — ДТЕК; дзеркало `Baskerville42/outage-data-ua` — лише коли ДТЕК не відповів і лише якщо його версія новіша.
- **Події.** Одна подія на шині `dtek_krem_outages_event` з полем `type` + event-сутність (dispatcher). Перший запуск мовчить. Події відкладаються до `homeassistant_started`. Таймер координатора прокидається на межах відключень, за `warning_minutes` до них, на межах адресного відключення й опівночі.
- **Черга.** Якщо ДТЕК вказує для будинку рівно одну іншу чергу і `group_manual` = False, запис переходить на неї (`group_changed`, `async_update_entry`).
- **Атрибуція.** Кожна сутність має `Data provided by DTEK Kyiv Regional Electric Networks` — не прибирати.

## Команди

```bash
pip install -r requirements_test.txt   # pytest-homeassistant-custom-component, ruff
ruff check .
ruff format --check .
pytest -q
```

CI використовує Python 3.14; `ruff` налаштований на `py313` (`pyproject.toml`). Правила `RUF001`–`RUF003` вимкнені: дані ДТЕК українською, кирилиця в рядках навмисна.

## Конвенції

- Код, коментарі, докстрінги та логи — англійською. Докстрінги у стилі Google (ruff `D`), рядок 88, `from __future__ import annotations` у кожному модулі.
- Константи тільки в `const.py` з `Final`.
- Тексти UI: `strings.json` і `translations/en.json` мають бути ідентичними; `translations/uk.json` оновлювати разом з ними (це перевіряє `tests/test_manifest.py`). Помилки — через `translation_key`. Тексти календаря — `CALENDAR_TEXT` у `const.py` за мовою HA.
- README розділений за мовами: `README.md` — англійська (за замовчуванням, її показує HACS), `doc/README_uk.md` — українська. Обидва повні, з однаковою структурою й прикладами YAML; зміни поведінки відображати в обох. Посилання на українську версію в `README.md` — абсолютне (GitHub URL), бо HACS не розв'язує відносні шляхи.
- Нова функціональність — з тестами в `tests/`. Запити до ДТЕК у тестах ідуть через `FakeDtek` (перевіряє справжній CSRF і семантику `updateFact`).

## Релізи

`release.yml` спрацьовує на кожен push у `main` (і вручну): спершу через `workflow_call` проганяє `tests.yml` і `validate.yml`, потім бере `version` з `manifest.json` і створює тег та/або GitHub Release (нотатки з секції `CHANGELOG.md`), якщо їх ще немає, тож упалий запуск повторюється наступним пушем. HACS після цього пропонує оновлення. Тобто підняття версії = реліз після пушу користувачем.
