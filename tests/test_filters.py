import unittest

from app.config.models import Preferences
from app.jobs.filters import passes_hard_filters
from app.jobs.models import Job


class HardFilterTests(unittest.TestCase):
    def preferences(self, allow_clearance=False):
        return Preferences.model_validate({
            "target_roles": [],
            "work_arrangements": {"remote": True, "hybrid": True, "onsite": True},
            "locations": {"preferred": [], "excluded": []},
            "experience": {"maximum_required_years": 7},
            "seniority": {"allowed": [], "excluded": ["Staff"]},
            "employment_types": ["Full Time"],
            "hard_filters": {
                "active_security_clearance_required": allow_clearance,
                "explicit_no_sponsorship": None,
            },
            "scoring": {"auto_apply_minimum": 90, "review_minimum": 80},
        })

    def job(self, clearance=None, **changes):
        values = dict(
            title="Test role", company="Test company", location="Unknown",
            description="Synthetic test job", required_experience_years=None,
            seniority=None, employment_type="Full Time", work_arrangement=None,
            sponsorship_available=None, security_clearance_required=clearance,
            source="test", url="https://example.com/job",
        )
        values.update(changes)
        return Job(**values)

    def test_required_clearance_rejected_when_disallowed(self):
        result = passes_hard_filters(self.job(True), self.preferences())
        self.assertFalse(result.passed)
        self.assertEqual(result.reasons, ["Job requires a security clearance."])

    def test_required_clearance_allowed_when_enabled(self):
        result = passes_hard_filters(self.job(True), self.preferences(True))
        self.assertTrue(result.passed)
        self.assertEqual(result.reasons, [])

    def test_false_or_unknown_clearance_does_not_reject(self):
        for clearance in (False, None):
            with self.subTest(clearance=clearance):
                result = passes_hard_filters(self.job(clearance), self.preferences())
                self.assertTrue(result.passed)

    def test_other_hard_filters_still_reject(self):
        result = passes_hard_filters(
            self.job(True, required_experience_years=8), self.preferences(True),
        )
        self.assertFalse(result.passed)
        self.assertEqual(len(result.reasons), 1)
        self.assertIn("Requires 8 years", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
