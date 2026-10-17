# AUDIT 2026-09-22 #4 (MEDIUM, closed 2026-09-29): WAS no test file anywhere in the repo (a glob for
# **/test*.py found 0), so kw_hit's word-boundary rule, jev_judge's fall-back-to-None contract and
# fetch_generic_description's silent-miss contract had nothing holding them; now this file pins all three
# with stdlib unittest. No network: fetch is patched, the Jev client is a stub, Noul is a lambda.
"""Hermetic unit tests for job_scraper's pure pieces: kw_hit, jev_judge, fetch_generic_description.

Run from anywhere:
    python W:\\AI\\GitHub\\job-scrubber\\tests\\test_pure.py
    python -m unittest discover -s W:\\AI\\GitHub\\job-scrubber\\tests -v
"""
import contextlib
import io
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup  # noqa: E402

import job_scraper as js  # noqa: E402


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


class KwHit(unittest.TestCase):
    # The 2026-09-21 fix: left word boundary always, right boundary only for keywords of 3 chars or fewer.
    def test_short_keyword_is_a_whole_word(self):
        self.assertFalse(js.kw_hit("ai", "detailing"))
        self.assertFalse(js.kw_hit("ai", "aid"))
        self.assertFalse(js.kw_hit("gis", "strategist"))
        self.assertTrue(js.kw_hit("ai", "uses ai tools"))

    def test_long_keyword_stays_a_stem(self):
        # CAUGHT 2026-09-21: \b on both sides made 'design' miss 'designer'.
        self.assertTrue(js.kw_hit("design", "designer"))

    def test_padding_and_specials(self):
        self.assertTrue(js.kw_hit(" iii", "architect iii"))
        self.assertFalse(js.kw_hit(" iii", "architect iiii"))
        self.assertTrue(js.kw_hit("$", "pay $90,000"))
        self.assertTrue(js.kw_hit("qa/qc", "leads qa/qc reviews"))


class JevJudge(unittest.TestCase):
    def test_unavailable_returns_none(self):
        with mock.patch.object(js, "_jev_client", None), mock.patch.object(js, "_jev_unavailable", True):
            self.assertIsNone(js.jev_judge("tech_leverage", "BIM Specialist", "Enscape"))

    def test_client_error_returns_none_and_counts(self):
        def boom(**_kw):
            raise RuntimeError("network down")
        stub = types.SimpleNamespace(system_one=boom)
        with mock.patch.object(js, "_jev_client", stub), mock.patch.object(js, "Noul", lambda **kw: kw), \
                mock.patch.dict(js.JEV_STATS, {"used": 0, "fallback": 0, "errors": 0}), _quiet():
            self.assertIsNone(js.jev_judge("tech_leverage", "BIM Specialist", "Enscape"))
            self.assertEqual(js.JEV_STATS["errors"], 1)
            self.assertEqual(js.JEV_STATS["used"], 0)

    def test_client_answer_is_returned(self):
        seen = {}

        def answer(state, questions):
            seen["state"], seen["questions"] = state, questions
            return types.SimpleNamespace(nouls={"compensation": types.SimpleNamespace(noul=0.8)})
        stub = types.SimpleNamespace(system_one=answer)
        with mock.patch.object(js, "_jev_client", stub), mock.patch.object(js, "Noul", lambda **kw: kw), \
                mock.patch.dict(js.JEV_STATS, {"used": 0, "fallback": 0, "errors": 0}):
            self.assertEqual(js.jev_judge("compensation", "Architect", "x" * 5000), 0.8)
            self.assertEqual(js.JEV_STATS["used"], 1)
        self.assertEqual(len(seen["state"]["description"]), 4000)  # description is capped before it leaves
        self.assertIn("compensation", seen["questions"])


