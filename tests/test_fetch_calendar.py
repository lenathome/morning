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


class MarkPersonalTest(unittest.TestCase):
    RULES = [{"title": "Catch up", "with": "yaw.poku@natwest.com"}]

    def personal(self, title, *emails, rules=None):
        e = ev(*emails)
        e["title"] = title
        events = [e]
        fetch_calendar.mark_external(events, "@ekko.earth", [])
        fetch_calendar.mark_personal(events, self.RULES if rules is None else rules)
        return events[0]

    def test_match_is_personal_even_with_an_extra_external_guest(self):
        e = self.personal("Catch up", "yaw.poku@natwest.com", "someone@visualsoft.co.uk")
        self.assertTrue(e["is_personal"])
        self.assertFalse(e["is_external"])

    def test_title_match_ignores_case_and_extra_words(self):
        self.assertTrue(self.personal("NatWest catch up (bi-weekly)", "Yaw.Poku@NatWest.com")["is_personal"])

    def test_same_title_with_someone_else_stays_external(self):
        e = self.personal("Catch up", "someone@visualsoft.co.uk")
        self.assertFalse(e["is_personal"])
        self.assertTrue(e["is_external"])

    def test_same_attendee_other_title_stays_external(self):
        self.assertTrue(self.personal("Pricing call", "yaw.poku@natwest.com")["is_external"])

    def test_title_only_rule_and_no_rules(self):
        self.assertTrue(self.personal("Dentist", "x@y.com", rules=[{"title": "dentist"}])["is_personal"])
        e = self.personal("Catch up", "yaw.poku@natwest.com", rules=[])
        self.assertFalse(e["is_personal"])
        self.assertTrue(e["is_external"])

    def test_parse_personal_arg(self):
        self.assertEqual(fetch_calendar.parse_personal(""), [])
        self.assertEqual(fetch_calendar.parse_personal('[{"title": "Catch up"}]'), [{"title": "Catch up"}])
        for bad in ("not json", "{}", "[{}]", '["Catch up"]'):
            with self.assertRaises(ValueError):
                fetch_calendar.parse_personal(bad)


if __name__ == "__main__":
    unittest.main()
