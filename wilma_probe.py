#!/usr/bin/env python3
"""
wilma_probe.py - standalone diagnostic harness for Wilma role scoping.

Purpose: determine whether Wilma returns per-child data when requests are
scoped by role slug (/!04307528/messages) versus unscoped (/messages).

This is a read-only diagnostic. It performs GETs only, apart from the login
POST. It never writes to Wilma.

Usage:
    python3 wilma_probe.py
    python3 wilma_probe.py --dump out/          # save every response body
    python3 wilma_probe.py --unscoped           # also fetch without slugs
    python3 wilma_probe.py --slugs '!01,!02'    # skip auto-discovery

Credentials come from a prompt, or from WILMA_USER / WILMA_PASS if set.
Prefer the prompt: environment variables leak into shell history.
"""

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Install with:  pip3 install requests")


DEFAULT_CITY = "espoo"

# Known role slugs for this account, for readable output. Discovery still
# runs normally; anything found but not listed here prints as the bare slug.
SLUG_NAMES = {
    "!04307528": "Ella",
    "!04307529": "Aaro",
    "!04265932": "Sasu",
}


def label(slug):
    name = SLUG_NAMES.get(slug)
    return f"{name} ({slug})" if name else slug

# Endpoints to probe under each role slug. Availability varies by Wilma
# version and by what the school has enabled, so 404s here are expected
# and informative rather than errors.
ENDPOINTS = [
    ("messages",   "/messages?format=json"),
    ("news",       "/news?format=json"),
    ("exams",      "/exams?format=json"),
    ("homework",   "/homework?format=json"),
    ("schedule",   "/schedule?format=json"),
    ("overview",   "/overview?format=json"),
    ("attendance", "/attendance?format=json"),
    ("groups",     "/selection/groups?format=json"),
    ("root_json",  "/?format=json"),
]


# --------------------------------------------------------------------------
# session setup
# --------------------------------------------------------------------------

SECRETS_FILE = "wilma_secrets.env"


def load_secrets_file(path=SECRETS_FILE):
    """Read KEY=value pairs from a local secrets file, if present.

    Values here do not override variables already set in the environment,
    so a one-off `WILMA_PASS=... python3 wilma_probe.py` still wins.
    """
    p = Path(path)
    if not p.is_file():
        return False

    mode = p.stat().st_mode & 0o777
    if mode & 0o077:
        print(f"  warning: {path} is mode {mode:03o}, readable by others.")
        print(f"           fix with:  chmod 600 {path}")

    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value

    print(f"  loaded credentials from {path}")
    return True


def get_credentials():
    user = os.environ.get("WILMA_USER") or input("Wilma username: ").strip()
    pw = os.environ.get("WILMA_PASS") or getpass.getpass("Wilma password: ")
    if not user or not pw:
        sys.exit("No credentials supplied.")
    if pw.startswith("put-the-real-password"):
        sys.exit(f"{SECRETS_FILE} still has the placeholder password in it.")
    return user, pw


def login(base, user, pw):
    """Handshake for a session token, then post credentials.

    Wilma's pre-auth GET returns LoginResult 'Failed' with a valid SessionID.
    That is normal and does not indicate a rejected password.
    """
    s = requests.Session()
    s.headers["User-Agent"] = "wilma-probe/1.0 (local diagnostic)"

    r = s.get(f"{base}/index_json", timeout=20)
    r.raise_for_status()
    handshake = r.json()

    token = handshake.get("SessionID") or handshake.get("SessionId")
    if not token:
        sys.exit(f"No session token in handshake. Got keys: {list(handshake)}")

    api_version = handshake.get("ApiVersion")
    print(f"  handshake ok (ApiVersion={api_version})")

    r = s.post(
        f"{base}/login",
        data={
            "Login": user,
            "Password": pw,
            "SessionId": token,
            "CompleteJson": "",
        },
        timeout=20,
        allow_redirects=True,
    )
    r.raise_for_status()

    body = r.text
    # A successful login lands on the guardian front page. A failure re-renders
    # the login form, usually with a Finnish error string.
    if "Oma etusivu" in body or re.search(r'href="/![0-9]+/', body):
        print("  login ok")
        return s, body

    for marker in ("Väärä käyttäjätunnus", "väärä salasana", "LoginResult"):
        if marker in body:
            sys.exit(f"Login appears to have failed (matched {marker!r}).")

    print("  login status unclear - continuing, discovery will confirm")
    return s, body


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def discover_slugs(session, base, landing_html):
    """Find role slugs. Each child the account can view has one."""
    found = []

    for html in (landing_html, session.get(base, timeout=20).text):
        for slug in re.findall(r'/(![0-9]+)(?:/|")', html):
            if slug not in found:
                found.append(slug)
        if found:
            break

    # Some versions expose these as structured data instead.
    if not found:
        try:
            r = session.get(f"{base}/api/v1/accounts", timeout=20)
            if r.ok and "json" in r.headers.get("content-type", ""):
                blob = json.dumps(r.json())
                for slug in re.findall(r'"(![0-9]+)"', blob):
                    if slug not in found:
                        found.append(slug)
        except Exception:
            pass

    return found


# --------------------------------------------------------------------------
# probing
# --------------------------------------------------------------------------

