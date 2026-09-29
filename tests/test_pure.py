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


if __name__ == "__main__":
    unittest.main()
