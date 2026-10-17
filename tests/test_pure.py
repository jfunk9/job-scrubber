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
        for f in envelope + tech:
            self.assertEqual(f["verified"], "no", f["name"])


if __name__ == "__main__":
    unittest.main()
