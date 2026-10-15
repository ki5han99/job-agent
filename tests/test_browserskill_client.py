import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from app.browser.browserskill_client import BrowserSkillClient
from app.browser.interface import BrowserError


class BrowserSkillClientTests(unittest.TestCase):
    def client(self):
        client = BrowserSkillClient()
        client.session_id, client.tab_id = "test", 42
        return client

    def test_fill_pins_tab_and_keeps_value_one_argument(self):
        client = self.client()
        client._run = Mock(return_value='{}')
        value = 'Text with "quotes"; $(not-a-command)'
        client.fill('#first_name', value)
        args = client._run.call_args.args[0]
        self.assertEqual(args[args.index('--value') + 1], value)
        self.assertEqual(args[args.index('--tab-id') + 1], '42')
        self.assertNotIn('press', args)

    def test_timeout_is_not_retried(self):
        with patch('app.browser.browserskill_client.subprocess.run', side_effect=subprocess.TimeoutExpired('bsk', 45)) as run:
            with self.assertRaises(BrowserError):
                self.client().fill('#first_name', 'Known')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs['timeout'], 45)

    def test_invalid_json_stops(self):
        client = self.client()
        client._run = Mock(return_value='not json')
        with self.assertRaises(BrowserError):
            client.fill('#first_name', 'Known')

    def test_failed_readback_stops(self):
        client = self.client()
        client._run = Mock(return_value='{"ok":false}')
        with self.assertRaises(BrowserError):
            client.evaluate_readonly('document.title')

    def test_attach_rejects_lost_session(self):
        client = self.client()
        client._run = Mock(return_value='[]')
        with self.assertRaises(BrowserError):
            client.attach('lost', 42)

    def test_attach_rejects_user_tab(self):
        client = self.client()
        client._run = Mock(side_effect=[json.dumps([{'session_id':'test'}]),
            json.dumps({'tabs':[{'tab_id':42,'scope':'user'}]})])
        with self.assertRaises(BrowserError):
            client.attach('test', 42)

    def test_start_pins_active_agent_tab(self):
        client = BrowserSkillClient()
        client._run = Mock(side_effect=['{"session_id":"test"}',
            '{"tabs":[{"tab_id":42,"scope":"agent","active":true}]}'])
        client.start()
        self.assertEqual(client.tab_id, 42)

    def test_attach_valid_agent_tab(self):
        client = BrowserSkillClient()
        client._run = Mock(side_effect=['[{"session_id":"test"}]',
            '{"tabs":[{"tab_id":42,"scope":"agent"}]}'])
        client.attach('test', 42)
        self.assertEqual((client.session_id, client.tab_id), ('test', 42))

    def test_click_is_pinned_to_session_tab_without_keyboard(self):
        client = self.client()
        client._run = Mock(return_value='{}')
        client.click('[role="option"][id="chosen"]')
        args = client._run.call_args.args[0]
        self.assertEqual(args[:2],['bsk','click'])
        self.assertIn('--selector',args)
        self.assertIn('--tab-id',args)
        self.assertNotIn('press',args)


class BrowserSkillClientErrorReportingTests(unittest.TestCase):
    def test_nonzero_exit_surfaces_bsk_diagnostics_without_arguments(self):
        client = BrowserSkillClient()
        client.session_id, client.tab_id = "test", 42
        out = json.dumps({"code": "cdp_failed", "message": "Not allowed", "hint": "enable file URL access",
                          "data": {"reason": "set_file_input_failed"}})
        done = subprocess.CompletedProcess([], 3, stdout=out, stderr="")
        with patch('app.browser.browserskill_client.subprocess.run', return_value=done) as run:
            with self.assertRaises(BrowserError) as raised:
                client.upload('#x', '/private/secret-resume.pdf')
        message = str(raised.exception)
        self.assertIn('cdp_failed', message)
        self.assertIn('enable file URL access', message)
        self.assertIn('set_file_input_failed', message)
        self.assertNotIn('secret-resume', message)
        self.assertEqual(run.call_count, 1)

    def test_upload_uses_selector_file_and_pinned_tab(self):
        client = BrowserSkillClient()
        client.session_id, client.tab_id = "test", 42
        client._run = Mock(return_value='{}')
        client.upload('div > button', '/abs/resume.pdf')
        args = client._run.call_args.args[0]
        self.assertEqual(args[:2], ['bsk', 'upload'])
        self.assertEqual(args[args.index('--file') + 1], '/abs/resume.pdf')
        self.assertEqual(args[args.index('--tab-id') + 1], '42')

    def test_unparseable_failure_still_reports_exit_code(self):
        client = BrowserSkillClient()
        client.session_id, client.tab_id = "test", 42
        done = subprocess.CompletedProcess([], 2, stdout="boom", stderr="sensitive")
        with patch('app.browser.browserskill_client.subprocess.run', return_value=done):
            with self.assertRaises(BrowserError) as raised:
                client.click('#x')
        self.assertIn('exited 2', str(raised.exception))
        self.assertNotIn('sensitive', str(raised.exception))
