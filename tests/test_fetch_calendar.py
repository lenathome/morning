import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_calendar.py"
sys.path.insert(0, str(SCRIPT.parent))
import fetch_calendar  # noqa: E402


def ev(*emails):
    return {"title": "x", "attendees": [{"name": "", "email": e} for e in emails]}


class MarkExternalTest(unittest.TestCase):
    def test_outside_domain_is_external(self):
        events = [ev("lena.thome@ekko.earth", "liam.quinn@visualsoft.co.uk")]
        fetch_calendar.mark_external(events, "@ekko.earth", [])
        self.assertTrue(events[0]["is_external"])

    def test_internal_contact_is_not_external(self):
        events = [ev("yaw.poku@natwest.com")]
        fetch_calendar.mark_external(events, "@ekko.earth", ["yaw.poku@natwest.com"])
        self.assertFalse(events[0]["is_external"])

    def test_contact_match_ignores_case_and_spaces(self):
        events = [ev("Yaw.Poku@NatWest.com")]
        fetch_calendar.mark_external(events, "@ekko.earth", [" yaw.poku@natwest.com "])
        self.assertFalse(events[0]["is_external"])

    def test_contact_plus_real_external_is_still_external(self):
        events = [ev("yaw.poku@natwest.com", "tim.mawson@visualsoft.co.uk")]
        fetch_calendar.mark_external(events, "@ekko.earth", ["yaw.poku@natwest.com"])
        self.assertTrue(events[0]["is_external"])

    def test_parse_contacts_arg(self):
        self.assertEqual(fetch_calendar.parse_contacts("a@x.com, B@y.com,,"), ["a@x.com", "b@y.com"])
        self.assertEqual(fetch_calendar.parse_contacts(""), [])


if __name__ == "__main__":
    unittest.main()
