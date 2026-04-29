# Twin Cities Architecture Job Radar

Scrapes careers pages of ~50 architecture firms within ~30 mi of 55408 (Minneapolis)
and produces a filtered, scored dashboard of open positions matching Jason's profile.

## Files

- `firms.csv` — source-of-truth list of firms (priority, careers URL, scraper key)
- `job_scraper.py` — main scraper; writes `jobs.json`
- `index.html` — static dashboard; reads `jobs.json` via fetch
- `jobs.json` — latest scrape results (auto-generated)
- `scrape.log` — run log (auto-generated)

## Usage

First-time setup:
```
pip install requests beautifulsoup4 lxml playwright
playwright install chromium
```

Run a full scan:
```
python job_scraper.py
```

Scan only the top-15 (P1) firms:
```
python job_scraper.py --p1
```

Scan one specific firm:
```
python job_scraper.py --firm "HGA"
```

After a scan, open `index.html` in your browser to view the dashboard locally.

## GitHub Pages deployment

The scraper auto-copies `index.html` and `jobs.json` into `W:\AI\GitHub\job-scrubber`
(the local clone of <https://github.com/jfunk9/job-scrubber>). To publish:

1. Run the scraper. It updates the GitHub folder for you.
2. Open GitHub Desktop, review the diff, commit, and push.
3. The live dashboard updates at <https://jfunk9.github.io/job-scrubber/>.

GitHub Pages settings: <https://github.com/jfunk9/job-scrubber/settings/pages> —
should be set to "Deploy from a branch" → `main` / `/ (root)`.

If you haven't cloned the repo yet, in GitHub Desktop:
**File → Clone Repository → jfunk9/job-scrubber** → set local path to
`W:\AI\GitHub\job-scrubber`.

## Firm priorities

- **P1 (top 15)** — Largest / most-likely-to-have-openings firms (HGA, Perkins&Will, Cuningham, DLR, etc.)
- **P2 (16–40)** — Mid-size firms with consistent project pipelines
- **P3 (41–50)** — Specialty / smaller firms (residential, niche)

## Scoring

Each listing gets a 0–100 score:
- **Title relevance** (up to 40): keyword match with role titles
- **Sector alignment** (up to 25): commercial, healthcare, civic, transit, hospitality
- **Software match** (up to 15): Revit, AutoCAD, SketchUp, Enscape
- **Level bonus** (20): senior/mid-senior signals
- **Exclude penalty** (-50): intern, marketing, non-architecture roles

## Customization

Edit `firms.csv` to add/remove firms, fix careers URLs, or change scraper keys.
Edit `TITLE_KEYWORDS`, `SECTOR_KEYWORDS`, `EXCLUDE_TITLE_KEYWORDS` at the top
of `job_scraper.py` to tune what counts as a match.

## Notes

- Many `careers_url` entries are best-guess — some firms use `/careers`, `/about/careers`,
  `/jobs`, third-party platforms (Greenhouse, Workday, Lever, BambooHR), or just an
  email address. Update the CSV as you verify each one.
- The `scraper_key` defaults to `generic` (HTML link/heading scraping) and falls
  back to a Playwright-rendered fetch if the static HTML returns nothing.
- Greenhouse / Lever scrapers use the platforms' public JSON APIs when available.
