# Home Assistant · Wilma

Unofficial Home Assistant integration for [Visma Wilma](https://www.wilma.fi/).

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mniittymaki&repository=ha-wilma&category=integration)

Current version: **1.2.15**.

It logs in with a **guardian** username and password, keeps one browser-like session, and polls school pages. There is no Visma developer API key.

Default tenant in the config flow is Helsinki: `https://helsinki.inschool.fi`.

Confirmed working:

| Tenant | URL |
|---|---|
| Helsinki | `https://helsinki.inschool.fi` |
| Kaarina | `https://kaarina.inschool.fi` |
| Espoo | `https://espoo.inschool.fi` (JSON + HTML fallback for messages) |

Other `*.inschool.fi` tenants use the same flow. Attendance-table and week-schedule parsing was checked against Vantaa's page shape. Some schools need strong identification (Suomi.fi / MFA). This integration only supports Wilma username + password. Hollola is a known login miss ([issue #6](https://github.com/mniittymaki/ha-wilma/issues/6)).

> Not affiliated with Visma or Wilma. Endpoints outside `/messages` are unofficial and can change when Wilma updates.

## Credits

Login uses [Wilhelmina](https://github.com/frwickst/pywilma) (`wilhelmina` on PyPI) by frwickst. Message lists, timetable, homework, exams, news and attendance are parsed by this component. Wilhelmina `get_messages()` is not used on the live poll, so a system notice without `SenderId` no longer crashes the update.

Message bodies, pins, dated notes and the five-week schedule fetch follow the same ideas as [Tubbs10/ha-wilma](https://github.com/Tubbs10/ha-wilma).

## What you get

One entry per guardian account. One device per child.

Account: Lukemattomat, Viestit, Viimeisin viesti (`msg_1`… is date · subject · sender).

Per child: Oppilas (`probes`, `overview_keys`), Tänään, Seuraava tunti, Kalenteri, Aktiiviset / Menneet / Kaikki läksyt, Seuraava koe, Arvosanat, Tiedote, Kurssit, Uudet viestit, Poissaolot, Myöhästymiset, Kehut, Moitteet, Selvittämättömät tuntimerkinnät, Kaikki tuntimerkinnät, Viimeisin tuntimerkintä.

`Uudet viestit` has `messages` (ids) and `pinned`. Kehut and Moitteet have `notes` as `{date, kind, subject, teacher, text}`. `Seuraava tunti` attributes `lesson_*` stay weekly slots; `schedule` has the dates of each slot. A fetched week shows in probes as `schedule?date=05.10.2026 200 lessons=21`.

`403` on exams / groups / choices is often a permission miss. A dead session is `LOGIN_COLLISION`, overview `401`/`403`, or overview `200 text/html`.

## Actions

`wilma.get_message` fetches one body on demand. Wilma marks it read, so bodies are never polled. Response: `id`, `subject`, `sender`, `timestamp`, `content`, `replies`.

```yaml
action: wilma.get_message
data:
  entity_id: sensor.aino_esimerkki_uudet_viestit
  message_id: 1234567
response_variable: message
```

`device_id` works instead of `entity_id`. `wilma.pin_message` and `wilma.unpin_message` take the same target and `message_id`. Pins are stored per child and listed in `pinned`.

## Lesson notes

`attendance/view` is a table. Date comes from the row, the event from `title="20UEEL03; Hyvä!; Hyvin sujunut oppitunti. /Katju Pitkänen"`. Kind, course code, text and teacher are split. `Tiedoksi` is kept. Header `Tuntimerkinnät` is not a note. The old token scrape remains a fallback.

Kehut / Moitteet use the type name first. Free text is used only when the type says nothing. A doctor's visit counts as an absence.

## Schedule

Overview `DateArray` stops about 12 days ahead. 1.2.15 fetches `/{id}/schedule?date=DD.MM.YYYY` for this week and the next four and reads `eventsJSON`.

A loaded week replaces overview slots. An empty week (autumn break) stays empty. A failed page keeps the overview slots and does not break the update. Subject is the group code plus the Text qualifier (`20SUK SUPER`, `20KS.a`, `20UEEL.1`). Teacher is the staff on that lesson (`Pitkänen Katju (KAKA)`). Room is `Huoneet`. Cancelled and moved lessons are included.

## Homework

The homework date is the assigned day. The item stays in Aktiiviset until that subject's next lesson after that date has ended. `Englanti, A1` matches `ENA1`, `Suomen kieli ja kirjallisuus` matches `SUK`. A and B tracks stay apart. Each `hw_*` line ends with a match hint.

## Session

One Wilma login per username. A second session yields *Päällekkäinen kirjautuminen*. The coordinator keeps the last good school payload. Relogin + retry on collision or a dead overview. Add the account once; children come from `/{id}/roles`.

## Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mniittymaki&repository=ha-wilma&category=integration)

The button adds this repository to HACS (Integration). Then install **Wilma** and restart.

Manual: copy `custom_components/wilma` to `/config/custom_components/wilma`, restart, add the Wilma integration. Minimum Home Assistant **2024.1.0**.

## Limits

Password login only. No sending messages, no reporting absences. Fetching a body marks the message read. Empty sensors after an overnight cookie death: reload the config entry.

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

MIT. Wilhelmina has its own license: [frwickst/pywilma](https://github.com/frwickst/pywilma).
