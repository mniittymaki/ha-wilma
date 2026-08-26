# Home Assistant · Wilma

Unofficial Home Assistant integration for [Visma Wilma](https://www.wilma.fi/).

It logs in with a guardian account, reads messages through **Wilhelmina**, and
reads timetable / homework / exams / lesson notes from the same browser session
(no Visma developer API key).

Default tenant in the config flow is Helsinki: `https://helsinki.inschool.fi`.
Other Visma tenants use the same flow — confirmed working on Kaarina
(`https://kaarina.inschool.fi`).

> Not affiliated with Visma or Wilma. Endpoints outside `/messages` are
> unofficial and can change when Wilma updates.

## Credits

Authentication and **messages** use [Wilhelmina](https://github.com/frwickst/pywilma)
(`wilhelmina` on PyPI), the async Wilma client by [frwickst](https://github.com/frwickst).

Wilhelmina is used as-is:

- `WilmaClient(url, session=..., headless=True)`
- `login(username, password)`
- `get_messages()`
- shared `aiohttp` session + `Wilma2SID` cookie

This integration does **not** vendor or fork Wilhelmina. Home Assistant installs
it from PyPI via `manifest.json`:

```json
"requirements": ["wilhelmina>=0.1.9"]
```

School pages (overview, attendance, schedule, exams, news, gradebook) are
fetched by this component on top of that session.

## What you get

| Entity | Comes from |
|---|---|
| Lukemattomat, Viestit, Viimeisin viesti | Wilhelmina `get_messages()` |
| Oppilas | `/{id}/overview` + `/{id}/roles` |
| Tänään, Seuraava tunti, Kalenteri | overview schedule |
| Läksyt | overview homework / groups |
| Seuraava koe, Arvosanat | overview exams / grades |
| Tiedote | news (HTML/JSON if available) |
| Kurssit | overview groups |
| Poissaolot, Myöhästymiset, Kehut, Viimeisin tuntimerkintä | `/{id}/attendance` and `/{id}/attendance/view` HTML |

`sensor.*_oppilas` attributes `probes` and `overview_keys` show which URLs
returned JSON vs HTML. Use those when a section stays empty.

## Install

### Manual (Docker / Container HA)

1. Copy `custom_components/wilma` to `/config/custom_components/wilma`.
2. Restart Home Assistant (needed so `wilhelmina` is pip-installed).
3. Settings → Devices & services → Add integration → **Wilma**.

### HACS

Add this repository as a custom repository (Integration), then install **Wilma**
and restart.

## Configuration

| Field | Notes |
|---|---|
| URL | Tenant, e.g. `https://helsinki.inschool.fi` |
| Username | Guardian username / email |
| Password | Guardian password |
| Scan interval | Default 300 s |

Works on Container/Docker HA. No Supervisor add-on store required.

## Two children

One guardian login = **one** Home Assistant entry. The integration lists every
role under `/{id}/roles` and creates a device per child. Messages stay on the
account (Wilma inbox is shared). Timetable, homework, exams and lesson notes
are fetched **sequentially** after `GET /!childid` so siblings do not share
the last child's overview.

Do **not** add the same username three times. Wilma allows one session per
account; parallel logins return `Failed to get token: 521` and Home Assistant
will keep reloading.

If you already added one entry per child: delete extras, keep/re-add a single
Wilma integration.

## Limits

- **One Wilma session per username.** If you open Wilma in a browser with the
  same account, you get *Päällekkäinen kirjautuminen* (`common-34`) and this
  integration may see HTML error pages instead of JSON. Use a dedicated
  guardian login for Home Assistant if you can.
- MFA/TOTP is not implemented here (Wilhelmina may support extra flows; this
  integration uses password login only).
- Lesson notes on Helsinki are an HTML calendar; parsing depends on `title` /
  visible text. Overview JSON is used for timetable, homework and exams.
- No official `/api/v1/*` calls. No sending messages, no reporting absences.

## License

MIT. Wilhelmina has its own license — see
[frwickst/pywilma](https://github.com/frwickst/pywilma).
