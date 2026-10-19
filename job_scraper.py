#!/usr/bin/env python3
"""
Architecture Firm Job Scraper (Job Radar)
==========================================
Scans careers pages of ~50 Twin Cities architecture firms for open
positions matching Jason's criteria, scores each match, and writes
results to jobs.json + a static HTML dashboard (index.html).

2026-10-17 retarget (Adkins did not renew his contract): three lanes, architecture firms,
building envelope (air barrier and enclosure consultants, testing firms like AET), and AI and
tech in AEC; Twin Cities metro plus fully remote in the US. NCARB-certified, not licensed, so
license-required roles stay dropped.

Usage:
    python job_scraper.py            # full scan
    python job_scraper.py --p1       # only top-15 priority firms
    python job_scraper.py --firm "HGA"  # one firm only

Requirements:
    pip install requests beautifulsoup4 lxml playwright
    playwright install chromium
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.parse as urlparse
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ── Paths ──────────────────────────────────────────────────────────────────────

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
FIRMS_CSV = os.path.join(THIS_DIR, "firms.csv")
OUTPUT_JSON = os.path.join(THIS_DIR, "jobs.json")
OUTPUT_HTML = os.path.join(THIS_DIR, "index.html")
LOG_FILE = os.path.join(THIS_DIR, "scrape.log")

# GitHub repo folder — the dashboard + jobs.json get copied here for GitHub Pages.
# Repo: https://github.com/jfunk9/job-scrubber
# Live: https://jfunk9.github.io/job-scrubber/
GITHUB_REPO_DIR = r"W:\AI\GitHub\job-scrubber"

# ── Config: Job-fit criteria ───────────────────────────────────────────────────

TITLE_KEYWORDS = [
    "architect", "architectural designer", "project architect",
    "job captain", "designer", "design lead",
    "design director", "project manager",
    "intermediate architect", "senior architect",
    "registered architect", "licensed architect",
    "interior architect",
    # Visualization / BIM / design technology — what Jason excels at
    "bim specialist", "bim technician", "bim coordinator", "bim manager",
    "design technologist", "visualization", "design visualization",
    "3d artist", "rendering", "real-time", "vr", "virtual reality",
    " iii", " iv", "level 3", "level iii", "senior", "lead",
    "principal", "associate",
    # 2026-10-17, his three lanes after Adkins did not renew. Lane 1, architecture firms:
    "architectural technician", "project designer", "revit",
    # Lane 2, building envelope (his Adkins air barrier reviews for AET):
    "building envelope", "envelope", "building enclosure", "enclosure",
    "air barrier", "building science", "waterproofing", "facade", "curtain wall",
    "envelope commissioning", "forensic",
    # Lane 3, AI and tech in AEC:
    "computational design", "design technology", "bim automation",
    "digital practice", "digital design", "virtual design", "vdc", "aec",
]

SECTOR_KEYWORDS = [
    "commercial", "healthcare", "civic", "government", "public",
    "transit", "transportation", "aviation", "airport",
    "hospitality", "restaurant", "food", "beverage", "f&b",
    "retail", "workplace", "office", "education", "k-12",
    "higher education", "mixed-use", "multifamily", "housing",
    "senior living",
    # 2026-10-17 lane 2, building envelope:
    "air barrier", "building envelope", "building enclosure", "enclosure",
    "waterproofing", "building science", "roofing", "fenestration",
    "energy code", "commissioning", "forensic", "field testing",
    # 2026-10-17 lane 3, tech in AEC:
    "aec", "construction technology", "design technology",
]

SOFTWARE_KEYWORDS = [
    "revit", "sketchup", "enscape", "lumion", "rhino",
    "twinmotion", "unreal", "unity", "d5 render",
    "bluebeam", "bim", "adobe",
    # Disruptive / emerging tech Jason wants to lean into
    "pyrevit", "dynamo", "grasshopper",
    "point cloud", "scan to bim", "3d scan", "lidar", "reality capture",
    "computational design", "parametric", "generative design",
    "ai", "machine learning", "automation",
    "autocad",
    # 2026-10-17 lane 2, envelope analysis tools ('therm' is a stem, so it also counts 'thermal'):
    "wufi", "therm", "flixo",
    # 2026-10-17 lane 3, the automation stack:
    "python", "revit api", "c#", "speckle", "ifc", "artificial intelligence",
]

EXCLUDE_TITLE_KEYWORDS = [
    "intern", "internship", "co-op", "coop",
    "marketing", "accountant", "accounting",
    "receptionist", "office manager", "it manager",
    "human resources", "hr ", "recruiter",
    "business development", "controller",
    "graphic designer", "interior designer", "lighting designer",
    "civil", "engineer", "engineering", "gis",
    "fire protection", "mep",
    "structural", "electrical", "mechanical", "plumbing",
    "landscape designer", "landscape architect",
    "industrial designer",
    "behavioral health planner",
    "commercial conservation architect",
    "project scheduler",
]

# 2026-10-17: his lanes 2 and 3 are full of titles the engineer excludes would kill
# ("Project Engineer - Building Envelope" at a testing firm, "Computational Design Engineer").
# A title carrying one of these lane words is let past ONLY the soft excludes below; intern,
# marketing, HR and the rest still drop it.
LANE_TITLE_OVERRIDES = [
    "envelope", "enclosure", "air barrier", "building science", "waterproofing",
    "facade", "curtain wall", "fenestration",
    "computational design", "design technolog", "bim", "revit", "aec",
    "digital practice", "virtual design", "vdc",
]
SOFT_EXCLUDES = ("engineer", "engineering")

# Target locations: Twin Cities metro + fully remote anywhere in the US (his 2026-10-17 pick).
# 2026-10-17: WAS "MSP metro + California + Chicago": the whitelist also carried San Diego,
# Newport Beach / Orange County, Santa Monica / Los Angeles and Chicago city. His 10-17 pick
# (Twin Cities plus remote, after Adkins did not renew) replaces them; those cities now sit in
# DROPPED_TARGET_CITIES so a bare "Chicago" with no state is still recognised as elsewhere.
# Hybrid in the Twin Cities counts as local: it passes on the city name.
# Twin Cities metro cities (2026-10-19: split out so a Minnesota place outside the metro can be told
# apart; WAS one list where "minnesota" and ", mn" let Hibbing, Duluth and St. Cloud pass as local).
METRO_CITIES = (
    "minneapolis", "minnetonka", "st. paul", "saint paul", "st paul",
    "bloomington", "edina", "eden prairie", "plymouth", "maple grove",
    "wayzata", "apple valley", "burnsville", "richfield",
    "golden valley", "st louis park", "st. louis park", "saint louis park",
    "roseville", "woodbury", "maplewood", "eagan", "lakeville", "shakopee",
    "brooklyn park", "brooklyn center", "coon rapids", "blaine", "fridley",
    "new brighton", "arden hills", "shoreview", "mendota heights",
    "inver grove heights", "hopkins", "chanhassen", "chaska", "savage",
    "prior lake", "white bear lake", "stillwater", "oakdale", "new hope",
    # 2026-10-19 added: more of the seven-county metro
    "st. anthony", "saint anthony", "columbia heights", "crystal", "robbinsdale",
    "champlin", "anoka", "andover", "ramsey", "ham lake", "lino lakes",
    "mounds view", "vadnais heights", "little canada", "lake elmo", "hugo",
    "cottage grove", "hastings", "rosemount", "farmington", "excelsior",
    "victoria", "waconia", "medina", "orono", "mound", "rogers", "minnetrista",
    "south st. paul", "west st. paul", "falcon heights", "lauderdale", "st. michael",
    "twin cities", "msp",
)
TARGET_LOCATION_KEYWORDS = list(METRO_CITIES) + [
    "minnesota", " mn,", " mn ", ", mn",
]

# 2026-10-19: AIA Minnesota's own region labels for places outside the metro. WAS passing on the
# word "minnesota": Evolve's "Outside Minnesota" and CF Design's "Northern Minnesota" listed as local.
OUTSTATE_REGIONS = re.compile(
    r"\b(outside (of )?minnesota|(northern|southern|southeast|southwest|northeast|northwest|"
    r"central|western|eastern|greater) minnesota)\b")

# 2026-10-19: big US cities outside Minnesota, for a place written with no state. WAS falling through
# to "assumed local": Braun Intertec's "Atlanta" historian passed. The metro is checked first, so
# "st. louis park" never reads as St. Louis.
OTHER_US_CITIES = (
    "atlanta", "dallas", "houston", "austin", "san antonio", "fort worth", "denver", "phoenix",
    "seattle", "portland", "boston", "new york", "philadelphia", "pittsburgh", "detroit",
    "milwaukee", "madison", "kansas city", "st. louis", "saint louis", "omaha", "des moines",
    "fargo", "sioux falls", "nashville", "charlotte", "raleigh", "miami", "tampa", "orlando",
    "salt lake", "las vegas", "san francisco", "san jose", "oakland", "sacramento", "baltimore",
    "cleveland", "columbus", "cincinnati", "indianapolis", "louisville", "new orleans",
)
# Backwards-compat alias used elsewhere
MSP_KEYWORDS = TARGET_LOCATION_KEYWORDS

# The cities his 10-17 pick dropped (WAS whitelisted, now known-elsewhere).
DROPPED_TARGET_CITIES = (
    "san diego", "chula vista", "carlsbad", "encinitas", "oceanside",
    "la jolla", "el cajon", "la mesa", "coronado", "national city",
    "newport beach", "costa mesa", "irvine", "huntington beach",
    "anaheim", "santa ana", "tustin", "mission viejo", "laguna beach",
    "lake forest", "aliso viejo", "fountain valley",
    "santa monica", "los angeles", "beverly hills", "culver city",
    "west hollywood", "pasadena", "burbank", "glendale", "long beach",
    "manhattan beach", "redondo beach", "el segundo", "marina del rey",
    "venice", "malibu", "torrance", "inglewood",
    "chicago",
)

REMOTE_KEYWORDS = ("remote", "work from home", "work-from-home", "telecommute",
                   "anywhere in the us", "anywhere in the united states", "100% virtual",
                   # 2026-10-17: Autodesk's Workday names its home-based roles "...- OffsiteHome"
                   "offsitehome", "offsite home")

# A remote role tied to another country is not his (remote anywhere in the US only).
NON_US_MARKERS = re.compile(
    r"\b(canada|uk|u\.k\.|united kingdom|england|london|ireland|india|europe|emea|apac|"
    r"latam|germany|france|netherlands|spain|poland|australia|singapore|japan|china|"
    r"mexico|brazil|toronto|vancouver|montreal|"
    # 2026-10-17 later: the Workday boards (Autodesk, Bentley, Trimble) passed Bengaluru, Shanghai,
    # Tel Aviv, Tokyo, Oslo and Dubai, since an unread place falls through to True.
    r"bengaluru|bangalore|pune|hyderabad|chennai|shanghai|beijing|shenzhen|israel|tel aviv|"
    r"tokyo|norway|oslo|sweden|denmark|finland|switzerland|italy|austria|belgium|portugal|"
    r"czech|romania|hungary|ukraine|korea|seoul|taiwan|philippines|vietnam|thailand|malaysia|"
    r"indonesia|new zealand|south africa|dubai|abu dhabi|united arab emirates|uae|saudi|qatar|"
    r"chile|colombia|argentina|"
    r"ind|chn|isr|jpn|gbr|deu|nor|swe|che|aus|sgp|kor|bra|mex)\b")

US_ONLY_MARKERS = re.compile(r"^\s*(united states( of america)?|usa|u\.s\.a?\.?|us)\s*$")

# 2026-10-17 later: WAS missing "CA" (a leftover from the SoCal whitelist), so "San Francisco, CA"
# passed as local; it surfaced once iCIMS postings started carrying their real locations.
NON_MN_STATES = ("AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC")


# Full state names (lower-cased) that are NOT Minnesota
NON_MN_STATE_NAMES = (
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "mississippi","missouri","montana","nebraska","nevada","new hampshire",
    "new jersey","new mexico","new york","north carolina","north dakota","ohio",
    "oklahoma","oregon","pennsylvania","rhode island","south carolina","south dakota",
    "tennessee","texas","utah","vermont","virginia","washington","west virginia",
    "wisconsin","wyoming","district of columbia",
)


NOT_REMOTE = re.compile(
    r"\b(not|no|non)[- ]remote\b|not a remote|remote (work )?(is )?not (available|offered|an option)")
_NON_MN_CODE = re.compile(r"\b(" + "|".join(NON_MN_STATES) + r")\b")
# Whole words, so "mound" never matches inside another name.
METRO_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in METRO_CITIES) + r")\b")
# A named town before ", MN" / ", Minnesota" ("hibbing, mn"); the metro is checked before this.
_MN_TOWN = re.compile(r"[a-z][a-z .'-]*,\s*(mn|minnesota)\b")

# 2026-10-19, miss m1070: a firm's own careers page gives no location, so every job there carried
# the firm's home city and passed as local. BKV Group's BIM Specialist listed as Minneapolis while
# its posting says "THIS ROLE IS LOCATED IN DALLAS, TX". The posting's own words now set the place.
_POSTING_PLACE_CUES = re.compile(
    r"(?:\b(?:this|the) (?:role|position|job|opportunity) is (?:located|based) in\b|"
    r"\b(?:located|based) (?:in|at) our\b|"
    r"\bjob location\s*[:\-]|\blocation\s*[:\-])\s*", re.I)
_CITY_STATE = re.compile(r"([A-Za-z][A-Za-z .'-]{1,40}?),\s*([A-Z]{2}|[A-Za-z]{4,14})\b")
_US_STATE_NAMES = set(NON_MN_STATE_NAMES) | {"minnesota"}
_US_STATE_CODES = set(NON_MN_STATES) | {"MN"}


def posting_location(description):
    """The place a posting's own text names after a cue such as "This role is located in" or
    "Location:", as "City, ST", or "" when it names none. Read only when the scraper gave no
    location; a word that is not a US state after the comma is not taken as one."""
    text = description or ""
    for cue in _POSTING_PLACE_CUES.finditer(text):
        window = text[cue.end():cue.end() + 90]
        if has_remote(window[:30]):
            return "Remote"
        for m in _CITY_STATE.finditer(window):
            city, state = m.group(1).strip(), m.group(2)
            ok = state.upper() in _US_STATE_CODES if len(state) == 2 else state.lower() in _US_STATE_NAMES
            if ok:
                # the last words before the comma are the city ("4124 Roseway Rd Minneapolis")
                return f"{' '.join(city.split()[-3:])}, {state}"
    return ""


def has_remote(text):
    """True if the text offers remote work (and does not say the opposite)."""
    t = (text or "").lower()
    if NOT_REMOTE.search(t):
        return False
    return any(k in t for k in REMOTE_KEYWORDS)


def is_msp_location(location_text, title="", description=""):
    """Return True if the job is Twin Cities metro (onsite or hybrid) or remote in the US.

    2026-10-17: WAS "MSP-area, SoCal or Chicago, or empty". Now, in order:
      empty location             -> True (unchanged; scrape_firm adds a rule for remote-lane firms)
      says MN / Minnesota        -> True
      location or title remote   -> True unless tied to another country
      only "United States"/"US"  -> True only if the description offers remote
      Twin Cities city name      -> True unless another state's code sits beside it
                                    ("Bloomington, IL", "Plymouth, MI" are not his)
      another state, a dropped city (Chicago, SoCal) or another country -> False
    """
    if not location_text or not location_text.strip():
        return True
    loc = location_text.lower().strip()
    remote = has_remote(loc) or has_remote(title)
    if re.search(r"\b(mn|minnesota)\b", loc):
        # 2026-10-19: WAS True for any Minnesota place. Now the metro, a bare "MN"/"Minnesota",
        # or remote; Hibbing, Duluth, St. Cloud, Rochester or "Northern Minnesota" alone drop.
        if METRO_RE.search(loc) or remote:
            return True
        if OUTSTATE_REGIONS.search(loc):
            return False
        return not _MN_TOWN.search(loc)
    if remote:
        return not NON_US_MARKERS.search(loc + " " + (title or "").lower())
    if US_ONLY_MARKERS.match(loc):
        return has_remote(description)
    other_code = _NON_MN_CODE.search(location_text)
    if METRO_RE.search(loc) and not other_code:
        return True
    if other_code:
        return False
    if any(city in loc for city in DROPPED_TARGET_CITIES):
        return False
    if any(re.search(r"\b" + re.escape(city) + r"\b", loc) for city in OTHER_US_CITIES):
        return False
    # Full state names check (catches "California", "Texas", etc.)
    if any(state in loc for state in NON_MN_STATE_NAMES):
        return False
    if NON_US_MARKERS.search(loc):
        return False
    return True


def passes_location(location_text, title="", description="", firm_city=""):
    """The location gate scrape_firm uses.

    2026-10-17: a firm added for the remote lane (city column starts with "Remote") is mostly
    scraped by the generic scraper, which never reads a location, so an empty location there
    would wave through every onsite San Francisco job. For those firms an empty location passes
    only when the title or description offers remote work.
    """
    remote_lane = (firm_city or "").lower().startswith("remote")
    if not (location_text or "").strip() and remote_lane:
        return has_remote(title) or has_remote(description)
    # 2026-10-17 later: a remote-lane firm's Workday board is worldwide, so a place this file cannot
    # read ("Bengaluru, IND", "Norway - Oslo") must not pass as local the way it does for a Twin
    # Cities firm. There a location passes only on Minnesota, a US remote signal, or a bare
    # "United States" whose description offers remote.
    if remote_lane:
        loc = location_text.lower()
        if re.search(r"\b(mn|minnesota)\b", loc):
            # 2026-10-19: the metro rule, WAS any Minnesota place
            return is_msp_location(location_text, title, description)
        if has_remote(loc) or has_remote(title):
            return not NON_US_MARKERS.search(loc + " " + (title or "").lower())
        if US_ONLY_MARKERS.match(loc):
            return has_remote(description)
        return False
    return is_msp_location(location_text, title, description)


def parse_ultipro_text(text):
    """
    UltiPro link text concatenates title + dept + city + address + date + type.
    Returns (clean_title, location, posted_date).
    """
    location = ""
    posted = ""
    m_loc = re.search(r"([A-Z][A-Za-z\.\s]+?),\s*([A-Z]{2})\s*\d{5}", text)
    if m_loc:
        location = f"{m_loc.group(1).strip()}, {m_loc.group(2)}"
    m_date = re.search(r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})", text)
    if m_date:
        posted = m_date.group(1)
    title = text
    for suffix in ["Full Time", "Part Time", "Contract", "Temporary"]:
        title = title.replace(suffix, "")
    if m_date:
        title = title[:title.find(m_date.group(1))]
    if m_loc:
        title = title[:title.find(m_loc.group(0))]
    for marker in ["Architecture", "Interior Design", "Urban Design", "Planning",
                   "Engineering", "Operations"]:
        idx = title.find(marker)
        if idx > 5:
            title = title[:idx]
            break
    title = re.sub(r"\s+", " ", title).strip()
    return title, location, posted


# License-required signals — drop jobs whose description requires architectural licensure.
# Jason has 17 yrs experience but is not licensed.
LICENSE_REQUIRED_KEYWORDS = [
    "licensed architect required",
    "registered architect required",
    "must be a licensed architect",
    "must be a registered architect",
    "professional license required",
    "professional registration required",
    "architectural registration required",
    "must hold a current professional license",
    "must hold a current architectural license",
    "must be licensed in",
    "must be registered in",
    "license is required",
    "registration is required",
    "aia registration",
]

# Title-only signals (used when description isn't available)
LICENSE_REQUIRED_TITLE = [
    "licensed architect", "registered architect",
]


def requires_license(title, description=""):
    """Return True if this job appears to require an architectural license."""
    t = (title or "").lower()
    for kw in LICENSE_REQUIRED_TITLE:
        if kw in t:
            return True
    d = (description or "").lower()
    for kw in LICENSE_REQUIRED_KEYWORDS:
        if kw in d:
            return True
    return False



# ── Network config ─────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

TIMEOUT = 15

# ── Playwright (lazy) ──────────────────────────────────────────────────────────

_browser = None
_pw = None
_browser_failed = False


def get_browser():
    # 2026-09-14: WAS retry-on-every-call with the started Playwright left running after a failed launch, so
    # the first failure turned every later call into "Sync API inside the asyncio loop" -- 20 firms per run
    # logged a browser error on top of their real one. Now: stop Playwright on failure, try once per run.
    global _browser, _pw, _browser_failed
    if _browser is None and not _browser_failed:
        try:
            from playwright.sync_api import sync_playwright
            _pw = sync_playwright().start()
            _browser = _pw.chromium.launch(headless=True)
            print("  [+] Playwright browser launched")
        except ImportError:
            print("  [!] Playwright not installed - JS-heavy pages will be skipped")
            _browser_failed = True
        except Exception as e:
            print(f"  [!] Could not launch browser: {e}")
            _browser_failed = True
            try:
                if _pw is not None:
                    _pw.stop()
            except Exception:
                pass
            _pw = None
    return _browser


def fetch_js(url, wait_ms=3000):
    browser = get_browser()
    if browser is None:
        return None
    try:
        page = browser.new_page()
        page.goto(url, timeout=20000)
        page.wait_for_timeout(wait_ms)
        html = page.content()
        page.close()
        return BeautifulSoup(html, "lxml")
    except Exception as e:
        print(f"    [JS] Error: {e}")
        return None


def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"    [HTTP] {e}")
        return None


# ── Scoring ───────────────────────────────────────────────────────────────────

_KW_CACHE = {}


def kw_hit(kw, text):
    """True if keyword `kw` appears in lower-cased `text` as whole word(s).

    2026-09-21: WAS `kw in text`, a plain substring test. 'ai' matched detailing, maintain, email,
    available, training, retail and job CAPTAIN, so tech_leverage scored on nearly every listing;
    'vr', 'gis' (logistics, strategist) and 'intern' (international) had the same disease.
    Now: a word boundary on the LEFT always (kills every mid-word hit: detailing, strategist,
    community-for-'unity'); on the RIGHT only for keywords of 3 characters or fewer ('ai', 'vr',
    'gis', 'iii', 'hr', 'bim', '75k'), so 'ai' can't become 'aid' or 'air'. Longer keywords stay
    stems: 'design' still counts 'designer', 'architect' 'architectural', 'manage' 'manager'.
    CAUGHT 2026-09-21: the first cut put \b on both sides and 'design' stopped matching
    'designer' -- 19 of 58 live listings lost their creative points. Known leftover of the stem
    rule: exclude 'intern' still matches 'international'. Specials are escaped ('$', 'qa/qc',
    'f&b'); padding spaces (' iii', 'hr ') are stripped because the boundary does their job.
    """
    pat = _KW_CACHE.get(kw)
    if pat is None:
        k = kw.strip()
        left = r"\b" if k[:1].isalnum() else ""
        right = r"\b" if (k[-1:].isalnum() and len(k) <= 3) else ""
        pat = _KW_CACHE[kw] = re.compile(left + re.escape(k) + right)
    return pat.search(text) is not None


def score_job(title, description=""):
    text = (title + " " + description).lower()
    bd = {"title_match": 0, "sector": 0, "software": 0, "level": 0, "exclude": 0}

    for kw in TITLE_KEYWORDS:
        if kw_hit(kw, text):  # was: substring -- 'vr' and ' iv' hit inside other words
            bd["title_match"] += 8
    bd["title_match"] = min(bd["title_match"], 40)

    for kw in SECTOR_KEYWORDS:
        if kw_hit(kw, text):
            bd["sector"] += 4
    bd["sector"] = min(bd["sector"], 25)

    for kw in SOFTWARE_KEYWORDS:
        if kw_hit(kw, text):  # was: substring 'ai' matched 'detailing'
            bd["software"] += 5
    bd["software"] = min(bd["software"], 15)

    if any(kw_hit(k, text) for k in ["senior", "lead", "principal", " iii", " iv", "15 year", "15+ year"]):
        bd["level"] = 20

    for kw in EXCLUDE_TITLE_KEYWORDS:
        if kw_hit(kw, title.lower()):  # was: substring 'gis' excluded 'strategist'
            bd["exclude"] -= 50

    score = sum(bd.values())
    return max(0, min(100, score)), bd


def is_relevant(title):
    t = title.lower().strip()
    if not t or len(t) < 3:
        return False
    lane_title = any(kw_hit(w, t) for w in LANE_TITLE_OVERRIDES)
    for kw in EXCLUDE_TITLE_KEYWORDS:
        if lane_title and kw in SOFT_EXCLUDES:
            continue  # 2026-10-17: 'Project Engineer - Building Envelope' is his lane 2
        if kw_hit(kw, t):  # was: substring 'gis' dropped 'Strategist' / 'Logistics' titles
            return False
    arch_words = ["architect", "designer", "design ", "drafter", "project",
                  "captain", "bim", "revit"]
    if any(w in t for w in arch_words):
        return True
    # 2026-10-17: his lanes 2 (building envelope) and 3 (AI and tech in AEC) name roles with
    # none of the architecture words: 'Building Science Specialist', 'Air Barrier Inspector',
    # 'Computational Design Specialist', 'Digital Practice Manager'.
    lane_words = ["envelope", "enclosure", "air barrier", "building science",
                  "waterproofing", "facade", "curtain wall", "fenestration", "forensic",
                  "computational", "design technolog", "digital practice", "digital design",
                  "virtual design", "vdc", "aec", "dynamo", "grasshopper", "parametric",
                  "building information"]
    return any(kw_hit(w, t) for w in lane_words)




# ── Jev (TypeSafe) — semantic judgments for the categories keywords fool easiest ─
# 2026-09-21: keyword tech_leverage had a hole word boundaries can't close -- a
# listing can genuinely say "ai" as a real word and still not be ABOUT ai/
# automation/design-tech in any meaningful way. 2026-09-22: compensation has the
# same disease from the other direction -- its trigger keyword is a bare "$",
# which fires on any dollar sign anywhere in the page (a benefits footer, a
# copyright line) whether or not a real number is disclosed. Both categories now
# get one real Jev judgment per listing instead of a keyword scan; the other
# five stay on keywords (cheap, not shown to need it). Falls back to the keyword
# ratio whenever the package, the key, or the network isn't there -- a run must
# never depend on an outside service to publish.
JEV_STATS = {"used": 0, "fallback": 0, "errors": 0}
_jev_client = None
_jev_unavailable = False

try:
    from typesafe_sdk import Noul, TypeSafeClient
except ImportError:
    Noul = None
    TypeSafeClient = None

# One Noul question per Jev-backed category. Keep instructions self-contained --
# Question IDs never reach the model, only the wording does.
JEV_QUESTIONS = {
    "tech_leverage": (
        "Does this job listing genuinely emphasize AI, automation, "
        "computational design, or emerging design technology as a "
        "meaningful part of the role -- not just an incidental word match?"
    ),
    "compensation": (
        "Does this job listing disclose an actual compensation figure or "
        "range for the role -- not just a passing mention of money, "
        "benefits, or a dollar sign elsewhere on the page?"
    ),
}


def get_jev_client():
    global _jev_client, _jev_unavailable
    if _jev_client is None and not _jev_unavailable:
        if TypeSafeClient is None or not os.environ.get("TYPESAFE_API_KEY"):
            _jev_unavailable = True
            return None
        try:
            _jev_client = TypeSafeClient()
        except Exception as e:
            print(f"    [Jev] could not start client: {e}")
            _jev_unavailable = True
    return _jev_client


def jev_judge(category, title, description):
    """
    Returns a 0-1 probability for one of JEV_QUESTIONS on this listing, or None
    if Jev isn't reachable -- the caller then falls back to the keyword ratio.
    """
    client = get_jev_client()
    if client is None:
        return None
    try:
        response = client.system_one(
            state={"title": title, "description": description[:4000]},
            questions={category: Noul(instructions=JEV_QUESTIONS[category])},
        )
        JEV_STATS["used"] += 1
        return response.nouls[category].noul
    except Exception as e:
        JEV_STATS["errors"] += 1
        print(f"    [Jev] {category} call failed, falling back to keywords: {e}")
        return None


# ── Fit-matrix scoring (Jason's weighted decision framework) ──────────────────
# Each category has a weight (sums to 100) and keyword signals.
# Score per category = weight * min(1, matches / target_matches)
FIT_MATRIX = {
    "autonomy": {
        "weight": 20,
        "target": 3,
        "keywords": ["principal", "studio leader", "studio lead", "design lead",
                     "associate principal", "director", "head of", "senior architect",
                     "lead architect", "manage", "ownership", "self-directed",
                     "lead the", "you will lead", "drive the"],
    },
    "creative": {
        "weight": 22,
        "target": 3,
        "keywords": ["design", "concept", "creative", "studio", "schematic",
                     "design phase", "concept design", "design lead", "designer",
                     "design director", "ideation", "design studio", "design vision"],
    },
    "lifestyle": {
        "weight": 20,
        "target": 2,
        "keywords": ["hybrid", "remote", "flexible", "work-life", "work life",
                     "4-day", "four-day", "wellness", "balance", "flexible schedule",
                     "esop", "employee-owned", "employee owned", "100% employee"],
    },
    "tech_leverage": {
        "weight": 12,
        "target": 2,
        "keywords": ["ai", "automation", "computational design", "parametric",
                     "pyrevit", "dynamo", "grasshopper", "vr", "virtual reality",
                     "real-time", "twinmotion", "unreal", "lumion", "enscape",
                     "machine learning", "design technology", "innovation",
                     # 2026-10-17 lane 3, AI and tech in AEC:
                     "bim automation", "revit api", "python", "speckle",
                     # 2026-10-17 later: HGA's 'Digital Design Support Lead' (Digital Practice Group,
                     # BIM, Revit, Dynamo) scored fit 9 because iCIMS was scored on title only; with
                     # its text these name the lane the way firms actually title it.
                     "digital practice", "digital design", "bim", "vdc", "virtual design"],
    },
    "tech_depth": {
        "weight": 11,
        "target": 3,
        "keywords": ["revit", "construction documents", "construction administration",
                     "production", "qa/qc", "specifications", "drafting", "detailing",
                     "permit drawings", "shop drawings",
                     # 2026-10-17 lane 2, the envelope review work he did for AET:
                     "air barrier", "building envelope", "enclosure", "waterproofing",
                     "plan review", "field testing", "wufi", "therm"],
    },
    "compensation": {
        "weight": 9,
        "target": 1,
        "keywords": ["$", "salary range", "competitive salary", "compensation",
                     "75k", "80k", "90k", "100k", "110k", "120k"],
    },
    "alignment": {
        "weight": 6,
        "target": 2,
        "keywords": ["career path", "career growth", "mentorship", "mentoring",
                     "esop", "employee-owned", "associate track", "professional development",
                     "long-term", "growth opportunity"],
    },
}


def fit_score(title, description=""):
    """
    Returns (total, breakdown) where total is 0-100 fit score using Jason's
    weighted matrix and breakdown is per-category contribution.
    """
    text = (title + " " + description).lower()
    breakdown = {}
    total = 0.0
    for cat, cfg in FIT_MATRIX.items():
        if cat in JEV_QUESTIONS:
            jev_p = jev_judge(cat, title, description)
            if jev_p is not None:
                contrib = round(cfg["weight"] * jev_p, 1)
                breakdown[cat] = contrib
                total += contrib
                continue
            JEV_STATS["fallback"] += 1
        matches = sum(1 for kw in cfg["keywords"] if kw_hit(kw, text))  # was: substring 'ai' matched 'detailing'
        ratio = min(1.0, matches / cfg["target"])
        contrib = round(cfg["weight"] * ratio, 1)
        breakdown[cat] = contrib
        total += contrib
    return round(total), breakdown


# ── Scrapers ──────────────────────────────────────────────────────────────────

def fetch_generic_description(url):
    """
    2026-09-22: CAUGHT by Jason, not a detector -- he'd read a BKV Group listing
    that named Enscape and asked why Jev scored it near zero on tech_leverage.
    Root cause: scrape_generic (and workday, which just calls it) never opened
    the individual job posting -- 50 of 53 firms in firms.csv were scored on
    TITLE ONLY, always, for both the keyword scan and now Jev. Neither method
    was ever shown "Enscape"; the title just said "BIM Specialist". This fetches
    the real posting the same way _fetch_aia_mn_description already did for its
    one firm. Best-effort and silent on failure -- a description miss must cost
    only that listing's description, never the listing or the run.
    """
    soup = fetch(url)
    if soup is None:
        return ""
    body = soup.find("body")
    if not body:
        return ""
    return body.get_text(" ", strip=True)[:6000]


def scrape_generic(url, firm_name):
    soup = fetch(url)
    if soup is None:
        soup = fetch_js(url)
    if soup is None:
        return [], "fetch failed"

    jobs = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not text or len(text) > 200:
            continue
        href_l = href.lower()
        if any(p in href_l for p in ["/job/", "/jobs/", "/career", "/position",
                                       "/opening", "/role/", "/apply/"]):
            full_url = urlparse.urljoin(url, href)
            key = (text.lower(), full_url)
            if key in seen:
                continue
            seen.add(key)
            if is_relevant(text):
                jobs.append({"title": text, "url": full_url, "location": ""})

    for tag in soup.find_all(["div", "section", "article", "li"]):
        cls = " ".join(tag.get("class", [])).lower()
        if any(kw in cls for kw in ["job", "career", "position", "opening", "role"]):
            heading = tag.find(["h1", "h2", "h3", "h4", "h5"])
            if heading:
                title = heading.get_text(strip=True)
                if not title or len(title) > 200:
                    continue
                link = tag.find("a", href=True)
                full_url = urlparse.urljoin(url, link["href"]) if link else url
                key = (title.lower(), full_url)
                if key in seen:
                    continue
                seen.add(key)
                if is_relevant(title):
                    jobs.append({"title": title, "url": full_url, "location": ""})

    # Every candidate here passed is_relevant already, so this is bounded by
    # the same set that would go on to be scored -- not every raw link on the
    # careers page.
    for job in jobs:
        job["description"] = fetch_generic_description(job["url"])
        time.sleep(0.2)

    return jobs, None


def scrape_greenhouse(url, firm_name):
    """
    Greenhouse-hosted board. Handles boards.greenhouse.io and job-boards.greenhouse.io.
    """
    token = None
    m = re.search(r"(?:job-boards|boards)\.greenhouse\.io/([^/?#]+)", url)
    if m:
        token = m.group(1)
    if not token:
        token = re.sub(r"[^a-z0-9]", "", firm_name.lower())

    api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    print(f"    [GH] token={token}")
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"    [GH] API returned {r.status_code}, falling back to HTML scrape")
            return scrape_generic(url, firm_name)
        data = r.json()
    except Exception as e:
        print(f"    [GH] {e}, falling back to HTML scrape")
        return scrape_generic(url, firm_name)

    jobs = []
    for j in data.get("jobs", []):
        title = j.get("title", "")
        if not is_relevant(title):
            continue
        jobs.append({
            "title": title,
            "url": j.get("absolute_url", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "description": j.get("content", ""),
        })
    return jobs, None


def scrape_ultipro(url, firm_name):
    """UltiPro / UKG Pro JobBoard - JS-rendered, use Playwright."""
    soup = fetch_js(url, wait_ms=5000)
    if soup is None:
        return [], "Playwright fetch failed"

    jobs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not text or len(text) > 500:
            continue
        if "OpportunityDetail" in href or "opportunityid" in href.lower():
            full_url = urlparse.urljoin(url, href)
            title, location, posted = parse_ultipro_text(text)
            if not title:
                continue
            key = (title.lower(), full_url)
            if key in seen:
                continue
            seen.add(key)
            if is_relevant(title):
                jobs.append({
                    "title": title,
                    "url": full_url,
                    "location": location,
                    "posted": posted,
                })
    return jobs, None


def scrape_icims(url, firm_name):
    """
    iCIMS Career Portal — JS-heavy. Uses Playwright with extended wait,
    walks any iframes, and matches multiple iCIMS link patterns.
    Also dumps rendered HTML to icims_<tenant>_debug.html for inspection.
    """
    from playwright.sync_api import sync_playwright

    browser = get_browser()
    if browser is None:
        return [], "Playwright unavailable"

    jobs = []
    seen = set()

    try:
        page = browser.new_page()
        page.goto(url, timeout=30000)
        # Wait for any of the typical iCIMS job-list signals
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            page.wait_for_timeout(8000)

        # Collect HTML from the main page AND every frame on the page
        html_chunks = [page.content()]
        for frame in page.frames:
            try:
                html_chunks.append(frame.content())
            except Exception:
                pass
        page.close()
    except Exception as e:
        return [], f"Playwright error: {e}"

    # Save a debug copy of what we saw (overwrites each run; useful when 0 results).
    # Audit fix 2026-07-23 (F5): gated behind JOB_SCRAPER_DEBUG. The Pages artifact
    # uploads the whole repo dir (path: .), so an unconditional dump published the
    # scraped HTML to the public site. Off in CI, off by default.
    if os.environ.get("JOB_SCRAPER_DEBUG"):
        try:
            m = re.search(r"careers-([a-z0-9-]+)\.icims\.com", url)
            tenant = m.group(1) if m else "unknown"
            with open(os.path.join(THIS_DIR, f"icims_{tenant}_debug.html"), "w", encoding="utf-8") as f:
                f.write("\n<!--FRAME-->\n".join(html_chunks))
        except Exception:
            pass

    for html in html_chunks:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if not text or len(text) > 200:
                continue
            href_l = href.lower()
            # iCIMS job link patterns
            if (re.search(r"/jobs/\d+/", href_l)
                or "icims.com/jobs/" in href_l):
                full_url = urlparse.urljoin(url, href)
                # Strip iCIMS prefix junk like "Job TitleArchitect"
                clean = re.sub(r"^(Job Title|Title|Position)\s*", "", text).strip()
                if not clean:
                    continue
                key = (clean.lower(), full_url)
                if key in seen:
                    continue
                seen.add(key)
                if is_relevant(clean):
                    jobs.append({"title": clean, "url": full_url, "location": ""})

    # 2026-10-17: WAS title only. HGA's 'Digital Design Support Lead' (BIM, Revit, Dynamo, the
    # Digital Practice Group) scored fit 9 because Jev and the keywords saw four words. iCIMS
    # answers a plain GET with 405, so each relevant posting is read through the same browser.
    for job in jobs:
        desc, loc = fetch_icims_detail(browser, job["url"])
        job["description"] = desc
        job["location"] = loc
    return jobs, None


def parse_icims_locations(text):
    """'Job Locations\\nUS-MN-Minneapolis | US-WI-Milwaukee' -> 'Minneapolis, MN; Milwaukee, WI'."""
    m = re.search(r"Job Locations?\s*\n?\s*([^\n]+)", text or "")
    if not m:
        return ""
    out = []
    for part in m.group(1).split("|"):
        bits = [b.strip() for b in part.strip().split("-", 2)]
        if len(bits) == 3 and len(bits[1]) == 2:
            out.append(f"{bits[2]}, {bits[1]}")
        elif part.strip():
            out.append(part.strip())
    return "; ".join(out)


def fetch_icims_detail(browser, url):
    """(description, location) for one iCIMS posting; ("", "") on any miss."""
    if browser is None:
        return "", ""
    if "in_iframe=1" not in url:
        url += ("&" if "?" in url else "?") + "in_iframe=1"
    # The in_iframe URL redirects to the branded page, which carries the posting in an inner frame,
    # so the longest frame's text is the posting (the outer body is only the footer).
    try:
        page = browser.new_page()
        page.goto(url, timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            page.wait_for_timeout(3000)
        texts = []
        for frame in page.frames:
            try:
                texts.append(frame.inner_text("body"))
            except Exception:
                pass
        page.close()
    except Exception as e:
        print(f"    [iCIMS] detail miss: {e}")
        return "", ""
    text = max(texts, key=len) if texts else ""
    return text[:6000], parse_icims_locations(text)


def scrape_aia_mn(url, firm_name):
    """
    AIA Minnesota Job Board aggregator.
    Captures title/firm/location from the listing, AND fetches each job's
    individual page to grab the description (so scoring uses the real text).
    """
    soup = fetch(url)
    if soup is None:
        soup = fetch_js(url, wait_ms=5000)
    if soup is None:
        return [], "fetch failed"

    if os.environ.get("JOB_SCRAPER_DEBUG"):  # audit F5: don't publish debug HTML (see icims dump)
        try:
            with open(os.path.join(THIS_DIR, "aia_mn_debug.html"), "w", encoding="utf-8") as f:
                f.write(str(soup))
        except Exception:
            pass

    jobs = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"/job/[^/]+/?$", href):
            continue
        if "job-submission" in href or "jobs/" in href.lower().rstrip("/").split("/")[-2:]:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) > 200:
            continue
        full_url = urlparse.urljoin(url, href)

        heading = a.find_parent(["h1","h2","h3","h4","h5","h6"]) or a.parent

        firm = ""
        location = ""
        nxt = heading.find_next_sibling() if heading else None
        attempts = 0
        while nxt is not None and attempts < 6:
            text = nxt.get_text(" ", strip=True)
            if text and len(text) < 200 and not text.lower().startswith("posted"):
                if not firm:
                    firm = text
                elif not location:
                    location = text
                    break
            nxt = nxt.find_next_sibling()
            attempts += 1

        if not firm:
            parent = heading.parent if heading else a.parent
            if parent:
                lines = [ln.strip() for ln in parent.get_text("\n", strip=True).split("\n") if ln.strip()]
                try:
                    ti = lines.index(title)
                    if ti + 1 < len(lines):
                        firm = lines[ti + 1]
                    if ti + 2 < len(lines):
                        location = lines[ti + 2]
                except ValueError:
                    pass

        key = (title.lower(), full_url)
        if key in seen:
            continue
        seen.add(key)

        if not is_relevant(title):
            continue

        # Fetch the individual job page to get the description for richer scoring
        description = _fetch_aia_mn_description(full_url)

        jobs.append({
            "title": title,
            "url": full_url,
            "location": location,
            "firm_override": firm,
            "description": description,
        })

    print(f"    [AIA-MN] found {len(jobs)} matching job links")
    return jobs, None


def _fetch_aia_mn_description(url):
    """
    Fetch an AIA-MN job page and return the description body text.
    Uses text-based extraction (between Description and Contact markers)
    so it's robust to varying HTML structure.
    """
    soup = fetch(url)
    if soup is None:
        return ""

    # Grab the full body text and extract the description portion.
    body = soup.find("body")
    if not body:
        return ""
    full_text = body.get_text("\n", strip=True)

    # Find the start: "Description" header marker
    m_start = re.search(r"\bDescription\b", full_text)
    if not m_start:
        # No marker — just return a chunk of body text (skip nav)
        return full_text[-4000:] if len(full_text) > 4000 else full_text

    start = m_start.end()

    # Find the end: Contact section or Back to Job Bank link
    end_match = re.search(r"\b(Contact|Back to Job Bank|info@aia-mn)", full_text[start:])
    end = start + end_match.start() if end_match else start + 6000

    desc = full_text[start:end].strip()
    # Cap length to avoid massive text blobs
    return desc[:6000]


def _html_text(html):
    return BeautifulSoup(html or "", "lxml").get_text(" ", strip=True)[:6000]


JSON_HEADERS = {"User-Agent": HEADERS["User-Agent"], "Accept": "application/json",
                "Accept-Language": "en-US"}
WORKDAY_PAGE = 20      # the cxs endpoint refuses a bigger page
WORKDAY_MAX = 1500     # Autodesk carried 355 on 10-17; a cap so a runaway total cannot stall the run


def parse_workday_url(url):
    """https://<tenant>.wd5.myworkdayjobs.com/en-US/<site>?q=enclosure -> (host, tenant, site, search)."""
    p = urlparse.urlparse(url)
    host = p.netloc
    if "myworkdayjobs.com" not in host:
        return None
    parts = [s for s in p.path.split("/") if s]
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]
    if not parts:
        return None
    q = urlparse.parse_qs(p.query).get("q", [""])[0]
    return host, host.split(".")[0], parts[0], q


