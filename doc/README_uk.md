<img src="https://raw.githubusercontent.com/NetZhizni/ha-dtek-krem-outages/main/custom_components/dtek_krem_outages/brand/icon.png" alt="DTEK KREM Outages" width="96" align="right">

# DTEK KREM Outages

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/validate.yml/badge.svg)](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/validate.yml)
[![Tests](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/tests.yml/badge.svg)](https://github.com/NetZhizni/ha-dtek-krem-outages/actions/workflows/tests.yml)

[English](../README.md) | **Українська**

Інтеграція Home Assistant для графіків відключень [ДТЕК Київські регіональні електромережі](https://www.dtek-krem.com.ua/ua/shutdowns) (ДТЕК КРЕМ, Київська область): ваша черга, графік на сьогодні й завтра, відключення, які ДТЕК вказує для вашої адреси, і події, коли графік змінюється або відключення ось-ось почнеться.

> Data provided by [DTEK KREM](https://www.dtek-krem.com.ua/ua/shutdowns). Проєкт не пов'язаний з ДТЕК.

## Що це

Ви обираєте населений пункт, вулицю й будинок так само, як на сайті ДТЕК. Інтеграція визначає вашу чергу, раз на кілька хвилин опитує ДТЕК і створює пристрій із сенсорами, календарем і event-сутністю. Налаштовується тільки через UI.

Графік змінюють часто, іноді кілька разів на день. Тому інтеграція:

- **зберігає поточний стан** у сховищі Home Assistant: графік по днях, його версію від ДТЕК, тижневий графік можливих відключень і відключення за адресою. Перезапуск або недоступність обох джерел (звична річ під час блекаутів) не губить графік: сутності працюють на збереженому;
- **застосовує нову версію лише до майбутнього**: півгодини, що вже минули, лишаються такими, як діяли; поточні й наступні беруть нові значення. Дні, яких ДТЕК не показує (завтра до публікації), зберігаються;
- **повідомляє про зміни**: `schedule_published` (з'явився графік на новий день, зазвичай на завтра) і `schedule_changed` (змінився залишок дня), з новими й попередніми відключеннями;
- **попереджає про відключення**: `outage_warning` перед початком відключення за графіком і `outage_end_warning` перед його кінцем (поверненням світла), у позначені вами моменти (наприклад, за 30 і за 5 хвилин); `outage_started` і `outage_ended` точно в момент, не чекаючи наступного опитування.

## Звідки дані

| Джерело | Що | Коли |
|---|---|---|
| [dtek-krem.com.ua](https://www.dtek-krem.com.ua/ua/shutdowns) | Будинки вашої вулиці з чергою й поточним відключенням, фактичний графік (`fact`) і тижневий (`preset`) | Кожне оновлення |
| [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua) (публічне дзеркало тих самих `fact`/`preset`, оновлюється приблизно раз на 5 хв) | Лише графік, без даних адреси | Тільки коли ДТЕК недоступний, і тільки якщо версія новіша |

Сторінки ДТЕК закриті JavaScript-перевіркою від ботів, але ендпоінт, з якого сторінка відключень бере дані (`POST /ua/ajax`), — ні. Інтеграція звертається до нього так само, як сторінка, з CSRF-токеном сайту, одним запитом на запис за оновлення й чесним User-Agent. Вона надсилає версію, яку вже має, і ДТЕК додає графік лише коли є новіший, тож більшість відповідей важать кілька кілобайт.

## Встановлення

> Вимоги до версії Home Assistant:
>
> - Core $\geq$ 2025.8

### Спосіб 1: [HACS](https://hacs.xyz/) (рекомендовано)

[![Відкрити репозиторій DTEK KREM Outages у HACS вашого Home Assistant.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=NetZhizni&repository=ha-dtek-krem-outages&category=integration)

Або додайте репозиторій вручну:

1. HACS → ⋮ → **Custom repositories** → додайте `https://github.com/NetZhizni/ha-dtek-krem-outages` з типом **Integration**.
2. У пошуку HACS введіть **DTEK KREM Outages** → відкрийте → **Download**.
3. Перезапустіть Home Assistant.

### Спосіб 2: Git clone з GitHub

```bash
cd /config
git clone https://github.com/NetZhizni/ha-dtek-krem-outages.git
mkdir -p custom_components
cp -r ha-dtek-krem-outages/custom_components/dtek_krem_outages custom_components/
```

Після цього перезапустіть Home Assistant. Щоб пізніше перейти на реліз, виконайте в клоні `git fetch --tags && git checkout <версія>` і скопіюйте теку ще раз.

### Спосіб 3: Вручну через [Samba](https://github.com/home-assistant/addons/tree/master/samba) / [FTPS](https://github.com/hassio-addons/addon-ftp)

1. Завантажте останній реліз з [Releases](https://github.com/NetZhizni/ha-dtek-krem-outages/releases).
2. Скопіюйте `custom_components/dtek_krem_outages` у `config/custom_components`.
3. Перезапустіть Home Assistant.

## Налаштування

[![Відкрити Home Assistant і почати налаштування DTEK KREM Outages.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dtek_krem_outages)

**Налаштування → Пристрої та служби → Додати інтеграцію → DTEK KREM Outages**, далі:

1. **Населений пункт**: почніть вводити, наприклад `Бориспіль`. Список той самий, що в ДТЕК (близько 1200 населених пунктів).
2. **Вулиця**: для сіл без назв вулиць є `Без вулиці`. Деякі населені пункти ДТЕК записав у кількох написаннях (`с. Софіївська Борщагівка` і `Софіївська Борщагівка`); показуються вулиці всіх, вулиці іншого написання — з ним у дужках, тож неважливо, яке ви обрали.
3. **Будинок**: як у списку ДТЕК (`43`, `8 а`, `1/2`, ...). За бажанням дайте запису коротку **Назву**, наприклад `Home`: з неї будуються ID сутностей (`sensor.home_next_outage`). Приклади нижче використовують саме таку назву. **Мова назв сутностей**: українська (за замовчуванням), англійська або російська, див. параметри нижче.
4. **Черга**: питається лише тоді, коли ДТЕК не вказує для будинку жодної черги або вказує кілька. Інакше черга визначається сама, а якщо ДТЕК згодом переведе будинок в іншу чергу, запис піде за нею (подія `group_changed`). Чергу, обрану вами вручну, інтеграція не змінює.

Кожну адресу можна додати один раз; для кількох адрес додайте кілька записів. **⋮ → Переналаштувати** змінює адресу або чергу.

### Параметри

| Параметр | За замовчуванням | Опис |
|---|---|---|
| Інтервал оновлення | 5 хв | Хвилин між запитами до ДТЕК, щонайменше 2 |
| Попереджати перед початком відключення | 30 хв | Чекбокси (1, 5, 10, 15, 30, 60, 120 хв): коли надсилати `outage_warning`, по одній події на кожен позначений час; нічого не позначено: вимкнено |
| Попереджати перед закінченням відключення (поверненням світла) | немає | Те саме для `outage_end_warning` |
| Використовувати запасне джерело | увімк. | Брати графік з дзеркала, коли ДТЕК недоступний |
| Показувати можливі відключення в календарі | увімк. | Заповнювати наступні 7 днів без фактичного графіка тижневим графіком можливих відключень |
| Мова назв сутностей | Українська | Мова назв сутностей і подій календаря (українська, англійська чи російська) незалежно від мови Home Assistant. ID сутностей лишаються англійськими |

Після збереження запис перезавантажується сам.

## Сутності

Кожен запис створює один пристрій:

| Сутність | Стан |
|---|---|
| `sensor.…_group` | Черга, наприклад `3.1`. Атрибути: `group_id` (`GPV3.1`), `groups_at_address`, `manual`, адреса |
| `sensor.…_next_outage` | Початок наступного відключення за графіком (мітка часу). Атрибути: `end`, `duration_minutes` |
| `sensor.…_outage_end` | Кінець поточного відключення; `unknown`, якщо його немає |
| `sensor.…_outages_today` | Тривалість відключень за графіком сьогодні, години. Атрибути: `outages_text` (`12:00–14:00, 18:00–20:30`), `outages`, `possible_text`, `schedule`, `published` |
| `sensor.…_outages_tomorrow` | Те саме на завтра; `unknown`, поки ДТЕК не опублікує |
| `sensor.…_schedule_updated` | Коли ДТЕК востаннє змінив графік. Атрибути: `version`, `source` (`dtek` / `mirror` / `storage`) |
| `sensor.…_last_update` | Коли востаннє відповіло хоч одне джерело (діагностична). Атрибут: `last_error` |
| `binary_sensor.…_scheduled_outage` | `on` (показується як *Проблема*) під час відключення за графіком. Атрибути: `start`, `end`, `next_start`, `next_end` |
| `binary_sensor.…_address_outage` | `on` (показується як *Проблема*), поки ДТЕК вказує відключення для будинку: стабілізаційне, аварійне чи планові роботи, зі своїми початком і кінцем. Атрибути: `reason`, `kind`, `start`, `end`. `unavailable`, коли недоступний сам ДТЕК |
| `calendar.…_outages` | Відключення за графіком, можливі відключення й нестабілізаційні роботи за адресою |
| `event.…_outage_events` | Усі події нижче (`event_type` — тип події, атрибути — її дані) |

Увесь час — київський. Сенсори перемикаються точно в момент початку й кінця відключення та опівночі, а не лише при оновленнях.

## Події

Кожна подія надсилається на шину як `dtek_krem_outages_event` з полем `type` і в event-сутність з тими самими даними.

У кожній події є `type`, `group` (`GPV3.1`), `group_name` (`3.1`), `settlement`, `street`, `house`, `config_entry_id`, `entry_title`, а також:

| `type` | Коли | Поля |
|---|---|---|
| `schedule_published` | День уперше отримав графік (зазвичай завтрашній, увечері) | `date`, `day` (`today` / `tomorrow` / `other`), `outages` (`[{start, end}]`), `outages_text`, `outage_minutes`, `possible`, `schedule`, `schedule_updated`, `source` |
| `schedule_changed` | Графік дня змінився від поточного моменту | те саме, плюс `previous_outages`, `previous_outages_text`, `previous_outage_minutes` |
| `outage_warning` | За N хвилин до початку відключення за графіком, по разу на кожен позначений час, або одразу (однією подією), якщо нове відключення почнеться раніше | `start`, `end`, `duration_minutes`, `minutes` (залишилось) |
| `outage_end_warning` | За N хвилин до закінчення відключення за графіком, коли повернеться світло, по разу на кожен позначений час (не для часу, довшого за саме відключення) | `start`, `end`, `duration_minutes`, `minutes` (залишилось) |
| `outage_started` | Почалося відключення за графіком | `start`, `end`, `duration_minutes` |
| `outage_ended` | Закінчилося відключення за графіком | `start`, `end`, `duration_minutes`, `next_start`, `next_end` |
| `address_outage` | ДТЕК вказав відключення для будинку, змінив його кінець або зняв його | `status` (`new` / `updated` / `cleared`), `reason`, `kind` (`stabilization` / `emergency` / `planned` / `other`), `start`, `end`, `previous_end` |
| `group_changed` | ДТЕК перевів будинок в іншу чергу | `previous_group`, `previous_group_name` |

Правила:

- **Перший запуск**: поточний стан записується мовчки, без подій про графік.
- **Зміни лише в минулому** (ДТЕК переписав півгодини, що вже минули) не породжують подій.
- **Після перезапуску** зміни, опубліковані, поки Home Assistant не працював, приходять як події. Події чекають повного запуску Home Assistant, щоб їх отримали автоматизації.
- `outage_started` / `outage_ended` не надсилаються для моментів, що минули, поки Home Assistant не працював. Попередження після перезапуску не повторюється. Якщо інтеграція прокинулась із запізненням і всередині кількох позначених часів одразу, вона надсилає одну подію, а не по одній на кожен час.

## Сервіси

| Сервіс | Опис |
|---|---|
| `dtek_krem_outages.refresh` | Оновити зараз. `config_entry_id` необов'язковий; помилка, якщо не відповіло жодне джерело |
| `dtek_krem_outages.get_schedule` | Повертає `{entries: [{group, days: {дата: {outages, outages_text, outage_minutes, possible, schedule}}, weekly, address_outage, source, ...}]}` |

## Приклади

### Новий або змінений графік → Telegram

```yaml
alias: "Графік відключень → Telegram"
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
        {{ '🆕 Графік на' if trigger.event.data.type == 'schedule_published'
           else '✏️ Змінено графік на' }}
        {{ {'today': 'сьогодні', 'tomorrow': 'завтра'}.get(trigger.event.data.day,
           trigger.event.data.date) }}
        (черга {{ trigger.event.data.group_name }}):
        {{ trigger.event.data.outages_text or 'без відключень' }}
        {%- if trigger.event.data.previous_outages_text is defined %}
        (було: {{ trigger.event.data.previous_outages_text or 'без відключень' }})
        {%- endif %}
mode: queued
```

### Попередження на телефон

Позначте часи в параметрах (наприклад, за 30 і за 5 хвилин до початку); `minutes` показує, який із них спрацював. Так само працює `type: outage_end_warning` для повернення світла.

```yaml
alias: "Скоро відключення → телефон"
triggers:
  - trigger: event
    event_type: dtek_krem_outages_event
    event_data:
      type: outage_warning
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "⚡ Відключення через {{ trigger.event.data.minutes }} хв"
      message: >-
        {{ as_timestamp(trigger.event.data.start) | timestamp_custom('%H:%M') }}–{{
           as_timestamp(trigger.event.data.end) | timestamp_custom('%H:%M') }}
mode: queued
```

### Аварійні роботи за адресою

```yaml
alias: "Аварійне відключення вдома"
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
        До {{ as_timestamp(trigger.event.data.end) | timestamp_custom('%d.%m %H:%M')
              if trigger.event.data.end else 'невідомо' }}
mode: queued
```

Замість події на шині можна використати event-сутність; дані тоді в `trigger.to_state.attributes`:

```yaml
triggers:
  - trigger: state
    entity_id: event.home_outage_events
    attribute: event_type
    to: outage_warning
```

### Картка Lovelace

```yaml
type: markdown
content: |
  **Черга {{ states('sensor.home_group') }}**

  Сьогодні: {{ state_attr('sensor.home_outages_today', 'outages_text') or 'без відключень' }}

  Завтра: {% if state_attr('sensor.home_outages_tomorrow', 'published') -%}
  {{ state_attr('sensor.home_outages_tomorrow', 'outages_text') or 'без відключень' }}
  {%- else %}ще не опубліковано{% endif %}

  {% if is_state('binary_sensor.home_scheduled_outage', 'on') -%}
  ⚫ Світло з'явиться о {{ as_timestamp(states('sensor.home_outage_end')) | timestamp_custom('%H:%M') }}
  {%- elif states('sensor.home_next_outage') not in ['unknown', 'unavailable'] -%}
  🟢 Наступне відключення {{ as_timestamp(states('sensor.home_next_outage')) | timestamp_custom('%d.%m %H:%M') }}
  {%- endif %}

  <sub>Дані: ДТЕК КРЕМ, оновлено {{ as_timestamp(states('sensor.home_schedule_updated')) | timestamp_custom('%d.%m %H:%M') }}</sub>
```

Для перегляду тижня використайте стандартну картку **Календар** з `calendar.home_outages`.

## Діагностика

**Пристрої та служби → DTEK KREM Outages → ⋮ → Завантажити діагностику**. Вулиця й номер будинку приховані; населений пункт, черга й графік лишаються.

## Відомі обмеження

- Інтеграція залежить від сайту ДТЕК. Якщо ДТЕК змінить ендпоінт або теж закриє його перевіркою від ботів, графік і далі прийде з дзеркала, але дані адреси (визначення черги, `address_outage`) зупиняться до оновлення інтеграції.
- Дзеркало оновлюється приблизно раз на 5 хвилин і може відставати від ДТЕК.
- Графік має точність до пів години, як на сайті ДТЕК. У дні переходу на літній/зимовий час пропущена чи повторена година йде за настінним годинником.
- Лише ДТЕК КРЕМ (Київська область). Київ обслуговує ДТЕК КЕМ / Yasno, цю інтеграцію він не охоплює.

## Атрибуція

Дані про відключення надає ДТЕК Київські регіональні електромережі; кожна сутність має атрибуцію `Data provided by DTEK Kyiv Regional Electric Networks`. Запасна копія — з [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua).

## Релізи

Workflow `Tag & Release` запускається на кожен push у `main` і читає `version` з `custom_components/dtek_krem_outages/manifest.json`, єдиного місця, де живе версія. Спершу він проганяє тести, hassfest і валідацію HACS; якщо вони пройшли, а тегу чи GitHub-релізу для цієї версії ще немає, створює те, чого бракує, і HACS пропонує реліз як оновлення. Нотатки релізу — це секція версії в `CHANGELOG.md`. Щоб випустити реліз:

1. Підніміть `version` у `manifest.json`.
2. Додайте секцію `## [X.Y.Z] - YYYY-MM-DD` у `CHANGELOG.md` (її наявність перевіряє тест).
3. Зробіть push у `main`.

## Ліцензія

[MIT](../LICENSE)