class FetchGenericDescription(unittest.TestCase):
    def test_fetch_miss_gives_empty_string(self):
        with mock.patch.object(js, "fetch", lambda url: None):
            self.assertEqual(js.fetch_generic_description("https://example.invalid/job"), "")

    def test_no_body_gives_empty_string(self):
        soup = BeautifulSoup("<p>Enscape</p>", "html.parser")
        with mock.patch.object(js, "fetch", lambda url: soup):
            self.assertEqual(js.fetch_generic_description("https://example.invalid/job"), "")

    def test_body_text_is_returned_and_capped(self):
        with mock.patch.object(js, "fetch", lambda url: BeautifulSoup("<body>Enscape x</body>", "html.parser")):
            self.assertIn("Enscape", js.fetch_generic_description("https://example.invalid/job"))
        big = BeautifulSoup("<body>" + "a" * 7000 + "</body>", "html.parser")
        with mock.patch.object(js, "fetch", lambda url: big):
            self.assertEqual(len(js.fetch_generic_description("https://example.invalid/job")), 6000)


class RetargetTitles(unittest.TestCase):
    # 2026-10-17 retarget: his three lanes after Adkins did not renew. Planted both ways.
    def test_envelope_titles_pass(self):
        for t in ("Building Envelope Consultant", "Air Barrier Inspector",
                  "Building Science Specialist", "Project Engineer - Building Envelope",
                  "Building Enclosure Commissioning Agent", "Forensic Envelope Field Technician"):
            self.assertTrue(js.is_relevant(t), t)

    def test_aec_tech_titles_pass(self):
        for t in ("BIM Automation Specialist", "Computational Design Engineer",
                  "Design Technology Manager", "Digital Practice Lead",
                  "Revit API Developer", "AEC Solutions Consultant"):
            self.assertTrue(js.is_relevant(t), t)

    def test_architecture_titles_still_pass(self):
        for t in ("Architectural Technician", "Project Designer", "BIM Coordinator"):
            self.assertTrue(js.is_relevant(t), t)

    def test_non_lane_titles_still_drop(self):
        for t in ("Civil Engineer", "Engineering Technician", "Mechanical Engineer",
                  "Building Envelope Intern", "Marketing Coordinator", "Software Engineer"):
            self.assertFalse(js.is_relevant(t), t)

    def test_licensed_architect_title_is_dropped(self):
        self.assertTrue(js.requires_license("Licensed Architect - Building Envelope"))
        self.assertTrue(js.requires_license("Project Architect", "Must be a licensed architect."))
        self.assertFalse(js.requires_license("Building Envelope Consultant", "NCARB a plus"))

    def test_envelope_title_scores_on_title(self):
        score, bd = js.score_job("Building Envelope Consultant",
                                 "Air barrier plan review, WUFI and THERM modeling, field testing.")
        self.assertGreater(bd["title_match"], 0)
        self.assertGreater(bd["sector"], 0)
        self.assertGreater(bd["software"], 0)
        self.assertEqual(bd["exclude"], 0)