def scrape_workday(url, firm_name):
    """
    Workday's public cxs JSON: POST https://<host>/wday/cxs/<tenant>/<site>/jobs pages the board,
    GET .../<site><externalPath> gives one posting's location list and description.
    2026-10-17: WAS a placeholder that called scrape_generic, which read WJE's own search page
    ("BECx, Building Science ... MORE >Building Enclosure Consultant") as a job and found none of
    the real ones. A board that fails here is an error, never a fall-back to the HTML page.
    """
    parsed = parse_workday_url(url)
    if not parsed:
        return [], f"not a myworkdayjobs.com board URL: {url}"
    host, tenant, site, search = parsed
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    postings, total, offset = [], None, 0
    while offset < WORKDAY_MAX:
        try:
            r = requests.post(api + "/jobs", headers=JSON_HEADERS, timeout=TIMEOUT + 10,
                              json={"appliedFacets": {}, "limit": WORKDAY_PAGE,
                                    "offset": offset, "searchText": search})
        except Exception as e:
            if offset == 0:
                return [], f"workday cxs: {e}"
            break
        if r.status_code != 200:
            if offset == 0:
                return [], f"workday cxs returned {r.status_code}"
            break
        data = r.json()
        if total is None:
            total = data.get("total") or 0  # only the first page carries the real total
        page = data.get("jobPostings") or []
        postings.extend(page)
        offset += WORKDAY_PAGE
        if not page or offset >= total:
            break
        time.sleep(0.2)
    print(f"    [WD] {tenant}/{site}: {len(postings)} postings of {total}")

    jobs = []
    for p in postings:
        title = (p.get("title") or "").strip()
        path = p.get("externalPath") or ""
        if not title or not path or not is_relevant(title):
            continue
        location = p.get("locationsText") or ""
        description = ""
        job_url = f"https://{host}/en-US/{site}{path}"
        try:
            d = requests.get(api + path, headers=JSON_HEADERS, timeout=TIMEOUT)
            if d.status_code == 200:
                info = d.json().get("jobPostingInfo") or {}
                locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
                joined = "; ".join(x for x in locs if x)
                location = joined or location
                description = _html_text(info.get("jobDescription"))
                job_url = info.get("externalUrl") or job_url
        except Exception as e:
            print(f"    [WD] detail miss {path}: {e}")
        jobs.append({"title": title, "url": job_url, "location": location,
                     "description": description, "posted": p.get("postedOn", "")})
        time.sleep(0.2)
    return jobs, None