def summarise(payload):
    """One-line description of a response body, for eyeballing differences."""
    if isinstance(payload, dict):
        for key in ("Messages", "News", "Exams", "Homework", "Items", "Rows"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                if not items:
                    return f"{key}: 0 items"
                first = items[0]
                label = ""
                if isinstance(first, dict):
                    for k in ("Subject", "Title", "Name", "Caption"):
                        if first.get(k):
                            label = f" | first: {str(first[k])[:48]}"
                            break
                return f"{key}: {len(items)} items{label}"
        return f"dict, keys: {', '.join(list(payload)[:6])}"
    if isinstance(payload, list):
        return f"list, {len(payload)} items"
    return type(payload).__name__


def probe(session, base, path, dump_to=None, tag=""):
    """GET one endpoint. Returns (status, fingerprint, summary)."""
    url = f"{base}{path}"
    try:
        r = session.get(url, timeout=20)
    except requests.RequestException as exc:
        return None, None, f"request failed: {exc}"

    ctype = r.headers.get("content-type", "")
    if "json" not in ctype:
        # HTML back from a ?format=json URL usually means the endpoint does
        # not exist on this instance, or the session was bounced to login.
        note = "HTML (endpoint absent or session lost)"
        return r.status_code, None, note

    try:
        payload = r.json()
    except ValueError:
        return r.status_code, None, "malformed JSON"

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()[:12]

    if dump_to:
        dest = Path(dump_to) / f"{tag}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    return r.status_code, fingerprint, summarise(payload)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default=None)
    ap.add_argument("--slugs", help="comma-separated, skips auto-discovery")
    ap.add_argument("--dump", metavar="DIR", help="write every response body here")
    ap.add_argument("--unscoped", action="store_true",
                    help="also fetch each endpoint with no slug, for comparison")
    args = ap.parse_args()

    load_secrets_file()

    city = args.city or os.environ.get("WILMA_CITY") or DEFAULT_CITY
    base = f"https://{city}.inschool.fi"
    print(f"\n=== {base} ===")

    user, pw = get_credentials()
    session, landing = login(base, user, pw)

    if args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    else:
        slugs = discover_slugs(session, base, landing)

    if not slugs:
        sys.exit("No role slugs found. Pass them explicitly with --slugs.")

    print(f"\n=== {len(slugs)} role slug(s) ===")
    for s in slugs:
        print(f"  {label(s)}")

    unknown = [s for s in slugs if s not in SLUG_NAMES]
    if unknown:
        print(f"\n  note: {len(unknown)} slug(s) not in SLUG_NAMES: "
              f"{', '.join(unknown)}")
    missing = [s for s in SLUG_NAMES if s not in slugs]
    if missing:
        print(f"  note: expected but not discovered: {', '.join(missing)}")

    # results[endpoint][slug] = (status, fingerprint, summary)
    results = {name: {} for name, _ in ENDPOINTS}

    for slug in slugs:
        print(f"\n=== {label(slug)} ===")
        who = SLUG_NAMES.get(slug, slug.lstrip("!"))
        for name, path in ENDPOINTS:
            status, fp, summary = probe(
                session, base, f"/{slug}{path}",
                dump_to=args.dump, tag=f"{who}_{name}",
            )
            results[name][slug] = (status, fp, summary)
            fp_col = fp or "-"
            print(f"  {name:<11} {str(status):<4} {fp_col:<13} {summary}")

    if args.unscoped:
        print("\n=== no slug (guardian root) ===")
        for name, path in ENDPOINTS:
            status, fp, summary = probe(
                session, base, path,
                dump_to=args.dump, tag=f"unscoped_{name}",
            )
            results[name]["<unscoped>"] = (status, fp, summary)
            print(f"  {name:<11} {str(status):<4} {fp or '-':<13} {summary}")

    # ---- the verdict -----------------------------------------------------
    print("\n=== scoping verdict ===")
    print("  Endpoints where all children return byte-identical JSON are")
    print("  either not role-scoped, or genuinely shared across children.\n")

    for name, _ in ENDPOINTS:
        per_slug = {s: v for s, v in results[name].items() if s != "<unscoped>"}
        fps = [fp for _, fp, _ in per_slug.values() if fp]

        if not fps:
            verdict = "no data (endpoint unavailable)"
        elif len(fps) < len(per_slug):
            verdict = "partial - some children returned no JSON"
        elif len(set(fps)) == 1:
            verdict = "IDENTICAL across all children"
        elif len(set(fps)) == len(fps):
            verdict = "distinct per child - scoping works"
        else:
            # Partial collision: name who collided, that is the useful detail.
            groups = {}
            for slug, (_, fp, _) in per_slug.items():
                groups.setdefault(fp, []).append(SLUG_NAMES.get(slug, slug))
            collided = [g for g in groups.values() if len(g) > 1]
            verdict = (f"{len(set(fps))} distinct across {len(fps)} - "
                       f"same data: {'; '.join(' + '.join(g) for g in collided)}")

        print(f"  {name:<11} {verdict}")

    print("\n  If 'messages' is distinct per child here but identical in your")
    print("  integration, the integration is dropping the slug from its URLs.")
    print("  If it is IDENTICAL here too, the cause is upstream of the client.\n")


if __name__ == "__main__":
    main()