class RetargetLocations(unittest.TestCase):
    # 2026-10-17: Twin Cities metro plus remote anywhere in the US. WAS MSP + SoCal + Chicago.
    def test_twin_cities_pass(self):
        for loc in ("Minneapolis, MN", "St. Paul, Minnesota", "Bloomington, MN",
                    "Hybrid - Minneapolis", "Eagan", "Edina, MN 55435"):
            self.assertTrue(js.is_msp_location(loc), loc)

    def test_chicago_and_socal_onsite_drop(self):
        for loc in ("Chicago, IL", "Chicago", "San Diego, CA", "Santa Monica, CA",
                    "Newport Beach", "Bloomington, IL", "Plymouth, MI", "Denver, CO"):
            self.assertFalse(js.is_msp_location(loc), loc)

    def test_remote_us_passes(self):
        self.assertTrue(js.is_msp_location("Remote"))
        self.assertTrue(js.is_msp_location("Remote - US"))
        self.assertTrue(js.is_msp_location("Remote, Texas"))
        self.assertTrue(js.is_msp_location("San Francisco, CA", title="BIM Automation Specialist (Remote)"))

    def test_remote_abroad_drops(self):
        self.assertFalse(js.is_msp_location("Remote - Canada"))
        self.assertFalse(js.is_msp_location("Remote, United Kingdom"))

    def test_united_states_needs_remote_in_description(self):
        self.assertTrue(js.is_msp_location("United States", "Design Technology Manager",
                                           "This is a fully remote position."))
        self.assertFalse(js.is_msp_location("United States", "Design Technology Manager",
                                            "On site at our Austin office."))
        self.assertFalse(js.is_msp_location("United States", "Design Technology Manager",
                                            "This is not a remote role."))

    def test_empty_location_unchanged_for_local_firms(self):
        self.assertTrue(js.passes_location("", "Project Designer", "", "Minneapolis"))

    def test_remote_lane_firm_needs_remote_signal(self):
        self.assertFalse(js.passes_location("", "BIM Automation Specialist", "Onsite in SF.", "Remote (US)"))
        self.assertTrue(js.passes_location("", "BIM Automation Specialist", "Fully remote.", "Remote (US)"))
        self.assertFalse(js.passes_location("Chicago, IL", "BIM Manager", "", "Remote (US)"))


class FirmsCsv(unittest.TestCase):
    def test_new_lane_firms_are_present_and_well_formed(self):
        firms = js.load_firms()
        names = [f["name"] for f in firms]
        self.assertEqual(len(names), len(set(names)), "duplicate firm names")
        for f in firms:
            self.assertIn(f["scraper_key"], js.SCRAPER_MAP, f["name"])
            self.assertTrue(f["careers_url"].startswith("https://"), f["name"])
        envelope = [f for f in firms if "his lane: envelope" in f["notes"]]
        tech = [f for f in firms if "his lane: AEC tech" in f["notes"]]
        self.assertGreaterEqual(len(envelope), 3)
        self.assertGreaterEqual(len(tech), 3)
        self.assertTrue(any(f["name"].startswith("AET") for f in envelope))
        # 2026-10-17 later: WAS every lane firm verified=no (best guesses). Each was opened that day;
        # verified is now yes, no (board real but empty) or dropped (reason in its notes).
        for f in envelope + tech:
            self.assertIn(f["verified"], ("yes", "no", "dropped"), f["name"])
            if f["verified"] == "dropped":
                self.assertIn("DROPPED", f["notes"], f["name"])
            self.assertNotIn("best guess", f["notes"], f["name"])

    def test_dropped_firms_are_not_scraped(self):
        rows = [{"name": "Kept", "priority": "P2", "verified": "yes"},
                {"name": "Gone", "priority": "P2", "verified": "dropped"}]
        seen = []
        with mock.patch.object(js, "load_firms", lambda: rows), \
                mock.patch.object(js, "scrape_firm", lambda f: (seen.append(f["name"]) or ([], None))), \
                mock.patch.object(js, "write_results", lambda *a, **k: None), \
                mock.patch.object(js.time, "sleep", lambda s: None), _quiet():
            js.run(firm_filter="e")  # a filter, so the keep-previous guard stays out of it
        self.assertEqual(seen, ["Kept"])


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