def scrape_adp(url, firm_name):
    """
    ADP Workforce Now career center (AET). The page's own JSON:
    .../careercenter/public/events/staffing/v1/job-requisitions?cid=..., 20 a page via $skip.
    """
    q = urlparse.parse_qs(urlparse.urlparse(url).query)
    cid = q.get("cid", [""])[0]
    cc = q.get("ccId", ["19000101_000001"])[0]
    if not cid:
        return [], f"ADP URL has no cid: {url}"
    base = ("https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/"
            "job-requisitions")
    common = f"cid={cid}&ccId={cc}&lang=en_US&locale=en_US"
    reqs, skip = [], 0
    while skip < 1000:
        try:
            r = requests.get(f"{base}?{common}&$top=20&$skip={skip}", headers=JSON_HEADERS,
                             timeout=TIMEOUT + 10)
        except Exception as e:
            if skip == 0:
                return [], f"ADP: {e}"
            break
        if r.status_code != 200:
            if skip == 0:
                return [], f"ADP returned {r.status_code}"
            break
        page = r.json().get("jobRequisitions") or []
        reqs.extend(page)
        if len(page) < 20:
            break
        skip += 20
    print(f"    [ADP] {len(reqs)} requisitions")

    jobs = []
    for j in reqs:
        title = (j.get("requisitionTitle") or "").strip()
        item = j.get("itemID") or ""
        if not title or not is_relevant(title):
            continue
        locs = []
        for loc in j.get("requisitionLocations") or []:
            a = loc.get("address") or {}
            city = a.get("cityName") or ""
            st = (a.get("countrySubdivisionLevel1") or {}).get("codeValue") or ""
            locs.append(", ".join(x for x in (city, st) if x) or
                        ((loc.get("nameCode") or {}).get("shortName") or "").strip())
        description = ""
        try:
            d = requests.get(f"{base}/{item}?{common}", headers=JSON_HEADERS, timeout=TIMEOUT)
            if d.status_code == 200:
                description = _html_text(d.json().get("requisitionDescription"))
        except Exception:
            pass
        jobs.append({
            "title": title,
            "url": (f"https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
                    f"?cid={cid}&ccId={cc}&jobId={item}&lang=en_US"),
            "location": "; ".join(x for x in locs if x),
            "description": description,
            "posted": (j.get("postDate") or "")[:10],
        })
    return jobs, None


