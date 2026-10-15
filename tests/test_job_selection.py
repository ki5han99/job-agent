import unittest
from unittest.mock import patch

from pathlib import Path

from app.config.loader import load_default_test_job_url, load_test_job_urls
from main import parse_job_url


FIXTURE = Path(__file__).parent / "fixtures" / "test_jobs.yaml"


class JobSelectionTests(unittest.TestCase):
    def test_no_argument_reads_yaml_default(self):
        with patch(
            "app.config.loader.yaml.safe_load",
            return_value={
                "default_job": "chosen",
                "jobs": {
                    "chosen": {
                        "company": "Example",
                        "title": "Test role",
                        "url": "https://example.com/jobs/123",
                    },
                },
            },
        ):
            self.assertEqual(parse_job_url([]), "https://example.com/jobs/123")

    def test_explicit_url_does_not_read_default(self):
        with patch(
            "main.load_default_test_job_url",
            side_effect=AssertionError("Unexpected config read"),
        ):
            self.assertEqual(
                parse_job_url(["https://example.com/jobs/456"]),
                "https://example.com/jobs/456",
            )

    def test_missing_default_or_url_is_rejected(self):
        configs = (
            None,
            {},
            {"default_job": "missing", "jobs": {}},
            {
                "default_job": "chosen",
                "jobs": {
                    "chosen": {
                        "company": "Example",
                        "title": "Test role",
                        "url": " ",
                    },
                },
            },
        )
        for config in configs:
            with self.subTest(config=config):
                with patch(
                    "app.config.loader.yaml.safe_load",
                    return_value=config,
                ):
                    with self.assertRaises(ValueError):
                        load_default_test_job_url()

    def test_fixture_config_selects_garner(self):
        # A frozen fixture, so rotating data/test_jobs.yaml batches cannot break this.
        self.assertEqual(
            load_default_test_job_url(FIXTURE),
            "https://job-boards.greenhouse.io/garnerhealth/jobs/6181548004",
        )
        self.assertEqual(len(load_test_job_urls(FIXTURE)), 1)

    def test_live_batch_config_is_well_formed(self):
        # Content-agnostic: whatever batch is loaded must parse and its default must resolve.
        urls = load_test_job_urls()
        self.assertTrue(urls)
        self.assertIn(load_default_test_job_url(), urls)