class Workday(unittest.TestCase):
    # 2026-10-17: scrape_workday WAS scrape_generic, which read WJE's search page as a job.
    URL = "https://wje.wd1.myworkdayjobs.com/en-US/Careers?q=enclosure"

    def test_url_parse(self):
        self.assertEqual(js.parse_workday_url(self.URL), ("wje.wd1.myworkdayjobs.com", "wje", "Careers", "enclosure"))
        self.assertEqual(js.parse_workday_url("https://autodesk.wd1.myworkdayjobs.com/Ext")[1:3], ("autodesk", "Ext"))
        self.assertIsNone(js.parse_workday_url("https://www.wje.com/careers/"))

    def _fake(self, calls):
        board = [{"title": "Building Enclosure Consultant | 8+ Years", "externalPath": "/job/Minneapolis-MN/BEC_1",
                  "locationsText": "2 Locations", "postedOn": "Posted Today"},
                 {"title": "Structural Engineer | 15+ years", "externalPath": "/job/Seattle-WA/SE_2",
                  "locationsText": "Seattle, WA"}]

        def post(url, headers=None, json=None, timeout=None):
            calls.append(("POST", url, json))
            page = board if json["offset"] == 0 else []
            return _Resp(200, {"total": 2 if json["offset"] == 0 else 0, "jobPostings": page})

        def get(url, headers=None, timeout=None):
            calls.append(("GET", url, None))
            return _Resp(200, {"jobPostingInfo": {
                "location": "Minneapolis, MN", "additionalLocations": ["Chicago, IL"],
                "jobDescription": "<p>Air barrier plan review and <b>WUFI</b> modeling.</p>",
                "externalUrl": "https://wje.wd1.myworkdayjobs.com/Careers/job/Minneapolis-MN/BEC_1"}})
        return post, get

    def test_real_postings_come_back_with_location_and_description(self):
        calls = []
        post, get = self._fake(calls)
        with mock.patch.object(js.requests, "post", post), mock.patch.object(js.requests, "get", get), \
                mock.patch.object(js.time, "sleep", lambda s: None), _quiet():
            jobs, err = js.scrape_workday(self.URL, "WJE")
        self.assertIsNone(err)
        self.assertEqual([j["title"] for j in jobs], ["Building Enclosure Consultant | 8+ Years"])
        self.assertEqual(jobs[0]["location"], "Minneapolis, MN; Chicago, IL")
        self.assertIn("WUFI", jobs[0]["description"])
        self.assertNotIn("<p>", jobs[0]["description"])
        self.assertTrue(jobs[0]["url"].endswith("/BEC_1"))
        self.assertEqual(calls[0][1], "https://wje.wd1.myworkdayjobs.com/wday/cxs/wje/Careers/jobs")
        self.assertEqual(calls[0][2]["searchText"], "enclosure")
        # the engineer row was filtered before any detail call
        self.assertFalse(any("SE_2" in c[1] for c in calls))

    def test_board_failure_is_an_error_not_a_generic_fallback(self):
        def post(*a, **k):
            return _Resp(422, {})
        with mock.patch.object(js.requests, "post", post), \
                mock.patch.object(js, "scrape_generic", lambda *a: self.fail("fell back to generic")), _quiet():
            jobs, err = js.scrape_workday(self.URL, "WJE")
        self.assertEqual(jobs, [])
        self.assertIn("422", err)

    def test_pages_until_total(self):
        calls = []

        def post(url, headers=None, json=None, timeout=None):
            calls.append(json["offset"])
            n = json["offset"]
            page = [{"title": f"Clerk {n + i}", "externalPath": f"/job/x/{n + i}"} for i in range(20)] if n < 45 else []
            return _Resp(200, {"total": 45 if n == 0 else 0, "jobPostings": page[:45 - n]})
        with mock.patch.object(js.requests, "post", post), mock.patch.object(js.time, "sleep", lambda s: None), _quiet():
            js.scrape_workday("https://x.wd5.myworkdayjobs.com/Site", "X")
        self.assertEqual(calls, [0, 20, 40])  # the later pages' total of 0 did not stop it early


