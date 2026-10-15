import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.config.loader import load_profile
from app.browser.interface import BrowserError, FieldObservation, FieldReadback, FileReadback, PageObservation
from app.jobs.answer_engine import GeneratedAnswer
from app.browser.interface import SubmitOutcome
from app.jobs.browserskill_greenhouse import UNSUPPORTED_PERSONAL_CLAIMS, company_from_page, run_greenhouse, submit_gate


from tests.support import make_profile
REAL_PROFILE = make_profile()


class BrowserSkillGreenhouseTests(unittest.TestCase):
    url = 'https://job-boards.greenhouse.io/example/jobs/123'

    def field(self, field_id, label, **changes):
        data = dict(field_id=field_id, label=label, field_type='text', name=None, role=None, required=True)
        data.update(changes)
        return FieldObservation(**data)

    def run_flow(self, fields, *, hard_pass=True, score=92, actual='Known', error=None, file_readback=None, upload_error=None, draft=None, mapping=None, submit=False, outcome=None,
                 select=None, select_error=None, checkbox=None, select_hook=None, page_sequence=None):
        browser = Mock()
        browser.observe_page.return_value = PageObservation(url=self.url,
            title='Job Application for Engineer at Example', heading='Engineer', text='Engineer\nRemote', fields=fields)
        if page_sequence:
            def page(i):
                return PageObservation(url=self.url, title='Job Application for Engineer at Example', heading='Engineer',
                                       text='Engineer\nRemote', fields=page_sequence[min(i, len(page_sequence) - 1)])
            browser.observe_page.side_effect = [page(i) for i in range(12)]
        browser.read_field.return_value = FieldReadback(found=True, value=actual)
        browser.read_file.return_value = file_readback or FileReadback(found=True, filenames=[])
        if select_hook:
            browser.select_choice = select_hook
        elif select_error:
            browser.select_choice.side_effect = select_error
        elif select:
            browser.select_choice.return_value = select
        if checkbox:
            browser.set_checkbox.return_value = checkbox
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
                ('load_profile', REAL_PROFILE), ('load_preferences', preferences),
                ('passes_hard_filters', SimpleNamespace(passed=hard_pass,reasons=[])),
                ('score_job', SimpleNamespace(overall_score=score,explanation='Test')),
                ('get_effective_mapping', mapping or SimpleNamespace(status='READY',value='Known')),
                ('generate_application_answer', draft or GeneratedAnswer(answer='', confidence='LOW')),
            ]:
                stack.enter_context(patch(prefix + name, return_value=result))
            try:
                browser.submit_application.return_value = outcome or SubmitOutcome(status='CONFIRMED', detail='ok')
                report = run_greenhouse(browser, self.url, submit=submit)
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

    def test_eeo_decline_is_selected_and_verified(self):
        field = self.field('gender', 'Gender*', role='combobox')
        report = self.run_flow([field], select=FieldReadback(found=True, value="I don't wish to answer"))
        request = self.browser.select_choice.call_args.args[1]
        self.assertTrue(request.no_search)
        self.assertIn("i don't wish to answer", request.labels)
        self.assertEqual(report.verified_count, 1)
        self.assertNotIn('Gender*', report.blocking_items)

    def test_race_is_selected_through_the_policy_and_verified(self):
        field = self.field('race', 'Race/Ethnicity', role='combobox')

        def select(observation, choice):             # what the adapter does: resolve the pick, then select it
            choice.labels = [choice.pick(['White', 'Asian', 'Decline to self identify'])]
            return FieldReadback(found=True, value=choice.labels[0])
        report = self.run_flow([field], select_hook=Mock(side_effect=select))
        self.assertEqual(report.verified_count, 1)
        self.assertNotIn('Race/Ethnicity', report.blocking_items)

    def test_race_with_no_matching_category_is_review_not_decline(self):
        from app.browser.interface import SelectionReview
        field = self.field('race', 'Race/Ethnicity', role='combobox')
        report = self.run_flow([field], select_error=SelectionReview('No listed option satisfies the approved policy'))
        self.assertIn('Race/Ethnicity', report.blocking_items)
        self.assertEqual(report.verified_count, 0)

    def test_fields_revealed_by_an_answer_are_processed_too(self):
        first = self.field('hisp', 'Are you Hispanic/Latino?', role='combobox')
        revealed = self.field('race', 'Please identify your race*', role='combobox')
        pages = [[first], [first, revealed], [first, revealed], [first, revealed], [first, revealed], [first, revealed]]

        def select(observation, choice):
            choice.labels = [choice.pick(['White', 'Asian', 'Yes', 'No'])]
            return FieldReadback(found=True, value=choice.labels[0])
        report = self.run_flow([first], select_hook=Mock(side_effect=select), page_sequence=pages)
        self.assertEqual(self.browser.select_choice.call_count, 2)
        self.assertEqual(report.verified_count, 2)
        self.assertNotIn('Please identify your race*', report.blocking_items)

    def test_generated_cover_letter_file_blocks_the_submit_gate(self):
        field = self.field('cover_letter', 'Cover Letter*', field_type='file')
        with patch('app.jobs.browserskill_greenhouse.generate_cover_letter', return_value='Dear team. ' * 30), \
                patch('app.jobs.browserskill_greenhouse.write_cover_letter_file', return_value=__import__('pathlib').Path('/tmp/cl.txt')), \
                patch('app.jobs.browserskill_greenhouse.submit_gate', wraps=submit_gate) as gate:
            report = self.run_flow([field], file_readback=FileReadback(found=True, filenames=['cl.txt']), submit=True)
        generated = gate.call_args.args[2]
        self.assertEqual([label for label, _ in generated], ['Cover Letter*'])    # the gate saw generated content
        self.browser.submit_application.assert_not_called()
        self.assertEqual(report.submission, 'SKIPPED')

    def test_eeo_without_decline_option_is_review(self):
        from app.browser.interface import SelectionReview
        field = self.field('gender', 'Gender*', role='combobox')
        report = self.run_flow([field], select_error=SelectionReview('No unique enabled matching option'))
        self.assertEqual(report.verified_count, 0)
        self.assertIn('Gender*', report.blocking_items)

    def test_eligible_consent_checkbox_is_ticked_and_verified(self):
        field = self.field('privacy', 'By clicking this box and submitting your application, you consent to our Applicant Privacy Statement.',
                           field_type='checkbox')
        report = self.run_flow([field], checkbox=FieldReadback(found=True, value='checked'))
        self.browser.set_checkbox.assert_called_once()
        self.assertEqual(report.verified_count, 1)
        self.assertNotIn(field.label, report.blocking_items)

    def test_ineligible_consent_checkbox_is_never_ticked(self):
        for label in ('I agree to receive marketing emails and text messages about future opportunities.',
                      'I consent to my data being shared with third parties.',
                      'I do not consent to the processing of my personal data.'):
            with self.subTest(label=label):
                field = self.field('bg', label, field_type='checkbox')
                report = self.run_flow([field])
                self.browser.set_checkbox.assert_not_called()
                self.assertIn(label, report.blocking_items)

    def test_approved_background_check_and_certification_are_ticked(self):
        for label in ('You consent to third-party background checks as part of your application process.',
                      'I certify that all information provided is true and complete.',
                      'I agree to resolve any disputes through binding arbitration.'):
            with self.subTest(label=label):
                field = self.field('c', label, field_type='checkbox')
                report = self.run_flow([field], checkbox=FieldReadback(found=True, value='checked'))
                self.browser.set_checkbox.assert_called_once()
                self.assertEqual(report.verified_count, 1)

    def test_unverified_checkbox_fails_readiness(self):
        field = self.field('privacy', 'I have read and acknowledge the Candidate Privacy Notice.', field_type='checkbox')
        report = self.run_flow([field], checkbox=FieldReadback(found=True, value='unchecked'))
        self.assertEqual(report.failed_count, 1)
        self.assertEqual(report.status, 'NOT_READY')

    def test_company_name_extraction(self):
        url = 'https://job-boards.greenhouse.io/bitgo/jobs/8880855002'
        self.assertEqual(company_from_page('Job Application for Senior Data Engineer at BitGo', url), 'BitGo')
        self.assertEqual(company_from_page('Job Application for Engineer at Gusto, Inc.', url), 'Gusto, Inc.')
        self.assertEqual(company_from_page('Job Application for Engineer at Foo at Gusto, Inc.', url), 'Gusto, Inc.')
        for title in ('page_title', '', 'Unknown', 'Job Application for Senior Data Engineer at page_title',
                      'Job Application for Senior Data Engineer'):
            with self.subTest(title=title):
                self.assertEqual(company_from_page(title, url), 'Bitgo')
        self.assertEqual(company_from_page('page_title', 'https://job-boards.greenhouse.io/included-health/jobs/1'),
                         'Included Health')

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

    essay = lambda self: self.field('question_1', 'Tell us about your relationship with sports?', field_type='textarea')
    unmapped = SimpleNamespace(status='REVIEW', value=None)

    def test_grounded_high_confidence_essay_is_filled_and_verified(self):
        text = 'This role aligns with my experience building regulatory reporting pipelines.'
        report = self.run_flow([self.essay()], actual=text, mapping=self.unmapped,
                               draft=GeneratedAnswer(answer=text, confidence='HIGH'))
        self.browser.fill_text.assert_called_once()
        self.assertEqual(self.browser.fill_text.call_args.args[1], text)
        self.assertEqual(report.verified_count, 1)

    def test_essay_readback_mismatch_is_failed(self):
        report = self.run_flow([self.essay()], actual='different', mapping=self.unmapped,
                               draft=GeneratedAnswer(answer='A safe answer.', confidence='HIGH'))
        self.assertEqual(report.failed_count, 1)
        self.assertEqual(report.status, 'NOT_READY')

    def test_low_or_medium_confidence_essay_is_not_filled(self):
        for confidence in ('LOW', 'MEDIUM'):
            with self.subTest(confidence=confidence):
                report = self.run_flow([self.essay()], mapping=self.unmapped,
                                       draft=GeneratedAnswer(answer='Something.', confidence=confidence))
                self.browser.fill_text.assert_not_called()
                self.assertEqual(report.status, 'NOT_READY')

    def test_draft_with_invented_personal_claims_is_discarded(self):
        for claim in ("I am a huge fan of the sport.", "I play basketball every weekend.",
                      "As an Underdog user I love it.", "Growing up I watched games.", "My favorite team wins."):
            with self.subTest(claim=claim):
                self.run_flow([self.essay()], mapping=self.unmapped,
                              draft=GeneratedAnswer(answer=claim, confidence='HIGH'))
                self.browser.fill_text.assert_not_called()

    def test_claim_filter_allows_grounded_alignment_language(self):
        for ok in ("This role aligns with my experience in Python and dbt.",
                   "I am interested in the opportunity to build reporting pipelines.",
                   "My background in AWS data engineering aligns with the team's needs."):
            self.assertIsNone(UNSUPPORTED_PERSONAL_CLAIMS.search(ok), ok)

    def test_non_textarea_unmapped_fields_never_get_generated_answers(self):
        self.run_flow([self.field('q', 'Why us?')], mapping=self.unmapped,
                      draft=GeneratedAnswer(answer='Fine answer.', confidence='HIGH'))
        self.browser.fill_text.assert_not_called()

    def ready_flow(self, **kw):
        ledger = {}
        with patch('app.jobs.browserskill_greenhouse._ledger', side_effect=lambda: dict(ledger)), \
             patch('app.jobs.browserskill_greenhouse._record', side_effect=lambda u, st: ledger.update({u: st})):
            report = self.run_flow([self.resume()], file_readback=FileReadback(found=True, filenames=['resume.pdf']), **kw)
        return report, ledger

    def test_submit_never_happens_without_the_flag(self):
        report, ledger = self.ready_flow()
        self.browser.submit_application.assert_not_called()
        self.assertEqual((report.status, report.submission, ledger), ('READY', 'NOT_ATTEMPTED', {}))

    def test_strict_gate_submits_once_and_records_ledger_first(self):
        report, ledger = self.ready_flow(submit=True)
        self.browser.submit_application.assert_called_once()
        self.assertEqual(report.submission, 'CONFIRMED')
        self.assertEqual(list(ledger.values()), ['CONFIRMED'])

    def test_unconfirmed_submit_is_reported_not_retried(self):
        report, _ = self.ready_flow(submit=True, outcome=SubmitOutcome(status='UNCONFIRMED', detail='captcha'))
        self.assertEqual(report.submission, 'UNCONFIRMED')
        self.browser.submit_application.assert_called_once()

    def test_review_score_blocks_submit(self):
        report, _ = self.ready_flow(submit=True, score=85)
        self.browser.submit_application.assert_not_called()
        self.assertEqual(report.submission, 'SKIPPED')

    def test_not_ready_blocks_submit(self):
        report = self.run_flow([self.resume(), self.field('salary', 'Current salary')],
                               file_readback=FileReadback(found=True, filenames=['resume.pdf']), submit=True)
        self.browser.submit_application.assert_not_called()
        self.assertEqual(report.submission, 'SKIPPED')

    def test_generated_answer_blocks_submit(self):
        text = 'This role aligns with my experience building pipelines.'
        report = self.run_flow([self.resume(), self.essay()], actual=text, mapping=self.unmapped, submit=True,
                               file_readback=FileReadback(found=True, filenames=['resume.pdf']),
                               draft=GeneratedAnswer(answer=text, confidence='HIGH'))
        self.assertEqual(report.status, 'READY')
        self.browser.submit_application.assert_not_called()
        self.assertEqual(report.submission, 'SKIPPED')

    def test_already_attempted_application_is_never_resubmitted(self):
        with patch('app.jobs.browserskill_greenhouse._ledger', return_value={self.url: 'ATTEMPTING'}):
            report = self.run_flow([self.resume()], file_readback=FileReadback(found=True, filenames=['resume.pdf']),
                                   submit=True)
        self.browser.submit_application.assert_not_called()
        self.assertEqual(report.submission, 'SKIPPED')

    def test_gate_reasons_are_all_reported(self):
        report = SimpleNamespace(status='NOT_READY')
        with patch('app.jobs.browserskill_greenhouse._ledger', return_value={}):
            reasons = submit_gate('REVIEW', report, [('q', 'a')], self.url)
        self.assertEqual(len(reasons), 3)

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