def scrape_ashby(url, firm_name):
    """Ashby job board (Higharc): https://api.ashbyhq.com/posting-api/job-board/<token>."""
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", url)
    if not m:
        return [], f"not an Ashby board URL: {url}"
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}",
                         headers=JSON_HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return [], f"Ashby returned {r.status_code}"
        data = r.json()
    except Exception as e:
        return [], f"Ashby: {e}"
    jobs = []
    for j in data.get("jobs", []):
        title = (j.get("title") or "").strip()
        if not title or not is_relevant(title):
            continue
        location = j.get("location") or ""
        if j.get("isRemote") and "remote" not in location.lower():
            location = f"Remote ({location})" if location else "Remote"
        jobs.append({"title": title, "url": j.get("jobUrl", ""), "location": location,
                     "description": j.get("descriptionPlain") or _html_text(j.get("descriptionHtml")),
                     "posted": (j.get("publishedAt") or "")[:10]})
    return jobs, None


def scrape_talentbrew(url, firm_name):
    """
    Radancy TalentBrew boards (Terracon): /search-jobs/<place> is server-rendered; each result is
    <a href="/job/..."><h2>title</h2><span class="job-location">...</span></a>. Only the first
    page (15) is read: its pager does not take a plain query string (tried 10-17).
    """
    soup = fetch(url)
    if soup is None:
        return [], "fetch failed"
    jobs, seen = [], set()
    for a in soup.find_all("a", href=True):
        h2 = a.find("h2")
        if "/job/" not in a["href"] or not h2:
            continue
        title = h2.get_text(strip=True)
        full = urlparse.urljoin(url, a["href"])
        if full in seen or not is_relevant(title):
            continue
        seen.add(full)
        loc = a.find(class_="job-location")
        jobs.append({"title": title, "url": full,
                     "location": loc.get_text(" ", strip=True).replace(" | Multiple Locations", "") if loc else ""})
    for job in jobs:
        job["description"] = fetch_generic_description(job["url"])
        time.sleep(0.2)
    return jobs, None