class OtherBoards(unittest.TestCase):
    def test_adp_reads_title_location_and_skips_non_lane(self):
        def get(url, headers=None, timeout=None):
            if "/job-requisitions/" in url:
                return _Resp(200, {"requisitionDescription": "<p>Air barrier testing</p>"})
            return _Resp(200, {"jobRequisitions": [
                {"itemID": "1_1", "requisitionTitle": "Building Envelope Consultant",
                 "requisitionLocations": [{"address": {"cityName": "St Paul",
                                                       "countrySubdivisionLevel1": {"codeValue": "MN"}}}]},
                {"itemID": "2_1", "requisitionTitle": "Drill Assistant",
                 "requisitionLocations": [{"address": {"cityName": "Duluth",
                                                       "countrySubdivisionLevel1": {"codeValue": "MN"}}}]}]})
        url = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=abc&ccId=19000101_000001&lang=en_US"
        with mock.patch.object(js.requests, "get", get), _quiet():
            jobs, err = js.scrape_adp(url, "AET")
        self.assertIsNone(err)
        self.assertEqual([(j["title"], j["location"]) for j in jobs], [("Building Envelope Consultant", "St Paul, MN")])
        self.assertIn("jobId=1_1", jobs[0]["url"])
        self.assertIn("Air barrier", jobs[0]["description"])
        _, err = js.scrape_adp("https://workforcenow.adp.com/x?lang=en_US", "AET")
        self.assertIn("cid", err)

    def test_ashby_marks_remote(self):
        def get(url, headers=None, timeout=None):
            return _Resp(200, {"jobs": [
                {"title": "Computational Design Specialist", "location": "New York City, NY", "isRemote": True,
                 "jobUrl": "https://jobs.ashbyhq.com/higharc/1", "descriptionPlain": "Grasshopper"},
                {"title": "Account Executive", "location": "Atlanta, GA", "isRemote": True, "jobUrl": "u2"}]})
        with mock.patch.object(js.requests, "get", get):
            jobs, err = js.scrape_ashby("https://jobs.ashbyhq.com/higharc", "Higharc")
        self.assertIsNone(err)
        self.assertEqual([j["location"] for j in jobs], ["Remote (New York City, NY)"])
        self.assertTrue(js.passes_location(jobs[0]["location"], jobs[0]["title"], "", "Remote (US)"))

    def test_talentbrew_splits_title_from_location(self):
        html = ('<body><ul><li><a href="/job/plymouth/bec/1/2"><h2>Building Enclosure Consultant</h2>'
                '<span class="job-location">Plymouth, MN | Multiple Locations</span></a></li>'
                '<li><a href="/job/omaha/m/1/3"><h2>Marketing Specialist</h2>'
                '<span class="job-location">Omaha, NE</span></a></li></ul></body>')
        with mock.patch.object(js, "fetch", lambda u: BeautifulSoup(html, "lxml")), \
                mock.patch.object(js, "fetch_generic_description", lambda u: ""), \
                mock.patch.object(js.time, "sleep", lambda s: None):
            jobs, err = js.scrape_talentbrew("https://careers.terracon.com/search-jobs/Minnesota", "Terracon")
        self.assertEqual([(j["title"], j["location"]) for j in jobs], [("Building Enclosure Consultant", "Plymouth, MN")])
        self.assertTrue(jobs[0]["url"].startswith("https://careers.terracon.com/job/"))

    def test_icims_locations(self):
        text = "Digital Design Support Lead\nJob Locations\nUS-MN-Minneapolis | US-WI-Milwaukee | US-CA-Santa Monica\nJob ID"
        self.assertEqual(js.parse_icims_locations(text), "Minneapolis, MN; Milwaukee, WI; Santa Monica, CA")
        self.assertTrue(js.is_msp_location(js.parse_icims_locations(text)))
        self.assertEqual(js.parse_icims_locations("no header here"), "")

    def test_remote_lane_board_drops_places_abroad(self):
        # 2026-10-17 live run: these passed from Autodesk and Bentley before the fix.
        for loc in ("Bengaluru, IND", "Shanghai, CHN", "Tel Aviv, ISR", "Tokyo, JPN", "Norway - Oslo",
                    "Dubai, Dubai, United Arab Emirates", "Portland OR USA", "Somewhere Unread"):
            self.assertFalse(js.passes_location(loc, "Product Manager, Revit", "", "Remote (US)"), loc)
            self.assertFalse(js.is_msp_location(loc) and loc != "Somewhere Unread", loc)
        for loc in ("US - Remote, CO; US - Remote, FL", "Pennsylvania, United States - Remote",
                    "Remote (New York City, NY)", "Minneapolis, MN; Seattle, WA"):
            self.assertTrue(js.passes_location(loc, "AEC Solutions Professional", "", "Remote (US)"), loc)
        self.assertTrue(js.passes_location("United States", "BIM Manager", "Fully remote.", "Remote (US)"))
        self.assertFalse(js.passes_location("United States", "BIM Manager", "In our Austin office.", "Remote (US)"))
        # a Twin Cities firm keeps the old reading: an unread place is assumed local
        self.assertTrue(js.passes_location("Somewhere Unread", "Project Designer", "", "Minneapolis"))
        self.assertTrue(js.is_msp_location("Indianapolis, IN") is False)

    def test_california_code_is_another_state(self):
        # WAS "CA" missing from NON_MN_STATES: HGA's San Francisco and San Jose postings passed.
        for loc in ("San Francisco, CA", "San Jose, CA", "Sacramento, CA"):
            self.assertFalse(js.is_msp_location(loc), loc)
        self.assertTrue(js.is_msp_location("Minneapolis, MN; San Francisco, CA"))

    def test_icims_detail_reads_the_posting_frame_not_the_footer(self):
        posting = "Digital Design Support Lead\nJob Locations\nUS-MN-Minneapolis\nBIM, Revit, Dynamo " + "x" * 200
        frames = [types.SimpleNamespace(inner_text=lambda sel: "CAREERS CONTACT US (c) HGA"),
                  types.SimpleNamespace(inner_text=lambda sel: posting)]
        opened = []
        page = types.SimpleNamespace(goto=lambda u, timeout=None: opened.append(u),
                                     wait_for_load_state=lambda *a, **k: None,
                                     wait_for_timeout=lambda ms: None, frames=frames, close=lambda: None)
        browser = types.SimpleNamespace(new_page=lambda: page)
        desc, loc = js.fetch_icims_detail(browser, "https://careers-hga.icims.com/jobs/3483/x/job")
        self.assertIn("Dynamo", desc)
        self.assertEqual(loc, "Minneapolis, MN")
        self.assertTrue(opened[0].endswith("?in_iframe=1"))
        self.assertEqual(js.fetch_icims_detail(None, "u"), ("", ""))

    def test_autodesk_offsitehome_counts_as_remote(self):
        self.assertTrue(js.is_msp_location("AMER - United States - North Carolina - OffsiteHome"))
        self.assertFalse(js.is_msp_location("AMER - United States - Colorado - Denver - Wewatta"))


