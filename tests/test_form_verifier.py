import unittest
from unittest.mock import Mock

from app.browser.browserskill_client import BrowserSkillClient
from app.jobs.form_parser import FormField
from app.jobs.form_verifier import verify_field


class FormVerifierTests(unittest.TestCase):
    def setUp(self):
        self.browser = Mock()
        self.element = Mock()
        self.browser.page.locator.return_value = self.element
        self.element.count.return_value = 1

    def make_field(self, field_type, role=None):
        return FormField(
            label="Test field",
            field_type=field_type,
            name="test-field",
            field_id="test-field",
            role=role,
            required=False,
        )

    def test_native_select_verifies_selected_option_label(self):
        self.element.locator.return_value.inner_text.return_value = "Selected"

        result = verify_field(
            self.browser,
            self.make_field("select"),
            "selected",
        )

        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.actual_value, "Selected")
        self.element.input_value.assert_not_called()

    def test_native_select_read_failure_is_unverified(self):
        self.element.locator.return_value.inner_text.side_effect = RuntimeError

        result = verify_field(
            self.browser,
            self.make_field("select"),
            "selected",
        )

        self.assertEqual(result.status, "UNVERIFIED")
        self.assertIsNone(result.actual_value)

    def test_input_combobox_reads_current_input_value(self):
        self.element.evaluate.return_value = "input"
        self.element.input_value.return_value = "Selected"

        result = verify_field(
            self.browser,
            self.make_field("text", role="combobox"),
            "selected",
        )

        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.actual_value, "Selected")
        self.element.input_value.assert_called_once_with()
        self.element.locator.assert_not_called()

    def test_non_input_combobox_uses_displayed_selected_value(self):
        self.element.evaluate.return_value = "div"
        selected_value = Mock()
        selected_value.count.return_value = 1
        selected_value.inner_text.return_value = "Selected"
        self.element.locator.return_value.locator.return_value = selected_value

        result = verify_field(
            self.browser,
            self.make_field("text", role="combobox"),
            "selected",
        )

        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.actual_value, "Selected")
        self.element.input_value.assert_not_called()

    def test_other_field_types_still_use_input_value(self):
        self.element.input_value.return_value = "Selected"

        result = verify_field(
            self.browser,
            self.make_field("text"),
            "selected",
        )

        self.assertEqual(result.status, "VERIFIED")
        self.element.input_value.assert_called_once_with()


class BrowserSkillClientTests(unittest.TestCase):
    def test_failed_stop_preserves_session_for_retry(self):
        browser = BrowserSkillClient()
        browser.session_id = "session-123"
        browser._run = Mock(side_effect=[RuntimeError, ""])

        with self.assertRaises(RuntimeError):
            browser.close()

        self.assertEqual(browser.session_id, "session-123")

        browser.close()

        self.assertIsNone(browser.session_id)
        self.assertEqual(browser._run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
