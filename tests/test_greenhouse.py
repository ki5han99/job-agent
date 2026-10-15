import unittest
from unittest.mock import Mock, patch

from app.jobs.greenhouse import (
    extract_greenhouse_job,
    validate_greenhouse_job_page,
)


class GreenhousePageTests(unittest.TestCase):
    url = "https://job-boards.greenhouse.io/example/jobs/123"

    def test_specific_job_is_accepted(self):
        validate_greenhouse_job_page(self.url, self.url, "Data Engineer")

    def test_tracking_query_and_trailing_slash_are_accepted(self):
        validate_greenhouse_job_page(self.url + "?source=test", self.url + "/", "Data Engineer")

    def test_redirect_to_board_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_greenhouse_job_page(self.url, "https://job-boards.greenhouse.io/example", "Current openings at Example")

    def test_listings_at_original_url_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_greenhouse_job_page(self.url, self.url, "Current openings at Example")

    def test_different_job_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_greenhouse_job_page(self.url, self.url + "4", "Data Engineer")

    def test_board_url_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_greenhouse_job_page("https://job-boards.greenhouse.io/example", "https://job-boards.greenhouse.io/example", "Example")

    def test_unsupported_requested_host_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_greenhouse_job_page(
                "https://example.com/example/jobs/123",
                "https://example.com/example/jobs/123",
                "Data Engineer",
            )

    def test_unsupported_actual_host_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_greenhouse_job_page(
                self.url,
                "https://example.com/example/jobs/123",
                "Data Engineer",
            )

    def test_supported_greenhouse_hosts_are_accepted(self):
        url = "https://boards.greenhouse.io/example/jobs/123"
        validate_greenhouse_job_page(url, url, "Data Engineer")

    def test_unknown_title_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_greenhouse_job_page(self.url, self.url, "Unknown")

    @patch("app.jobs.greenhouse.extract_job")
    def test_empty_page_is_rejected_before_job_extraction(self, extract_job_mock):
        browser = Mock()
        browser.page.url = self.url
        browser.page.locator.return_value.count.return_value = 0
        browser.get_text.return_value = ""

        with self.assertRaises(ValueError):
            extract_greenhouse_job(browser, self.url)

        extract_job_mock.assert_not_called()
