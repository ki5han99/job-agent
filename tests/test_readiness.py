import unittest

from app.jobs.form_parser import FormField
from app.jobs.form_verifier import FieldVerification
from app.jobs.readiness import build_readiness_report


def field(field_id="answer", label="Question", required=True):
    return FormField(field_id=field_id, label=label, required=required,
                     field_type="textarea", name=None, role=None)


def verification(field_id="answer", status="VERIFIED"):
    return FieldVerification(field_id=field_id, label="Question",
                             expected_value="answer", actual_value="answer", status=status)


class ReadinessTests(unittest.TestCase):
    def test_skipped_required_textarea_blocks(self):
        report = build_readiness_report([], [], [field()])
        self.assertEqual(report.status, "NOT_READY")
        self.assertIn("Question", report.blocking_items)

    def test_unlabeled_required_field_has_readable_blocker(self):
        report = build_readiness_report([], [], [field(None, "")])
        self.assertEqual(report.status, "NOT_READY")
        self.assertIn("Unlabeled required field #1", report.blocking_items)

    def test_label_match_does_not_verify_different_field(self):
        report = build_readiness_report([verification("other")], [], [field()])
        self.assertEqual(report.status, "NOT_READY")

    def test_verified_required_field_is_ready(self):
        report = build_readiness_report([verification()], [], [field()])
        self.assertEqual(report.status, "READY")
        self.assertEqual(report.verified_count, 1)

    def test_unknown_verification_status_fails_closed(self):
        report = build_readiness_report([verification(status="UNKNOWN")], [], [field()])
        self.assertEqual(report.status, "NOT_READY")
        self.assertEqual(report.failed_count, 1)

    def test_duplicate_ids_cannot_share_one_verification(self):
        report = build_readiness_report([verification()], [], [field(), field()])
        self.assertEqual(report.status, "NOT_READY")

    def test_empty_form_is_not_ready(self):
        self.assertEqual(build_readiness_report([], [], []).status, "NOT_READY")

    def test_optional_review_does_not_fail_required_coverage(self):
        report = build_readiness_report([verification()], [field("cover", "Cover letter", False)],
                                        [field(), field("cover", "Cover letter", False)])
        self.assertEqual(report.status, "READY")
        self.assertEqual(report.blocking_items, [])
        self.assertEqual(report.optional_review_items, ["Cover letter"])
        self.assertEqual(report.optional_review_count, 1)
        self.assertEqual(report.review_count, 0)

    def test_optional_demographics_do_not_block(self):
        demographics = [field("gender", "Gender", False), field("ethnicity", "Ethnicity", False)]
        report = build_readiness_report([verification()], demographics, [field(), *demographics])
        self.assertEqual(report.status, "READY")
        self.assertEqual(report.optional_review_count, 2)
        self.assertEqual(report.blocking_items, [])

    def test_same_label_does_not_confuse_required_and_optional(self):
        required = field("required", "Shared label", True)
        optional = field("optional", "Shared label", False)
        report = build_readiness_report([], [optional], [required, optional])
        self.assertEqual(report.status, "NOT_READY")
        self.assertEqual(report.review_count, 1)
        self.assertEqual(report.optional_review_count, 1)
        self.assertIn("Shared label", report.blocking_items)

    def test_optional_verification_failure_still_blocks(self):
        report = build_readiness_report([verification(status="FAILED")], [], [field(required=False)])
        self.assertEqual(report.status, "NOT_READY")
        self.assertEqual(report.failed_count, 1)

    def test_skipped_optional_textarea_is_reported(self):
        report = build_readiness_report([], [], [field(required=False)])
        self.assertEqual(report.status, "READY")
        self.assertEqual(report.optional_review_items, ["Question"])
