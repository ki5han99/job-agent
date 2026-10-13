import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.browser.interface import BrowserError, FieldObservation, FieldReadback, FileReadback, PageObservation
from app.jobs.browserskill_greenhouse import run_greenhouse


class BrowserSkillGreenhouseTests(unittest.TestCase):
    url = 'https://job-boards.greenhouse.io/example/jobs/123'

    def field(self, field_id, label, **changes):
        data = dict(field_id=field_id, label=label, field_type='text', name=None, role=None, required=True)
        data.update(changes)
        return FieldObservation(**data)

    def run_flow(self, fields, *, hard_pass=True, score=92, actual='Known', error=None, file_readback=None, upload_error=None):
        browser = Mock()
        browser.observe_page.return_value = PageObservation(url=self.url,
            title='Job Application for Engineer at Example', heading='Engineer', text='Engineer\nRemote', fields=fields)
        browser.read_field.return_value = FieldReadback(found=True, value=actual)
        browser.read_file.return_value = file_readback or FileReadback(found=True, filenames=[])
        if upload_error:
            browser.upload_file.side_effect = upload_error
        if error:
            browser.fill_text.side_effect = error
        preferences = SimpleNamespace(scoring=SimpleNamespace(auto_apply_minimum=90,review_minimum=80))
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(StringIO()))
            prefix = 'app.jobs.browserskill_greenhouse.'
            for name, result in [
                ('extract_job', SimpleNamespace(title='Engineer', company='Example')),
                ('load_profile', Mock()), ('load_preferences', preferences),
                ('passes_hard_filters', SimpleNamespace(passed=hard_pass,reasons=[])),
                ('score_job', SimpleNamespace(overall_score=score,explanation='Test')),
                ('get_effective_mapping', SimpleNamespace(status='READY',value='Known')),
            ]:
                stack.enter_context(patch(prefix + name, return_value=result))
            try:
                report = run_greenhouse(browser, self.url)
            finally:
                self.browser = browser
        return report

    def test_only_permitted_text_filled_and_unsupported_required_blocks(self):
        fields = [self.field('first_name','First Name'), self.field('salary','Current salary'),
                  self.field('auth','Are you legally authorized to work in the United States?'),
                  self.field('sponsor','Will you require sponsorship?'),
                  self.field('resume','Resume',field_type='file')]
        report = self.run_flow(fields)
        self.assertEqual(self.browser.fill_text.call_count, 1)
        self.assertEqual(report.verified_count, 1)
        self.assertEqual(report.status,'NOT_READY')
        self.browser.handoff.assert_called_once()
        self.browser.close.assert_not_called()
        self.browser.click.assert_not_called()

    def test_hard_filter_skip_never_mutates(self):
        self.run_flow([self.field('first_name','First Name')],hard_pass=False)
        self.browser.fill_text.assert_not_called()

    def test_score_skip_never_mutates(self):
        self.run_flow([self.field('first_name','First Name')],score=20)
        self.browser.fill_text.assert_not_called()

    def test_readback_mismatch_blocks(self):
        report = self.run_flow([self.field('first_name','First Name')],actual='Different')
        self.assertEqual(report.failed_count,1)
        self.assertEqual(report.status,'NOT_READY')

    def test_disconnect_stops_without_replay_and_hands_off(self):
        with self.assertRaises(BrowserError):
            self.run_flow([self.field('first_name','First Name')],error=BrowserError('Disconnected'))
        self.assertEqual(self.browser.fill_text.call_count,1)
        self.browser.handoff.assert_called_once()

    def test_duplicate_ids_are_never_filled(self):
        report = self.run_flow([self.field('first_name','First Name')]*2)
        self.browser.fill_text.assert_not_called()
        self.assertEqual(report.status,'NOT_READY')

    def test_resume_gap_prevents_ready_even_when_file_not_observed(self):
        report = self.run_flow([self.field('first_name','First Name')])
        self.assertEqual(report.status,'NOT_READY')
        self.assertTrue(any('Resume attachment' in item for item in report.blocking_items))

    resume = lambda self: self.field('resume', 'Resume/CV*', field_type='file')
    cover = lambda self: self.field('cover_letter', 'Cover Letter', field_type='file', required=False)

    def test_resume_uploaded_and_verified_from_input_files(self):
        report = self.run_flow([self.resume()], file_readback=FileReadback(found=True, filenames=['resume.pdf']))
        self.browser.upload_file.assert_called_once()
        self.assertEqual(self.browser.upload_file.call_args.args[1].rsplit('/', 1)[-1], 'resume.pdf')
        self.browser.read_file.assert_called_once()
        self.assertEqual((report.status, report.verified_count), ('READY', 1))

    def test_resume_verified_from_ui_when_input_replaced(self):
        report = self.run_flow([self.resume()], file_readback=FileReadback(found=True, filenames=[], shown_in_ui=True))
        self.assertEqual(report.status, 'READY')

    @patch('app.jobs.browserskill_greenhouse.time.sleep')
    def test_attachment_that_appears_after_rerender_is_verified(self, sleep):
        from app.jobs.browserskill_greenhouse import upload_resume
        browser = Mock()
        browser.read_file.side_effect = [FileReadback(found=True, filenames=[]),
                                         FileReadback(found=True, filenames=[], shown_in_ui=True)]
        field = self.resume()
        with redirect_stdout(StringIO()):
            result = upload_resume(browser, field, field)
        self.assertEqual(result.status, 'VERIFIED')
        browser.upload_file.assert_called_once()
        sleep.assert_called_once()

    @patch('app.jobs.browserskill_greenhouse.time.sleep')
    def test_upload_success_without_attachment_is_not_verified(self, sleep):
        report = self.run_flow([self.resume()])
        self.assertEqual(report.status, 'NOT_READY')
        self.assertEqual(report.failed_count, 1)

    def test_upload_error_leaves_required_resume_for_review(self):
        report = self.run_flow([self.resume()], upload_error=BrowserError('Not allowed'))
        self.browser.read_file.assert_not_called()
        self.assertEqual(report.status, 'NOT_READY')
        self.assertIn('Resume/CV*', report.blocking_items)

    def test_optional_cover_letter_is_never_uploaded_and_non_blocking(self):
        report = self.run_flow([self.resume(), self.cover()],
                               file_readback=FileReadback(found=True, filenames=['resume.pdf']))
        self.assertEqual(self.browser.upload_file.call_count, 1)
        self.assertEqual(report.status, 'READY')
        self.assertEqual(report.optional_review_items, ['Cover Letter'])

    def test_submit_is_never_clicked(self):
        self.run_flow([self.resume()], file_readback=FileReadback(found=True, filenames=['resume.pdf']))
        self.browser.click.assert_not_called()


class BrowserSelectionTests(unittest.TestCase):
    def test_browser_skill_is_default_and_url_override_survives(self):
        from main import parse_options
        options = parse_options(['https://example.com/jobs/1'])
        self.assertEqual(options.browser, 'browserskill')
        self.assertEqual(options.job_url, 'https://example.com/jobs/1')

    def test_explicit_playwright_uses_existing_runtime(self):
        from main import main
        with patch('main.run_playwright') as run:
            main('https://example.com/jobs/1', 'playwright')
            run.assert_called_once_with('https://example.com/jobs/1')

    def test_partial_attach_arguments_rejected(self):
        from main import parse_options
        with redirect_stdout(StringIO()), patch('sys.stderr', new_callable=StringIO):
            with self.assertRaises(SystemExit):
                parse_options(['--session','test'])

    def test_backend_failure_does_not_fall_back(self):
        from main import main
        with patch('app.jobs.browserskill_greenhouse.run_greenhouse', side_effect=BrowserError('Lost session')):
            with patch('main.run_playwright') as fallback, redirect_stdout(StringIO()):
                with self.assertRaises(BrowserError):
                    main('https://example.com/jobs/1')
                fallback.assert_not_called()
