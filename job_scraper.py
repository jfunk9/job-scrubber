#!/usr/bin/env python3
"""
Architecture Firm Job Scraper (Job Radar)
==========================================
Scans careers pages of ~50 Twin Cities architecture firms for open
positions matching Jason's criteria, scores each match, and writes
results to jobs.json + a static HTML dashboard (index.html).

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
    " iii", " iv", "level 3", "level iii", "senior", "lead",
    "principal", "associate",
]

SECTOR_KEYWORDS = [
    "commercial", "healthcare", "civic", "government", "public",
    "transit", "transportation", "aviation", "airport",
    "hospitality", "restaurant", "food", "beverage", "f&b",
    "retail", "workplace", "office", "education", "k-12",
    "higher education", "mixed-use", "multifamily", "housing",
    "senior living",
]

SOFTWARE_KEYWORDS = [
    "revit", "autocad", "sketchup", "enscape", "rhino",
    "bluebeam", "bim", "adobe", "lumion",
]

EXCLUDE_TITLE_KEYWORDS = [
    "intern", "internship", "co-op", "coop",
    "marketing", "accountant", "accounting",
    "receptionist", "office manager", "it manager",
    "human resources", "hr ", "recruiter",
    "business development", "controller",
    "graphic designer",
    "civil engineer", "structural engineer", "mep engineer",
    "electrical engineer", "mechanical engineer",
    "landscape designer", "landscape architect",
]

# ── Network config ─────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

TIMEOUT = 15

# ── Playwright (lazy) ──────────────────────────────────────────────────────────

_browser = None


def get_browser():
    global _browser
    if _browser is None:
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            _browser = pw.chromium.launch(headless=True)
            print("  [+] Playwright browser launched")
        except ImportError:
            print("  [!] Playwright not installed - JS-heavy pages will be skipped")
            return None
        except Exception as e:
            print(f"  [!] Could not launch browser: {e}")
            return None
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

def score_job(title, description=""):
    text = (title + " " + description).lower()
    bd = {"title_match": 0, "sector": 0, "software": 0, "level": 0, "exclude": 0}

    for kw in TITLE_KEYWORDS:
        if kw in text:
            bd["title_match"] += 8
    bd["title_match"] = min(bd["title_match"], 40)

    for kw in SECTOR_KEYWORDS:
        if kw in text:
            bd["sector"] += 4
    bd["sector"] = min(bd["sector"], 25)

    for kw in SOFTWARE_KEYWORDS:
        if kw in text:
            bd["software"] += 5
    bd["software"] = min(bd["software"], 15)

    if any(k in text for k in ["senior", "lead", "principal", " iii", " iv", "15 year", "15+ year"]):
        bd["level"] = 20

    for kw in EXCLUDE_TITLE_KEYWORDS:
        if kw in title.lower():
            bd["exclude"] -= 50

    score = sum(bd.values())
    return max(0, min(100, score)), bd


def is_relevant(title):
    t = title.lower().strip()
    if not t or len(t) < 3:
        return False
    for kw in EXCLUDE_TITLE_KEYWORDS:
        if kw in t:
            return False
    arch_words = ["architect", "designer", "design ", "drafter", "project",
                  "captain", "bim", "revit"]
    return any(w in t for w in arch_words)


# ── Scrapers ──────────────────────────────────────────────────────────────────

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
        if not text or len(text) > 200:
            continue
        if "OpportunityDetail" in href or "opportunityid" in href.lower():
            full_url = urlparse.urljoin(url, href)
            key = (text.lower(), full_url)
            if key in seen:
                continue
            seen.add(key)
            if is_relevant(text):
                jobs.append({"title": text, "url": full_url, "location": ""})
    return jobs, None


def scrape_workday(url, firm_name):
    return scrape_generic(url, firm_name)


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

    try:
        result = scraper(url, name)
    except Exception as e:
        print(f"    [!] scraper crashed: {e}")
        return []

    if isinstance(result, tuple):
        jobs, err = result
    else:
        jobs, err = result, None

    if err:
        print(f"    [!] {err}")
        return []

    enriched = []
    for j in jobs:
        title = j["title"]
        score, bd = score_job(title, j.get("description", ""))
        enriched.append({
            "firm": name,
            "priority": firm["priority"],
            "city": firm.get("city", ""),
            "title": title,
            "url": j["url"],
            "location": j.get("location", ""),
            "score": score,
            "breakdown": bd,
            "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    enriched.sort(key=lambda x: -x["score"])
    print(f"    -> {len(enriched)} matching listings")
    for j in enriched[:3]:
        print(f"        [{j['score']:>3}] {j['title']}")
    return enriched


def write_results(all_jobs):
    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(all_jobs),
        "jobs": all_jobs,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\n[+] Wrote {len(all_jobs)} jobs to {OUTPUT_JSON}")

    # Mirror dashboard + data into the GitHub repo for Pages publishing.
    try:
        os.makedirs(GITHUB_REPO_DIR, exist_ok=True)
        for fname in ("index.html", "jobs.json"):
            src = os.path.join(THIS_DIR, fname)
            dst = os.path.join(GITHUB_REPO_DIR, fname)
            if os.path.exists(src):
                shutil.copy2(src, dst)
                print(f"[+] Copied {fname} -> {dst}")
        print(f"\n  >> Open GitHub Desktop, commit, and push to publish.")
        print(f"  >> Live URL: https://jfunk9.github.io/job-scrubber/")
    except Exception as e:
        print(f"[!] Could not copy to GitHub repo at {GITHUB_REPO_DIR}: {e}")
        print(f"    (dashboard still available locally at {OUTPUT_HTML})")


def main():
    parser = argparse.ArgumentParser(description="Twin Cities architecture job scraper")
    parser.add_argument("--p1", action="store_true", help="Only scan P1 (top-15) firms")
    parser.add_argument("--firm", help="Scan a single firm by name (case-insensitive)")
    args = parser.parse_args()

    firms = load_firms()

    if args.p1:
        firms = [f for f in firms if f["priority"] == "P1"]
    if args.firm:
        firms = [f for f in firms if args.firm.lower() in f["name"].lower()]
        if not firms:
            print(f"No firm matched '{args.firm}'")
            sys.exit(1)

    print(f"Scanning {len(firms)} firms...")
    all_jobs = []
    for firm in firms:
        all_jobs.extend(scrape_firm(firm))
        time.sleep(0.5)

    write_results(all_jobs)
    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
