import unittest

from app.jobs.greenhouse import validate_greenhouse_job_page


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
