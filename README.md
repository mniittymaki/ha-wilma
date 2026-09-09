# Home Assistant · Wilma

Unofficial Home Assistant integration for [Visma Wilma](https://www.wilma.fi/).

Current version: **1.2.7**.

It logs in with a **guardian** username and password, keeps one browser-like
session, and polls school pages. There is no Visma developer API key.

Default tenant in the config flow is Helsinki:
`https://helsinki.inschool.fi`.

Confirmed working:

| Tenant | URL |
|---|---|
| Helsinki | `https://helsinki.inschool.fi` |
| Kaarina | `https://kaarina.inschool.fi` |
| Espoo | `https://espoo.inschool.fi` (JSON + HTML fallback for messages) |

Other `*.inschool.fi` tenants use the same flow. Some schools need strong
identification (Suomi.fi / MFA) — this integration only supports Wilma
username + password. Hollola (`hollola.inschool.fi`) is a known login miss
([issue #6](https://github.com/mniittymaki/ha-wilma/issues/6)).

> Not affiliated with Visma or Wilma. Endpoints outside `/messages` are
> unofficial and can change when Wilma updates.

## Credits

Login uses [Wilhelmina](https://github.com/frwickst/pywilma) (`wilhelmina` on
PyPI) by [frwickst](https://github.com/frwickst):

- `WilmaClient(url, session=..., headless=True)`
- `login(username, password)`
- shared `aiohttp` session + `Wilma2SID` cookie

Home Assistant installs it from PyPI:

```json
"requirements": ["wilhelmina>=0.1.9"]
```

Message lists, timetable, homework, exams, news and attendance are parsed by
**this** component (JSON first, HTML fallback). Wilhelmina’s `get_messages()`
is not used on the live poll — system notices without `SenderId` used to
crash that parser ([issue #9](https://github.com/mniittymaki/ha-wilma/issues/9)).
1.2.5+ catches that path and defaults a missing sender to `Wilma`.

## What you get

One Home Assistant **entry** per guardian account. One **device** per child.
Account-level sensors live on the integration device; school sensors live on
the child device.

### Account

| Entity | What it shows |
|---|---|
| Lukemattomat | Unread message count |
| Viestit | Message list length |
| Viimeisin viesti | Latest subject. Attributes `msg_1`… include **date · subject · sender** |

### Per child

| Entity | What it shows |
|---|---|
| Oppilas | Name, class, school. Attributes: `probes`, `overview_keys`, counts |
| Tänään | Today’s lessons (`lesson_*`) |
| Seuraava tunti | Next weekly slot |
| Kalenteri | Lessons, exams and homework as calendar events |
| Aktiiviset läksyt | Still due (see homework rules) |
| Menneet läksyt | Next subject lesson after the assigned date has ended |
| Kaikki läksyt | Unfiltered list + the same `hw_*` hints |
| Seuraava koe | Upcoming exams |
| Arvosanat | Unread grades (`ExamSeen`) |
| Tiedote | School news |
| Kurssit | Overview `Groups` (code + name + teacher) |
| Uudet viestit | Per-child inbox after role switch |
| Poissaolot | Absence notes |
| Myöhästymiset | Late notes |
| Kehut | Positive notes |
| Selvittämättömät tuntimerkinnät | Unresolved / *selvitettävä* notes |
| Kaikki tuntimerkinnät | Full note list |
| Viimeisin tuntimerkintä | Latest note |

`sensor.*_oppilas` attributes `probes` and `overview_keys` show which URLs
returned JSON vs HTML. Use those when a section stays empty.

`403` on `exams` / `groups` / `choices` / `news/list` is often a **permission
miss**, not a dead session. A dead session is `LOGIN_COLLISION`, an overview
`401`/`403`, or overview `200 text/html` (login page).

## Homework rules (1.2.6–1.2.7)

Wilma homework uses long names (`Englanti, A1`, `Suomen kieli ja kirjallisuus`,
`Elämänkatsomustieto`). The timetable uses codes plus teacher
(`ENA1_Wera`, `SUK_Mari`, `2.UEEL_HannaF`).

Matching, in order:

1. Strip teacher/room: `ENA1_Wera V357` → `ENA1`.
2. Pair `Groups` course code ↔ course name for this child.
3. Built-in codes, among others: `ENA`/`EN` englanti, `ENB` englanti B,
   `SUK` suomen kieli ja kirjallisuus, `RUB`/`RUA` ruotsi, `MA` matematiikka,
   `HI` historia, `UEEL`/`UE` elämänkatsomus / uskonto, `KU` kuvataide,
   `KO` kotitalous, `KS` käsityö, `FY` fysiikka, `TE` terveystieto,
   `OP` opo, `LI` liikunta.
4. A and B tracks stay apart (`ENA1` ≠ `ENB1`). Generic `Englanti` is allowed
   only when it does not collide with both tracks.

**Due date:** the homework date is the **assigned** day (the lesson when it
was given), not the deadline. The item stays in *Aktiiviset* until that
subject’s **next** weekly lesson **after** that date has ended.

Example: given Mon 7.9. on `UEEL`, next `UEEL` Mon 14.9. 14:55 → active until
then. Same-day 7.9. 14:10 is the assignment slot, not the due slot.

Each `hw_*` line ends with a hint:

```text
2026-09-07 · UEEL_71 : Elämänkatsomustieto · Kirjoita vihkoosi… · lukujärjestys UEEL ma 14.9. 14:55
2026-08-17 · Englanti, A1 · Textbook s. 114… · tunti ohi · lukujärjestys ENA1 ma 09:15
… · ei lukujärjestysosumaa (ENA1, SUK, MA, …)
```

If several rows have no timetable match, the sensor also sets `huomio`.

## Session behaviour

- One Wilma login per username. A second browser/app session yields
  *Päällekkäinen kirjautuminen* and `Failed to get token: 521`.
- Coordinator keeps the last good school payload when a fetch fails.
- Relogin + retry on collision / dead overview.
- Prefer a **dedicated guardian login** for Home Assistant.

Do **not** add the same username three times (one entry per child). Add the
account once; children are created from `/{id}/roles`. Nameless numeric
guardian ids are dropped when named children exist.

Messages: JSON `/{id}/messages/list` first (Espoo `Status=1` = unread), HTML
fallback. `msg_*` includes the send timestamp.

## Install

### Manual (Docker / Container HA)

1. Copy `custom_components/wilma` to `/config/custom_components/wilma`.
2. Restart Home Assistant (`wilhelmina` is pip-installed on startup).
3. Settings → Devices & services → Add integration → **Wilma**.

### HACS

Add [mniittymaki/ha-wilma](https://github.com/mniittymaki/ha-wilma) as a custom
repository (Integration), install **Wilma**, restart.

Minimum Home Assistant: **2024.1.0**.

## Configuration

| Field | Notes |
|---|---|
| URL | Tenant, e.g. `https://helsinki.inschool.fi` |
| Username | Guardian username / email |
| Password | Guardian password |
| Scan interval | Default 300 s |

Works on Container/Docker HA. No Supervisor add-on store required.

## Limits

- Password login only. No Suomi.fi / MFA / TOTP.
- No official `/api/v1/*` writes. No sending messages, no reporting absences.
- Attendance on many tenants is an HTML calendar; parsing depends on visible
  text / `title`.
- Empty sensors after an overnight cookie death: reload the config entry
  (same as UI ⋮ → Reload). 1.2.3+ already tries to relogin; a morning
  `homeassistant.reload_config_entry` on `sensor.*_oppilas` is a safe belt.
- Wilhelmina itself still requires `sender_id` if something calls
  `get_messages()` directly. This integration no longer does that on the
  update path.

## Changelog (recent)

| Version | Notes |
|---|---|
| 1.2.7 | Homework due = next subject lesson **after** the assigned date |
| 1.2.6 | Code↔name matching (`Englanti, A1` ↔ `ENA1`), `hw_*` hints, calendar `time`/`date` crash fixes |
| 1.2.5 | Do not crash on auto-messages without `sender_id` |
| 1.2.4 | Aktiiviset / Menneet / Kaikki läksyt |
| 1.2.3 | Treat only overview 401/403 as a dead session |
| 1.2.2 | Keep last school data, drop unnamed guardian child, message timestamps |

## License

MIT. Wilhelmina has its own license — see
[frwickst/pywilma](https://github.com/frwickst/pywilma).