class DigitalDesignFit(unittest.TestCase):
    # 2026-10-17: HGA's 'Digital Design Support Lead' scored fit 9 on its title alone.
    DESC = ("HGA is seeking a Digital Design Support Lead to join our Digital Practice Group. Are you "
            "passionate about BIM? Troubleshooting across Revit, ACC/BIM 360, Dynamo. Reinforce digital "
            "standards, construction documents and production. A clear career path for technology "
            "professionals, professional development. Hybrid, flexible schedule. Employee-owned.")

    def test_the_lane_job_scores_with_its_text(self):
        with mock.patch.object(js, "_jev_unavailable", True), mock.patch.object(js, "_jev_client", None):
            fit_title, _ = js.fit_score("Digital Design Support Lead")
            fit_full, bd = js.fit_score("Digital Design Support Lead", self.DESC)
        self.assertLess(fit_title, 15)
        self.assertGreaterEqual(fit_full, 45)
        self.assertGreater(bd["tech_leverage"], 6)

    def test_an_unrelated_support_lead_stays_low_on_tech(self):
        with mock.patch.object(js, "_jev_unavailable", True), mock.patch.object(js, "_jev_client", None):
            _, bd = js.fit_score("Customer Support Lead", "Answer phones and route tickets.")
        self.assertEqual(bd["tech_leverage"], 0)


if __name__ == "__main__":
    unittest.main()
