import unittest
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

from app.jobs.form_parser import parse_form_fields
from app.jobs.form_verifier import FieldVerification
from app.jobs.readiness import build_readiness_report


def widget(field_id, label):
    return f'''<label for="{field_id}">{label}</label>
    <div class="select-shell">
      <input id="{field_id}" role="combobox" type="text" aria-required="true">
      <input required tabindex="-1" aria-hidden="true" value="">
    </div>'''


class FormParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def parse(self, html):
        self.page.set_content(html)
        return parse_form_fields(SimpleNamespace(page=self.page))

    def test_combobox_validation_proxy_is_not_a_second_field(self):
        fields = self.parse(widget("country", "Country*"))
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].field_id, "country")
        self.assertTrue(fields[0].required)

    def test_named_combobox_validation_proxy_is_not_a_missing_field(self):
        html = widget("country", "Country*").replace(
            '<input required tabindex="-1" aria-hidden="true" value="">',
            '<input name="country" required tabindex="-1" aria-hidden="true" value="">',
        )
        fields = self.parse(html)
        report = build_readiness_report(
            [
                FieldVerification(
                    field_id="country",
                    label="Country",
                    expected_value="US",
                    actual_value="US",
                    status="VERIFIED",
                )
            ],
            [],
            fields,
        )
        self.assertEqual(len(fields), 1)
        self.assertEqual(report.status, "READY")
        self.assertEqual(report.blocking_items, [])

    def test_multiple_widgets_stay_distinct(self):
        fields = self.parse(widget("country", "Country*") + widget("state", "State*"))
        self.assertEqual([field.field_id for field in fields], ["country", "state"])

    def test_standalone_unlabeled_required_input_is_preserved(self):
        fields = self.parse('<input required>')
        self.assertEqual(len(fields), 1)
        self.assertEqual(build_readiness_report([], [], fields).status, "NOT_READY")

    def test_proxy_without_observed_labeled_widget_is_preserved(self):
        fields = self.parse('''<div class="select-shell">
            <input required tabindex="-1" aria-hidden="true">
        </div>''')
        self.assertEqual(len(fields), 1)

    def test_unmarked_input_in_widget_is_preserved(self):
        fields = self.parse(widget("country", "Country*").replace('tabindex="-1" aria-hidden="true"', ''))
        self.assertEqual(len(fields), 2)

    def test_hidden_and_search_inputs_remain_ignored(self):
        fields = self.parse('<input type="hidden"><input type="search"><textarea id="answer" required></textarea>')
        self.assertEqual([field.field_id for field in fields], ["answer"])
