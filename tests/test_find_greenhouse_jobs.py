import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.find_greenhouse_jobs as find_greenhouse_jobs


class FindGreenhouseJobsTests(unittest.TestCase):
    def test_write_path_writes_selected_jobs_as_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "greenhouse_boards.txt").write_text("example\n", encoding="utf-8")
            job = {
                "id": 123,
                "title": "Data Engineer",
                "location": {"name": "Remote"},
            }
            with (
                patch.object(find_greenhouse_jobs, "ROOT", root),
                patch.object(find_greenhouse_jobs, "seen_ids", return_value=set()),
                patch.object(find_greenhouse_jobs, "fetch_board", return_value=("example", [job])),
                patch.object(find_greenhouse_jobs, "stays_on_greenhouse", return_value=True),
                patch("sys.argv", ["find_greenhouse_jobs.py", "--write", "--count", "1"]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                find_greenhouse_jobs.main()

            output = (root / "data" / "test_jobs.yaml").read_text(encoding="utf-8")
            self.assertIn("company: example", output)
            self.assertIn("Data Engineer", output)
            self.assertIn("https://job-boards.greenhouse.io/example/jobs/123", output)


if __name__ == "__main__":
    unittest.main()