def scrape_lever(url, firm_name):
    m = re.search(r"jobs\.lever\.co/([^/?#]+)", url)
    if not m:
        return scrape_generic(url, firm_name)
    token = m.group(1)
    api_url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=TIMEOUT)
        data = r.json()
    except Exception:
        return scrape_generic(url, firm_name)

    jobs = []
    for j in data:
        title = j.get("text", "")
        if not is_relevant(title):
            continue
        jobs.append({
            "title": title,
            "url": j.get("hostedUrl", ""),
            "location": ((j.get("categories") or {}).get("location") or ""),
        })
    return jobs, None


SCRAPER_MAP = {
    "generic":    scrape_generic,
    "greenhouse": scrape_greenhouse,
    "workday":    scrape_workday,
    "lever":      scrape_lever,
    "ultipro":    scrape_ultipro,
    "icims":      scrape_icims,
    "aia_mn":     scrape_aia_mn,
    "adp":        scrape_adp,
    "ashby":      scrape_ashby,
    "talentbrew": scrape_talentbrew,
}


# ── Driver ────────────────────────────────────────────────────────────────────

def load_firms():
    firms = []
    with open(FIRMS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            firms.append(row)
    return firms


def scrape_firm(firm):
    name = firm["name"]
    url = firm["careers_url"]
    key = (firm.get("scraper_key") or "generic").strip() or "generic"
    scraper = SCRAPER_MAP.get(key, scrape_generic)

    print(f"\n[{firm['priority']}] {name}")
    print(f"    {url}")
    print(f"    scraper={key}")

    # Audit fix 2026-07-23 (HIGH: crashed firms were swallowed into [] —
    # indistinguishable from "firm has no matching openings", so a broken
    # scraper looked like a quiet job market forever). scrape_firm now returns
    # (jobs, error_or_None) — the RFP-scrubber error-channel pattern — and
    # run() carries errors into jobs.json + the keep-previous guard.
    try:
        result = scraper(url, name)
    except Exception as e:
        print(f"    [!] scraper crashed: {e}")
        return [], f"scraper crashed: {e}"

    if isinstance(result, tuple):
        jobs, err = result
    else:
        jobs, err = result, None

    if err:
        print(f"    [!] {err}")
        return [], str(err)

    enriched = []
    for j in jobs:
        title = j["title"]
        location = j.get("location", "")
        if not location.strip():
            # 2026-10-19, m1070: no place from the board, so read the posting's own words
            location = posting_location(j.get("description", ""))
        # Geographic filter: Twin Cities metro or remote in the US (2026-10-17; WAS MSP + SoCal + Chicago)
        if not passes_location(location, title, j.get("description", ""), firm.get("city", "")):
            continue
        # License filter — Jason isn't licensed; drop jobs that require it
        if requires_license(title, j.get("description", "")):
            continue
        score, bd = score_job(title, j.get("description", ""))
        fit, fit_bd = fit_score(title, j.get("description", ""))
        enriched.append({
            "firm": j.get("firm_override") or name,
            "priority": firm["priority"],
            "city": firm.get("city", ""),
            "title": title,
            "url": j["url"],
            "location": location,
            "posted": j.get("posted", ""),
            "score": score,
            "fit": fit,
            "breakdown": bd,
            "fit_breakdown": fit_bd,
            "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    enriched.sort(key=lambda x: -x["score"])
    print(f"    -> {len(enriched)} matching listings")
    for j in enriched[:3]:
        print(f"        [{j['score']:>3}] {j['title']}")
    return enriched, None


def write_results(all_jobs, firm_errors=None):
    firm_errors = firm_errors or []
    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(all_jobs),
        # Error channel (2026-07-23): firms whose scraper crashed or errored this
        # run. The dashboard can surface these; a consumer diffing totals can now
        # tell "market went quiet" apart from "scrapers broke".
        "firms_err": len(firm_errors),
        "firm_errors": firm_errors,
        "jobs": all_jobs,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\n[+] Wrote {len(all_jobs)} jobs to {OUTPUT_JSON}")

    # Mirror only the dashboard HTML to the GitHub repo (NOT jobs.json — that's
    # written by the GitHub Actions cron so we don't get merge conflicts when
    # both local and cloud runs touch the same file). When running INSIDE the
    # Actions runner, GITHUB_REPO_DIR has been overridden to cwd by scrape.yml,
    # so jobs.json gets written directly to the repo root by write_results above.
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true" or GITHUB_REPO_DIR == os.getcwd()
    try:
        os.makedirs(GITHUB_REPO_DIR, exist_ok=True)
        files = ("index.html", "jobs.json") if in_ci else ("index.html",)
        for fname in files:
            src_path = os.path.join(THIS_DIR, fname)
            dst_path = os.path.join(GITHUB_REPO_DIR, fname)
            if os.path.exists(src_path) and src_path != dst_path:
                shutil.copy2(src_path, dst_path)
                print(f"[+] Copied {fname} -> {dst_path}")
        if not in_ci:
            print(f"\n  >> Local run: jobs.json stays local. The daily GitHub")
            print(f"     Actions cron updates the live dashboard.")
            print(f"  >> If you want to publish NOW: manually trigger the workflow")
            print(f"     at https://github.com/jfunk9/job-scrubber/actions")
        else:
            print(f"\n  >> Live URL: https://jfunk9.github.io/job-scrubber/")
    except Exception as e:
        print(f"[!] Could not copy to GitHub repo at {GITHUB_REPO_DIR}: {e}")
        print(f"    (dashboard still available locally at {OUTPUT_HTML})")


def run(p1_only=False, firm_filter=None):
    """
    End-to-end scrape, no argparse, no input() prompt.
    Used by GitHub Actions and as the engine behind main().
    Returns the list of all jobs found.
    """
    # 2026-10-17: a firm checked and found to have no Twin Cities or remote US work stays in
    # firms.csv with verified=dropped and the reason in its notes, so nobody re-adds it blind.
    firms = [f for f in load_firms() if (f.get("verified") or "").strip() != "dropped"]
    if p1_only:
        firms = [f for f in firms if f["priority"] == "P1"]
    if firm_filter:
        firms = [f for f in firms if firm_filter.lower() in f["name"].lower()]
    print(f"Scanning {len(firms)} firms...")
    all_jobs, firm_errors = [], []
    for firm in firms:
        jobs, err = scrape_firm(firm)
        if err:
            firm_errors.append({"firm": firm["name"], "priority": firm.get("priority", ""),
                                "error": str(err)[:300]})
        all_jobs.extend(jobs)
        time.sleep(0.5)

    # Keep-previous guard (audit fix 2026-07-23): on a FULL run (no filters), a
    # collapse to zero results — or a majority of firms erroring — is treated as
    # scraper/infrastructure failure, NOT market truth. We refuse to overwrite a
    # previously-nonempty jobs.json and exit nonzero so the Actions run shows
    # red instead of publishing an empty dashboard.
    full_run = not p1_only and not firm_filter
    if full_run:
        prev_total = None
        try:
            with open(OUTPUT_JSON, encoding="utf-8") as f:
                prev_total = json.load(f).get("total")
        except (OSError, ValueError):
            pass
        collapsed = (len(all_jobs) == 0 and (prev_total or 0) > 0)
        broken_majority = (len(firms) >= 4 and len(firm_errors) >= max(3, len(firms) // 2))
        # Live-baseline ratio guard (AUDIT 2026-08-06 #7, added 2026-08-14): the two
        # guards above are blind to SELECTOR ROT -- sites answering 200 with zero
        # rows and no error. 72 jobs collapsing to 1 published silently for months.
        # The checkout's jobs.json is frozen (CI is contents:read, never commits
        # back -- prev_total sat at 72 since 2026-05-20), so the honest baseline is
        # the LIVE deployed dashboard, fetched fresh each run. Thresholds CHOSEN:
        # <25% of live total = infrastructure, not market (a real market never
        # loses 3/4 of listings overnight); live floor 8 so a naturally small
        # board can't trip it. Fetch failure skips the check -- a guard must
        # never become the thing that breaks the run.
        ratio_collapsed = False
        live_total = None
        if len(all_jobs) > 0:
            try:
                import urllib.request as _ur
                with _ur.urlopen("https://jfunk9.github.io/job-scrubber/jobs.json",
                                 timeout=15) as _r:
                    live_total = json.load(_r).get("total")
            except Exception:
                live_total = None
            if live_total and live_total >= 8 and len(all_jobs) < live_total * 0.25:
                ratio_collapsed = True
        if collapsed or broken_majority or ratio_collapsed:
            reason = ("results collapsed to 0 (previous run had %s)" % prev_total) if collapsed \
                     else ("results collapsed to %d from %s live (under 25%% -- selector rot, "
                           "not market)" % (len(all_jobs), live_total)) if ratio_collapsed \
                     else ("%d/%d firms errored" % (len(firm_errors), len(firms)))
            print(f"\n[!] PUBLISH ABORTED: {reason}. Keeping previous jobs.json/dashboard.")
            for fe in firm_errors[:10]:
                print(f"    [!] {fe['firm']}: {fe['error']}")
            sys.exit(2)

    if JEV_STATS["used"] or JEV_STATS["fallback"] or JEV_STATS["errors"]:
        print(f"\n[Jev] {', '.join(JEV_QUESTIONS)}: {JEV_STATS['used']} scored live, "
              f"{JEV_STATS['fallback']} fell back to keywords, {JEV_STATS['errors']} call errors")
    elif not os.environ.get("TYPESAFE_API_KEY"):
        print(f"\n[Jev] TYPESAFE_API_KEY not set -- {', '.join(JEV_QUESTIONS)} scored by keywords only")

    write_results(all_jobs, firm_errors)
    return all_jobs


def main():
    parser = argparse.ArgumentParser(description="Twin Cities architecture job scraper")
    parser.add_argument("--p1", action="store_true", help="Only scan P1 (top-15) firms")
    parser.add_argument("--firm", help="Scan a single firm by name (case-insensitive)")
    args = parser.parse_args()

    if args.firm:
        firms = load_firms()
        matching = [f for f in firms if args.firm.lower() in f["name"].lower()]
        if not matching:
            print(f"No firm matched '{args.firm}'")
            sys.exit(1)

    run(p1_only=args.p1, firm_filter=args.firm)
    # CI guard (2026-07-23): unguarded input() in CI hits EOF -> EOFError -> exit 1,
    # which turns every SUCCESSFUL Actions run red and makes the deliberate exit-2
    # abort guard indistinguishable from success at the exit-code level. Same guard
    # the RFP scraper already carries.
    if not (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
