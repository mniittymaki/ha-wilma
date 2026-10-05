# Home Assistant · Wilma

Unofficial Home Assistant integration for [Visma Wilma](https://www.wilma.fi/).

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mniittymaki&repository=ha-wilma&category=integration)

Current version: **1.2.15**.

It logs in with a **guardian** username and password, keeps one browser-like session, and polls school pages. There is no Visma developer API key.

Default tenant in the config flow is Helsinki: `https://helsinki.inschool.fi`.

Confirmed working: Helsinki, Kaarina, Espoo. Other `*.inschool.fi` tenants use the same flow. Attendance-table and week-schedule parsing was checked against Vantaa's page shape. Password login only; Hollola is a known login miss (issue #6).

> Not affiliated with Visma or Wilma.

## Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mniittymaki&repository=ha-wilma&category=integration)

The button adds this repository to HACS (Integration). Then install **Wilma** and restart.

Manual: copy `custom_components/wilma` to `/config/custom_components/wilma` and restart. Minimum Home Assistant 2024.1.0.

## What you get

One entry per guardian account, one device per child.

Account: Lukemattomat, Viestit, Viimeisin viesti.

Per child: Oppilas, Tänään, Seuraava tunti, Kalenteri, Aktiiviset / Menneet / Kaikki läksyt, Seuraava koe, Arvosanat, Tiedote, Kurssit, Uudet viestit, Poissaolot, Myöhästymiset, Kehut, Moitteet, Selvittämättömät tuntimerkinnät, Kaikki tuntimerkinnät, Viimeisin tuntimerkintä.

`Uudet viestit` has `messages` (with ids) and `pinned`. Kehut and Moitteet have `notes` as objects. `Seuraava tunti` attributes stay weekly slots; `schedule` has dates per period.

## Actions

`wilma.get_message` fetches one body on demand and returns `id`, `subject`, `sender`, `timestamp`, `content`, `replies`. Wilma marks it read, so bodies are never polled.

```yaml
action: wilma.get_message
data:
  entity_id: sensor.aino_esimerkki_uudet_viestit
  message_id: 1234567
response_variable: message
```

`wilma.pin_message` and `wilma.unpin_message` take the same target and `message_id`. Pins are stored per child.

## Lesson notes

`attendance/view` is a table. Date comes from the row, the event from `title="20UEEL03; Hyvä!; Hyvin sujunut oppitunti. /Katju Pitkänen"`. Kind, course code, text and teacher are split. `Tiedoksi` is kept. Header `Tuntimerkinnät` is not a note. Token scrape remains a fallback.

Kehut / Moitteet use the type name first. A doctor's visit counts as an absence.

## Schedule

Overview `DateArray` stops about 12 days ahead. 1.2.15 fetches `/{id}/schedule?date=DD.MM.YYYY` for this week and the next four and reads `eventsJSON`.

A loaded week replaces overview slots. An empty week stays empty. A failed page keeps overview slots and is recorded as a probe (`schedule?date=05.10.2026 200 lessons=21`). Subject is the group code plus qualifier (`20SUK SUPER`, `20KS.a`). Teacher is the staff on the lesson (`Pitkänen Katju (KAKA)`). Room is `Huoneet`.

## Homework

Due date is the next lesson of that subject after the assigned date. `Englanti, A1` matches `ENA1`, `Suomen kieli ja kirjallisuus` matches `SUK`. `hw_*` ends with a match hint.

## Session

One login per username. Last good school payload is kept on failure. Relogin on collision or a dead overview. Add the account once; children come from roles.

## Changelog

| Version | Notes |
|---|---|
| 1.2.15 | Five schedule weeks from `schedule?date=` |
| 1.2.14 | Message body, pins, `notes`, dated `schedule`, doctor's visit as absence |
| 1.2.11 | Attendance table rows |
| 1.2.10 | Moitteet |
| 1.2.9 | Hyve captions count as Kehut |
| 1.2.7 | Homework due after the assigned date |
| 1.2.6 | Code to name matching, calendar crash fixes |
| 1.2.5 | Auto-messages without `sender_id` |
| 1.2.4 | Aktiiviset / Menneet / Kaikki läksyt |
| 1.2.3 | Only overview 401/403 is a dead session |
| 1.2.2 | Keep last data, drop unnamed guardian child |

## License

MIT. Login uses [Wilhelmina](https://github.com/frwickst/pywilma).
