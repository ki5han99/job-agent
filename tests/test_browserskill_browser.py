import unittest
from unittest.mock import Mock, patch

from app.browser.browserskill_browser import BrowserSkillBrowser, PAGE_QUERY
from app.browser.interface import BrowserError, ChoiceRequest, FieldObservation, FieldReadback, SelectionReview


class BrowserSkillBrowserTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(session_id='test', tab_id=42)
        self.browser = BrowserSkillBrowser(self.client)
        self.field = FieldObservation(label='First Name', field_type='text', name=None,
                                      field_id='first_name', role=None, required=True)
        self.page = dict(url='https://example.com/jobs/1', title='Job', heading='Engineer', text='',
                         fields=[self.field.model_dump()])

    def test_incomplete_observation_stops(self):
        self.client.evaluate_readonly.return_value = {'fields':[]}
        with self.assertRaises(BrowserError):
            self.browser.observe_page()

    def test_attach_checks_url_before_any_fill(self):
        self.client.evaluate_readonly.return_value = self.page
        with self.assertRaises(BrowserError):
            self.browser.attach('test', 42, 'https://example.com/jobs/2')
        self.client.fill.assert_not_called()

    def test_combobox_fill_is_rejected(self):
        with self.assertRaises(BrowserError):
            self.browser.fill_text(self.field.model_copy(update={'role':'combobox'}), 'Yes')
        self.client.fill.assert_not_called()

    def test_text_fill_preflight_then_readback(self):
        self.client.evaluate_readonly.side_effect = [self.page, self.page, {'found':True,'value':''}]
        self.browser.fill_text(self.field, 'Known')
        self.client.fill.assert_called_once_with('[id="first_name"]', 'Known')
        self.client.evaluate_readonly.side_effect = [self.page, {'found':True,'value':'Known'}]
        self.assertEqual(self.browser.read_field(self.field).value, 'Known')

    def test_textarea_is_fillable_and_readable(self):
        area = FieldObservation(label='Essay', field_type='textarea', name=None, field_id='q1', role=None, required=True)
        page = dict(self.page, fields=[area.model_dump()])
        self.client.evaluate_readonly.side_effect = [page, page, {'found': True, 'value': ''}]
        self.browser.fill_text(area, 'hi')
        self.client.fill.assert_called_once_with('[id="q1"]', 'hi')
        self.client.evaluate_readonly.side_effect = [page, {'found': True, 'value': 'hi'}]
        self.assertEqual(self.browser.read_field(area).value, 'hi')
        # the readback JS must accept TEXTAREA elements, not just INPUT
        query = self.client.evaluate_readonly.call_args_list[-1].args[0]
        self.assertIn("el.tagName === 'TEXTAREA'", query)

    def test_ambiguous_or_missing_field_is_not_filled(self):
        self.client.evaluate_readonly.side_effect = [self.page, self.page, {'found':False,'value':None}]
        with self.assertRaises(BrowserError):
            self.browser.fill_text(self.field, 'Known')
        self.client.fill.assert_not_called()

    def test_handoff_never_stops_session(self):
        self.assertIn('test', self.browser.handoff())
        self.client.close.assert_not_called()


class BrowserSkillObservationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_normalized_dom_query_preserves_required_and_optional_fields(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content('''<h1>Engineer</h1><label for="country">Country*</label>
            <div class="select-shell"><input id="country" role="combobox" aria-required="true">
            <input required aria-hidden="true" tabindex="-1"></div>
            <label for="gender">Gender</label><select id="gender"><option>Unknown</option></select>
            <input required><input type="submit" value="Submit"><input type="hidden">''')
        observation = page.evaluate(PAGE_QUERY)
        fields = observation['fields']
        self.assertEqual(len(fields), 3)
        self.assertEqual(fields[0]['field_id'], 'country')
        self.assertTrue(fields[0]['required'])
        self.assertEqual(fields[1]['label'], 'Gender')
        self.assertFalse(fields[1]['required'])
        self.assertIsNone(fields[2]['field_id'])
        self.assertTrue(fields[2]['required'])

    def test_readback_uses_committed_selection_not_search_text(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content('''<label for="auth">Authorization</label><div class="select-shell">
            <span class="select__single-value">No</span>
            <input id="auth" role="combobox" aria-expanded="false" value="Yes"></div>''')
        client = Mock()
        client.evaluate_readonly.side_effect = page.evaluate
        browser = BrowserSkillBrowser(client)
        field = browser.observe_page().fields[0]
        self.assertEqual(browser.read_field(field).value,'No')
        page.locator('#auth').evaluate("el => el.setAttribute('aria-expanded','true')")
        self.assertIsNone(browser.read_field(field).value)

    def test_options_must_belong_to_controlled_listbox(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content('''<label for="auth">Authorization</label><div class="select-shell">
            <input id="auth" role="combobox" aria-expanded="true" aria-controls="owned"></div>
            <div id="other" role="listbox"><div id="wrong" role="option">Yes</div></div>
            <div id="owned" role="listbox"><div id="right" role="option">No</div></div>''')
        client = Mock()
        client.evaluate_readonly.side_effect = page.evaluate
        browser = BrowserSkillBrowser(client)
        options = browser._combo_state(browser.observe_page().fields[0])['options']
        self.assertEqual([option['id'] for option in options],['right'])


class ComboboxSelectionTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.browser = BrowserSkillBrowser(self.client)
        self.field = FieldObservation(label='Authorization',field_type='text',name=None,
                                      field_id='observed',role='combobox',required=True)
        self.choice = ChoiceRequest(search='Yes',labels=['Yes'])
        self.option = dict(id='option1',label='Yes',country_code=None,unique=True,disabled=False,listbox_id='owned')

    def state(self, options):
        return {'found':True,'options':options}

    def test_unique_option_click_and_committed_readback(self):
        self.browser.read_field = Mock(side_effect=[FieldReadback(found=True,value=None),FieldReadback(found=True,value='Yes')])
        self.browser._combo_state = Mock(return_value=self.state([self.option]))
        result = self.browser.select_choice(self.field,self.choice)
        self.assertEqual(result.value,'Yes')
        self.assertEqual(self.client.click.call_count,2)
        self.assertIn('[role="option"]',self.client.click.call_args.args[0])
        self.client.fill.assert_not_called()

    def test_ambiguous_options_never_click_option(self):
        self.browser.read_field = Mock(return_value=FieldReadback(found=True,value=None))
        self.browser._combo_state = Mock(return_value=self.state([self.option,self.option | {'id':'option2'}]))
        with self.assertRaises(SelectionReview):
            self.browser.select_choice(self.field,self.choice)
        self.assertEqual(self.client.click.call_count,1)

    def test_identical_duplicate_place_rows_pick_the_first_only_when_allowed(self):
        city = self.option | {'label': 'Seattle, Washington, United States', 'id': 'o0'}
        dup = city | {'id': 'o1'}
        choice = ChoiceRequest(search='Seattle', labels=['Seattle, Washington, United States'], identical_duplicates_ok=True)
        self.browser.read_field = Mock(side_effect=[FieldReadback(found=True, value=None),
                                                    FieldReadback(found=True, value='Seattle, Washington, United States')])
        self.browser._combo_state = Mock(return_value=self.state([city, dup]))
        self.browser.select_choice(self.field, choice)
        self.assertIn('o0', self.client.click.call_args.args[0])

    def test_different_place_labels_or_unflagged_duplicates_stay_review(self):
        a = self.option | {'label': 'Seattle, Washington, United States', 'id': 'o0'}
        for options, allowed in (([a, a | {'id': 'o1'}], False),
                                 ([a, a | {'id': 'o1', 'label': 'Seattle, Washington, United States '.replace('Wash', 'Wash')}], False)):
            with self.subTest(allowed=allowed):
                choice = ChoiceRequest(search='Seattle', labels=[a['label']], identical_duplicates_ok=allowed)
                self.browser.read_field = Mock(return_value=FieldReadback(found=True, value=None))
                self.browser._combo_state = Mock(return_value=self.state(options))
                with self.assertRaises(SelectionReview):
                    self.browser.select_choice(self.field, choice)
        self.assertFalse([c for c in self.client.click.call_args_list if 'option' in c.args[0] and 'o0' in c.args[0]])

    def test_failed_selection_closes_the_dropdown(self):
        self.browser.read_field = Mock(return_value=FieldReadback(found=True, value=None))
        self.browser._combo_state = Mock(return_value=self.state([self.option, self.option | {'id': 'option2'}]))
        with self.assertRaises(SelectionReview):
            self.browser.select_choice(self.field, self.choice)
        self.client.press.assert_called_once_with('Escape', '[id="observed"]')

    def test_missing_options_poll_readonly_then_review(self):
        self.browser.read_field = Mock(return_value=FieldReadback(found=True,value=None))
        self.browser._combo_state = Mock(return_value=self.state([]))
        with patch('app.browser.browserskill_browser.time.sleep'):
            with self.assertRaises(SelectionReview):
                self.browser.select_choice(self.field,self.choice)
        self.client.fill.assert_called_once()
        self.assertEqual(self.client.click.call_count,1)

    def test_async_options_are_selected_after_observation(self):
        self.browser.read_field = Mock(side_effect=[FieldReadback(found=True,value=None),FieldReadback(found=True,value='Yes')])
        self.browser._combo_state = Mock(side_effect=[self.state([]),self.state([]),self.state([self.option]),self.state([self.option])])
        with patch('app.browser.browserskill_browser.time.sleep'):
            self.browser.select_choice(self.field,self.choice)
        self.client.fill.assert_called_once()

    def test_mismatched_readback_is_not_verified(self):
        self.browser.read_field = Mock(return_value=FieldReadback(found=True,value='No'))
        self.browser._combo_state = Mock(return_value=self.state([self.option]))
        with patch('app.browser.browserskill_browser.time.sleep'):
            with self.assertRaises(SelectionReview):
                self.browser.select_choice(self.field,self.choice)

    def test_commit_landing_after_polling_window_is_still_verified(self):
        self.browser.read_field = Mock(side_effect=[FieldReadback(found=True, value=None)] + [
            FieldReadback(found=True, value='No')] * 24 + [FieldReadback(found=True, value=self.choice.labels[0])])
        self.browser._combo_state = Mock(return_value=self.state([self.option]))
        with patch('app.browser.browserskill_browser.time.sleep'):
            got = self.browser.select_choice(self.field, self.choice)
        self.assertEqual(got.value, self.choice.labels[0])

    def test_stale_option_does_not_get_clicked(self):
        self.browser.read_field = Mock(return_value=FieldReadback(found=True,value=None))
        self.browser._combo_state = Mock(side_effect=[self.state([self.option]),self.state([self.option]),self.state([])])
        with self.assertRaises(SelectionReview):
            self.browser.select_choice(self.field,self.choice)
        self.assertEqual(self.client.click.call_count,1)

    def test_phone_country_requires_country_identity_not_calling_code(self):
        choice = ChoiceRequest(search='United States',labels=['United States'],country_code='us')
        self.assertFalse(self.browser._matches(choice,'+1','ca'))
        self.assertFalse(self.browser._matches(choice,'+1',None))
        self.assertTrue(self.browser._matches(choice,'+1','us'))

    def test_country_option_is_clicked_by_flag_identity(self):
        choice = ChoiceRequest(search='United States', labels=['United States'], country_code='us')
        option = dict(self.option, id='react-select-country-option-0', label='United States +1', country_code='us')
        self.browser.read_field = Mock(side_effect=[FieldReadback(found=True, value=None)] +
                                       [FieldReadback(found=True, value='+1', country_code='us')])
        self.browser._combo_state = Mock(return_value=self.state([option]))
        self.browser.select_choice(self.field, choice)
        selector = self.client.click.call_args.args[0]
        self.assertTrue(selector.endswith(':has(.iti__flag.iti__us)'), selector)

    def test_wrong_committed_value_is_reselected_exactly_once(self):
        wrong = FieldReadback(found=True, value='No')
        self.browser.read_field = Mock(side_effect=[FieldReadback(found=True, value=None)] + [wrong] * 25 + [
            wrong, FieldReadback(found=True, value='Yes')] )
        self.browser._combo_state = Mock(return_value=dict(self.state([self.option]), selected='No'))
        # first attempt: wrong value committed -> one retry that succeeds
        with patch('app.browser.browserskill_browser.time.sleep'):
            got = self.browser.select_choice(self.field, self.choice)
        self.assertEqual(got.value, 'Yes')
        option_clicks = [c for c in self.client.click.call_args_list if 'option' in c.args[0]]
        self.assertEqual(len(option_clicks), 2)

    def test_uncommitted_failure_is_retried_exactly_once(self):
        # A click lost to a re-render commits nothing. One more verified attempt is allowed (the retry
        # re-reads the current value first, so a late commit is never double-clicked); never a third.
        self.browser.read_field = Mock(return_value=FieldReadback(found=True, value=None))
        self.browser._combo_state = Mock(return_value=dict(self.state([self.option]), selected=None))
        with patch('app.browser.browserskill_browser.time.sleep'):
            with self.assertRaises(SelectionReview):
                self.browser.select_choice(self.field, self.choice)
        option_clicks = [c for c in self.client.click.call_args_list if 'option' in c.args[0]]
        self.assertEqual(len(option_clicks), 2)


class FileUploadTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(session_id='test', tab_id=42)
        self.browser = BrowserSkillBrowser(self.client)
        self.field = FieldObservation(label='Resume/CV*', field_type='file', name=None,
                                      field_id='resume', role=None, required=True)
        self.page = dict(url='https://example.com/jobs/1', title='Job', heading='Engineer', text='',
                         fields=[self.field.model_dump()])
        import tempfile, os
        handle, self.path = tempfile.mkstemp(suffix='.pdf')
        os.close(handle)
        self.addCleanup(os.unlink, self.path)

    def test_page_query_uses_upload_group_label_and_required(self):
        self.assertIn("closest('[role=\"group\"][aria-labelledby]')", PAGE_QUERY)
        self.assertIn("group?.getAttribute('aria-required')", PAGE_QUERY)

    def test_upload_targets_only_the_attach_button(self):
        self.client.evaluate_readonly.side_effect = [self.page, {'count': 1, 'text': 'Attach', 'inputs': 1}]
        self.browser.upload_file(self.field, self.path)
        selector, sent = self.client.upload.call_args.args
        self.assertEqual(selector, 'div:has(> input[id="resume"][type="file"]) > button')
        self.assertEqual(sent, self.path)

    def test_unsupported_picker_falls_back_to_one_drop_delivery_to_the_owning_wrapper(self):
        unsupported = BrowserError("BrowserSkill 'upload' exited 1: unsupported; upload trigger did not activate an input[type=file]")
        self.client.evaluate_readonly.side_effect = [self.page, {'count': 1, 'text': 'Attach', 'inputs': 1}, {'count': 1}]
        self.client.upload.side_effect = [unsupported, None]
        self.browser.upload_file(self.field, self.path)
        self.assertEqual(self.client.upload.call_count, 2)
        selector, sent = self.client.upload.call_args.args
        self.assertEqual(selector, 'div:has(> input[id="resume"][type="file"])')
        self.assertEqual(self.client.upload.call_args.kwargs, {'mode': 'drop'})

    def test_drop_fallback_needs_one_unambiguous_wrapper_and_only_for_unsupported_errors(self):
        unsupported = BrowserError("BrowserSkill 'upload' exited 1: unsupported; ...")
        self.client.evaluate_readonly.side_effect = [self.page, {'count': 1, 'text': 'Attach', 'inputs': 1}, {'count': 2}]
        self.client.upload.side_effect = unsupported
        with self.assertRaises(SelectionReview):
            self.browser.upload_file(self.field, self.path)
        self.assertEqual(self.client.upload.call_count, 1)                    # no drop delivered to an ambiguous target
        self.client.upload.reset_mock()
        self.client.evaluate_readonly.side_effect = [self.page, {'count': 1, 'text': 'Attach', 'inputs': 1}]
        self.client.upload.side_effect = BrowserError("BrowserSkill 'upload' exited 1: timeout")
        with self.assertRaises(BrowserError):
            self.browser.upload_file(self.field, self.path)
        self.assertEqual(self.client.upload.call_count, 1)                    # other failures are never retried

    def test_non_attach_or_ambiguous_trigger_is_not_used(self):
        for info in ({'count': 4, 'text': 'Attach', 'inputs': 1}, {'count': 1, 'text': 'Dropbox', 'inputs': 1},
                     {'count': 1, 'text': 'Attach', 'inputs': 2}):
            self.client.evaluate_readonly.side_effect = [self.page, info]
            with self.assertRaises(SelectionReview):
                self.browser.upload_file(self.field, self.path)
        self.client.upload.assert_not_called()

    def test_missing_relative_or_changed_inputs_never_upload(self):
        with self.assertRaises(BrowserError):
            self.browser.upload_file(self.field, 'relative/resume.pdf')
        with self.assertRaises(BrowserError):
            self.browser.upload_file(self.field, '/does/not/exist.pdf')
        self.client.evaluate_readonly.return_value = dict(self.page, fields=[])
        with self.assertRaises(BrowserError):
            self.browser.upload_file(self.field, self.path)
        self.client.upload.assert_not_called()

    def test_text_field_is_not_a_file_field(self):
        text = self.field.model_copy(update={'field_type': 'text'})
        self.client.evaluate_readonly.return_value = dict(self.page, fields=[text.model_dump()])
        with self.assertRaises(SelectionReview):
            self.browser.upload_file(text, self.path)

    def test_readback_from_input_files_and_ui_text(self):
        self.client.evaluate_readonly.return_value = {'found': True, 'filenames': ['resume.pdf'], 'text': 'x'}
        got = self.browser.read_file(self.field, 'resume.pdf')
        self.assertEqual((got.found, got.filenames, got.shown_in_ui), (True, ['resume.pdf'], False))
        self.client.evaluate_readonly.return_value = {'found': True, 'filenames': [], 'text': 'Resume/CV*\nresume.pdf\nRemove'}
        self.assertTrue(self.browser.read_file(self.field, 'resume.pdf').shown_in_ui)

    def test_empty_chooser_is_not_attached(self):
        self.client.evaluate_readonly.return_value = {'found': True, 'filenames': [], 'text': 'Resume/CV*\nAttach'}
        got = self.browser.read_file(self.field, 'resume.pdf')
        self.assertEqual((got.filenames, got.shown_in_ui), ([], False))

    def test_invalid_readback_stops(self):
        self.client.evaluate_readonly.return_value = 'nope'
        with self.assertRaises(BrowserError):
            self.browser.read_file(self.field, 'resume.pdf')


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(session_id='test', tab_id=42)
        self.browser = BrowserSkillBrowser(self.client)
        self.page = dict(url='https://example.com/jobs/1', title='Job', heading='H', text='', fields=[])
        self.browser.expected_url = self.page['url']
        self.button = {'count': 1, 'visible': 1, 'text': 'Submit application', 'disabled': False}

    def run_submit(self, texts):
        self.client.evaluate_readonly.side_effect = [self.button, self.page] + [{'text': t} for t in texts]
        with patch('app.browser.browserskill_browser.time.sleep'):
            return self.browser.submit_application()

    def test_confirmation_text_is_required_to_report_success(self):
        out = self.run_submit(['', 'Thank you for applying!'])
        self.assertEqual(out.status, 'CONFIRMED')
        self.client.click.assert_called_once_with('form button[type="submit"]')

    def test_timeout_is_unconfirmed_and_never_reclicked(self):
        out = self.run_submit(['still the form'] * 40)
        self.assertEqual(out.status, 'UNCONFIRMED')
        self.client.click.assert_called_once()

    def test_security_code_and_captcha_are_reported(self):
        self.assertIn('security', self.run_submit(['Enter the security code we emailed you']).detail)
        self.setUp()
        self.assertIn('captcha', self.run_submit(['Please complete the captcha']).detail)

    def test_ambiguous_disabled_or_wrong_button_is_not_clicked(self):
        for bad in (dict(self.button, count=2), dict(self.button, visible=0), dict(self.button, disabled=True),
                    dict(self.button, text='Save draft')):
            with self.subTest(bad=bad):
                self.client.evaluate_readonly.side_effect = [bad]
                with self.assertRaises(SelectionReview):
                    self.browser.submit_application()
        self.client.click.assert_not_called()


class PickFailureMessageTests(unittest.TestCase):
    def test_failure_lists_the_options_the_page_offered(self):
        client = Mock(session_id='t', tab_id=1)
        browser = BrowserSkillBrowser(client)
        field = FieldObservation(label='Q', field_type='text', name=None, field_id='q', role='combobox', required=True)
        options = [dict(id=f'o{i}', label=f'Option number {i}', listbox_id='lb', disabled=False, unique=True) for i in range(12)]
        browser.read_field = Mock(return_value=FieldReadback(found=True, value=None))
        browser._combo_state = Mock(return_value=dict(found=True, options=options, expanded='true', nshown=0, listboxes=1, selected=None))
        with patch('app.browser.browserskill_browser.time.sleep'):
            with self.assertRaises(SelectionReview) as caught:
                browser.select_choice(field, ChoiceRequest(search='x', labels=[], pick=lambda labels: None, no_search=True))
        self.assertIn('Option number 0', str(caught.exception))
        self.assertIn('Option number 11', str(caught.exception))


class TypeaheadPickTests(unittest.TestCase):
    def test_a_typeahead_pick_types_the_search_when_nothing_is_listed_yet(self):
        client = Mock(session_id='t', tab_id=1)
        browser = BrowserSkillBrowser(client)
        field = FieldObservation(label='School*', field_type='text', name=None, field_id='school', role='combobox', required=True)
        option = dict(id='o1', label='The University of Texas at Dallas', listbox_id='lb', disabled=False, unique=True)
        empty = dict(found=True, options=[], expanded='true', nshown=0, listboxes=1, selected=None)
        listed = dict(empty, options=[option])
        committed = dict(found=True, options=[], expanded='false', nshown=1, listboxes=0, selected='The University of Texas at Dallas')
        def clicked_option():
            return any('option' in c.args[0] for c in client.click.call_args_list)

        def state(_field):                 # empty until searched, listed after the search, committed after the click
            if clicked_option():
                return committed
            return listed if client.fill.called else empty
        browser.read_field = Mock(side_effect=lambda f: FieldReadback(
            found=True, value='The University of Texas at Dallas' if clicked_option() else None))
        browser._combo_state = Mock(side_effect=state)
        choice = ChoiceRequest(search='University of Texas at Dallas', labels=[],
                               pick=lambda labels: labels[0] if len(labels) == 1 else None)
        with patch('app.browser.browserskill_browser.time.sleep'):
            result = browser.select_choice(field, choice)
        client.fill.assert_called_once_with('[id="school"]', 'University of Texas at Dallas')
        self.assertEqual(result.value, 'The University of Texas at Dallas')
        self.assertEqual(choice.chosen, 'The University of Texas at Dallas')


class TypeaheadFallbackTests(unittest.TestCase):
    def test_shorter_terms_are_tried_only_when_the_full_search_lists_nothing(self):
        client = Mock(session_id='t', tab_id=1)
        browser = BrowserSkillBrowser(client)
        field = FieldObservation(label='School*', field_type='text', name=None, field_id='school', role='combobox', required=True)
        option = dict(id='o1', label='University of Texas at Dallas', listbox_id='lb', disabled=False, unique=True)
        empty = dict(found=True, options=[], expanded='true', nshown=0, listboxes=1, selected=None)
        committed = dict(found=True, options=[], expanded='false', nshown=1, listboxes=0, selected='University of Texas at Dallas')

        def state(_field):
            if any('option' in c.args[0] for c in client.click.call_args_list):
                return committed
            typed = [c.args[1] for c in client.fill.call_args_list]
            return dict(empty, options=[option]) if typed and typed[-1] == 'Dallas' else empty
        browser.read_field = Mock(side_effect=lambda f: FieldReadback(
            found=True, value='University of Texas at Dallas' if any('option' in c.args[0] for c in client.click.call_args_list) else None))
        browser._combo_state = Mock(side_effect=state)
        choice = ChoiceRequest(search='University of Texas at Dallas', search_fallbacks=['Texas Dallas', 'Dallas'], labels=[],
                               pick=lambda labels: labels[0] if len(labels) == 1 else None)
        with patch('app.browser.browserskill_browser.time.sleep'):
            result = browser.select_choice(field, choice)
        self.assertEqual([c.args[1] for c in client.fill.call_args_list], ['University of Texas at Dallas', 'Texas Dallas', 'Dallas'])
        self.assertEqual(result.value, 'University of Texas at Dallas')


class MultiSelectChipTests(unittest.TestCase):
    def test_page_query_reads_multi_select_chips_as_the_committed_value(self):
        import inspect
        import app.browser.browserskill_browser as module
        source = inspect.getsource(module.BrowserSkillBrowser._combo_state)
        self.assertIn('.select__multi-value__label', source)
        self.assertIn('chips.map(c => c.innerText.trim()).join', source)

    def test_a_chip_selection_verifies_without_a_retry(self):
        client = Mock(session_id='t', tab_id=1)
        browser = BrowserSkillBrowser(client)
        field = FieldObservation(label='Gender', field_type='text', name=None, field_id='g', role='combobox', required=True)
        option = dict(id='o1', label="I don't wish to answer", listbox_id='lb', disabled=False, unique=True)
        listed = dict(found=True, options=[option], expanded='true', nshown=0, listboxes=1, selected=None)
        chipped = dict(found=True, options=[], expanded='false', nshown=1, listboxes=0, selected="I don't wish to answer")

        def state(_field):
            return chipped if any('option' in c.args[0] for c in client.click.call_args_list) else listed
        browser.read_field = Mock(side_effect=lambda f: FieldReadback(
            found=True, value="I don't wish to answer" if any('option' in c.args[0] for c in client.click.call_args_list) else None))
        browser._combo_state = Mock(side_effect=state)
        choice = ChoiceRequest(search='decline', labels=[], pick=lambda labels: "I don't wish to answer", no_search=True)
        with patch('app.browser.browserskill_browser.time.sleep'):
            result = browser.select_choice(field, choice)
        self.assertEqual(result.value, "I don't wish to answer")
        option_clicks = [c for c in client.click.call_args_list if 'option' in c.args[0]]
        self.assertEqual(len(option_clicks), 1)


class SelectionRetryTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(session_id='test', tab_id=42)
        self.browser = BrowserSkillBrowser(self.client)
        self.field = FieldObservation(label='Privacy *', field_type='text', name=None, field_id='q',
                                      role='combobox', required=True)
        self.choice = ChoiceRequest(search='Yes', labels=['Yes'])
        self.done = FieldReadback(found=True, value='Yes')
        self.browser._combo_state = Mock(return_value={'chips': []})

    def lost_click(self):
        error = SelectionReview('Selection was attempted but committed value did not verify')
        error.wrong_value_committed, error.nothing_committed = False, True
        return error

    def test_a_lost_click_is_retried_once_and_then_verified(self):
        with patch.object(self.browser, '_select_choice_once', side_effect=[self.lost_click(), self.done]) as once:
            self.assertEqual(self.browser.select_choice(self.field, self.choice).value, 'Yes')
        self.assertEqual(once.call_count, 2)

    def test_a_second_lost_click_stops_for_review_without_a_third_try(self):
        with patch.object(self.browser, '_select_choice_once', side_effect=[self.lost_click(), self.lost_click()]) as once:
            with self.assertRaises(SelectionReview):
                self.browser.select_choice(self.field, self.choice)
        self.assertEqual(once.call_count, 2)
        self.client.press.assert_called()          # the dropdown is closed again

    def test_ordinary_review_reasons_are_never_retried(self):
        with patch.object(self.browser, '_select_choice_once', side_effect=SelectionReview('No unique enabled matching option')) as once:
            with self.assertRaises(SelectionReview):
                self.browser.select_choice(self.field, self.choice)
        self.assertEqual(once.call_count, 1)


    def test_a_wrong_multiselect_chip_is_removed_before_the_retry(self):
        wrong = SelectionReview('committed value did not verify')
        wrong.wrong_value_committed, wrong.nothing_committed = True, False
        choice = ChoiceRequest(search='Asian', labels=['South Asian'])
        states = [{'chips': ['Hispanic or Latinx']}, {'chips': []}]
        self.browser._combo_state = Mock(side_effect=states)
        with patch.object(self.browser, '_select_choice_once', side_effect=[wrong, self.done]):
            self.browser.select_choice(self.field, choice)
        clicked = [c.args[0] for c in self.client.click.call_args_list]
        self.assertEqual(len(clicked), 1)
        self.assertIn('Remove Hispanic or Latinx', clicked[0])

    def test_the_approved_chip_is_never_removed(self):
        choice = ChoiceRequest(search='Asian', labels=['South Asian'])
        self.browser._combo_state = Mock(return_value={'chips': ['South Asian']})
        self.browser._remove_wrong_chips(self.field, choice)
        self.client.click.assert_not_called()
