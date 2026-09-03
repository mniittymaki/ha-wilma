DOMAIN = "wilma"
VERSION = "1.2.4"
DEFAULT_URL = "https://helsinki.inschool.fi"
DEFAULT_SCAN_INTERVAL = 300

CONF_URL = "url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CHILD_ID = "child_id"
CONF_CHILD_NAME = "child_name"
CONF_CHILDREN = "children"

TIMEZONE = "Europe/Helsinki"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
}

# Same Wilma2SID session. Official /api/v1/* needs a Visma developer key
# and is not used. These are the guardian web endpoints that work without it.
PROBE_PATHS = (
    "overview",
    "roles",
    "attendance",
    "attendance/view",
    "schedule",
    "exams",
    "news",
    "news/list",
    "gradebook",
    "grades",
    "choices",
    "groups",
    "calendar",
    "decisions",
    "printouts",
)

ABSENCE_TOKENS = (
    "poissa",
    "absent",
    "selvitys",
    "selvitettävä",
    "sairas",
    "sairaana",
    "lupa",
    "luvallinen",
    "terveys",
    "terveydellinen",
)
LATE_TOKENS = ("myöh", "late", "tardy")
POSITIVE_TOKENS = ("kehu", "kiitos", "aktiiv", "+akt", "+teh", "+koe", "hyvä")
