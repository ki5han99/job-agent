"""BrowserSkill output is translated here, never in application policy."""
import json
import re
import time
from pathlib import Path

from pydantic import ValidationError

from app.browser.browserskill_client import BrowserSkillClient
from app.browser.interface import (
    BrowserError, ChoiceRequest, FieldObservation, FieldReadback, FileReadback, PageObservation,
    SelectionReview, SubmitOutcome,
)


PAGE_QUERY = r'''(() => {
    const visible = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
    const label = el => (el.getAttribute('aria-label') ||
        Array.from(el.labels || []).map(x => x.innerText).join(' ') ||
        (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.innerText || '').join(' ')).trim();
    const fields = [];
    for (const el of document.querySelectorAll('input, textarea, select')) {
        if (!visible(el) || el.name === 'g-recaptcha-response' || el.type === 'search' ||
            ['hidden', 'submit', 'button', 'reset'].includes(el.type)) continue;
        const group = el.type === 'file' ? el.closest('[role="group"][aria-labelledby]') : null;
        const groupText = group ? (group.getAttribute('aria-labelledby') || '').split(/\s+/)
            .map(id => document.getElementById(id)?.innerText || '').join(' ').trim() : '';
        const text = groupText || label(el);
        if (!el.id && !el.name && !text && !el.getAttribute('role') &&
            el.getAttribute('aria-hidden') === 'true' && el.getAttribute('tabindex') === '-1') {
            const combos = el.closest('.select-shell')?.querySelectorAll('[role="combobox"][id]');
            if (combos?.length === 1 && fields.some(f => f.field_id === combos[0].id && f.role === 'combobox' && f.label)) continue;
        }
        fields.push({label:text, field_type:el.getAttribute('type') || el.tagName.toLowerCase(),
            name:el.getAttribute('name'), field_id:el.id || null, role:el.getAttribute('role'),
            required:el.required || el.getAttribute('aria-required') === 'true' ||
                group?.getAttribute('aria-required') === 'true'});
    }
    return {url:location.href, title:document.title, heading:document.querySelector('h1')?.innerText || '',
        text:document.body.innerText, fields};
})()'''


class BrowserSkillBrowser:
    def __init__(self, client: BrowserSkillClient | None = None):
        self.client = client or BrowserSkillClient()
        self.expected_url: str | None = None

    def start(self) -> None:
        self.client.start()

    def attach(self, session_id: str, tab_id: int, expected_url: str) -> None:
        self.client.attach(session_id, tab_id)
        self.expected_url = expected_url
        self.observe_page()

    def open(self, url: str) -> None:
        self.expected_url = url
        self.client.open(url)

    def observe_page(self) -> PageObservation:
        try:
            page = PageObservation.model_validate(self.client.evaluate_readonly(PAGE_QUERY))
        except ValidationError as error:
            raise BrowserError("Incomplete page observation; cannot establish readiness.") from error
        if self.expected_url and page.url.split('?')[0].rstrip('/') != self.expected_url.split('?')[0].rstrip('/'):
            raise BrowserError("Browser tab changed URL. Stop and inspect before resuming.")
        return page

    def _query_field(self, field: FieldObservation) -> FieldReadback:
        if not field.field_id:
            return FieldReadback(found=False, value=None)
        # JSON encoding here builds JavaScript literals, never a shell command.
        query = r'''(() => {
            const matches = Array.from(document.querySelectorAll('[id]')).filter(el => el.id === FIELD_ID);
            if (matches.length !== 1) return {found:false,value:null};
            const el = matches[0];
            const textual = (el.tagName === 'INPUT' && ['text','email','tel'].includes(el.type)) ||
                el.tagName === 'TEXTAREA';
            if (location.href !== EXPECTED_URL || !textual || el.getAttribute('role') === 'combobox' ||
                !el.getClientRects().length || el.disabled || el.readOnly)
                return {found:false,value:null};
            return {found:true,value:el.value};
        })()'''.replace('FIELD_ID', json.dumps(field.field_id)).replace('EXPECTED_URL', json.dumps(self.observe_page().url))
        try:
            return FieldReadback.model_validate(self.client.evaluate_readonly(query))
        except ValidationError as error:
            raise BrowserError("Invalid field readback.") from error

    def fill_text(self, field: FieldObservation, value: str) -> None:
        if field.role == "combobox" or field.field_type not in {"text", "email", "tel", "textarea"}:
            raise BrowserError("Unsupported action: not a plain text field.")
        if field not in self.observe_page().fields:
            raise BrowserError("Field label or metadata changed; re-plan before filling.")
        if not self._query_field(field).found:
            raise BrowserError("Text field is missing, ambiguous, disabled, or changed.")
        self.client.fill('[id=' + json.dumps(field.field_id) + ']', value)

    def read_field(self, field: FieldObservation) -> FieldReadback:
        if field.role == "combobox":
            state = self._combo_state(field)
            return FieldReadback(found=state["found"], value=state.get("selected"),
                                 country_code=state.get("country_code"))
        return self._query_field(field)

    def _combo_state(self, field: FieldObservation) -> dict:
        page = self.observe_page()
        if field not in page.fields or not field.field_id:
            raise SelectionReview("Combobox identity or label changed.")
        query = r'''((id, url) => {
            const visible = el => el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
            const flag = el => {
                const classes = Array.from(el?.querySelector('.iti__flag')?.classList || []);
                return classes.find(c => /^iti__[a-z]{2}$/.test(c))?.slice(5) || null;
            };
            const matches = Array.from(document.querySelectorAll('[id]')).filter(el => el.id === id);
            if (location.href !== url || matches.length !== 1) return {found:false, options:[]};
            const el = matches[0], shell = el.closest('.select-shell');
            if (el.getAttribute('role') !== 'combobox' || !visible(el) || el.disabled || el.readOnly || !shell)
                return {found:false, options:[]};
            const controlled = (el.getAttribute('aria-controls') || '').split(/\s+/).filter(Boolean)
                .map(id => document.getElementById(id)).filter(x => x?.getAttribute('role') === 'listbox');
            const local = Array.from(shell.querySelectorAll('[role="listbox"]'));
            const boxes = Array.from(new Set([...controlled, ...local])).filter(visible);
            const options = boxes.length === 1 && boxes[0].id ?
                Array.from(boxes[0].querySelectorAll('[role="option"]')).filter(visible).map(opt => ({
                    id:opt.id || null, label:opt.innerText.trim(), country_code:flag(opt),
                    disabled:opt.getAttribute('aria-disabled') === 'true', listbox_id:boxes[0].id,
                    unique:!!opt.id && Array.from(document.querySelectorAll('[id]')).filter(x => x.id === opt.id).length === 1
                })) : [];
            const selected = Array.from(shell.querySelectorAll('.select__single-value')).filter(visible);
            const committed = el.getAttribute('aria-expanded') !== 'true' && selected.length === 1;
            return {found:true, options, expanded:el.getAttribute('aria-expanded'), nshown:selected.length, listboxes:boxes.length,
                selected:committed ? selected[0].innerText.trim() : null,
                country_code:committed ? flag(selected[0]) : null};
        })'''
        state = self.client.evaluate_readonly(
            query + '(' + json.dumps(field.field_id) + ',' + json.dumps(page.url) + ')')
        if not isinstance(state, dict) or not isinstance(state.get("found"), bool) or not isinstance(state.get("options"), list):
            raise BrowserError("Invalid combobox observation; stop mutations.")
        return state

    @staticmethod
    def _matches(choice: ChoiceRequest, label: str | None, country_code: str | None) -> bool:
        if choice.country_code:
            return country_code == choice.country_code
        normalized = " ".join((label or "").casefold().split())
        return bool(normalized) and normalized in {" ".join(x.casefold().split()) for x in choice.labels}

    def _candidates(self, state: dict, choice: ChoiceRequest) -> list[dict]:
        options = [o for o in state['options'] if self._matches(choice, o.get('label'), o.get('country_code'))]
        if (len(options) > 1 and choice.identical_duplicates_ok and not any(o.get('disabled') for o in options)
                and len({" ".join((o.get('label') or "").casefold().split()) for o in options}) == 1
                and all(o.get('unique') for o in options)):
            return options[:1]  # indistinguishable rows: the first is as good as any
        return options

    def select_choice(self, field: FieldObservation, choice: ChoiceRequest) -> FieldReadback:
        try:
            try:
                return self._select_choice_once(field, choice)
            except SelectionReview as error:
                if not getattr(error, "wrong_value_committed", False):
                    raise
            # A different value was committed (option list re-ordered under the click).
            # Re-selecting is idempotent and verified again; never retried more than once.
            return self._select_choice_once(field, choice)
        except SelectionReview:
            # Never leave an open dropdown covering later controls (e.g. the Attach button).
            try:
                self.client.press("Escape", '[id=' + json.dumps(field.field_id) + ']')
            except BrowserError:
                pass
            raise

    def _select_choice_once(self, field: FieldObservation, choice: ChoiceRequest) -> FieldReadback:
        if field.role != "combobox" or not choice.search.strip() or not choice.labels:
            raise SelectionReview("No supported approved combobox target.")
        current = self.read_field(field)
        if not current.found:
            raise SelectionReview("Combobox is missing, disabled, or ambiguous.")
        if self._matches(choice, current.value, current.country_code):
            return current
        self.client.click('[id=' + json.dumps(field.field_id) + ']')
        state = self._combo_state(field)
        if not state['found']:
            raise SelectionReview("Combobox changed after opening; stop selection.")
        options = [o for o in state['options'] if self._matches(choice, o.get('label'), o.get('country_code'))]
        if not options:
            self.client.fill('[id=' + json.dumps(field.field_id) + ']', choice.search)
        for attempt in range(12):
            state = self._combo_state(field)
            if not state['found']:
                raise SelectionReview("Combobox became unavailable; stop selection.")
            options = self._candidates(state, choice)
            if len(options) > 1:
                raise SelectionReview("Multiple matching options; no option was clicked.")
            if len(options) == 1:
                break
            time.sleep(0.25)
        if len(options) != 1 or not options[0].get('unique') or options[0].get('disabled'):
            raise SelectionReview("No unique enabled matching option; selection left for review.")
        option = options[0]
        # Refresh ownership and identity immediately before the option click.
        fresh = self._combo_state(field)
        matches = self._candidates(fresh, choice)
        if len(matches) != 1 or matches[0] != option:
            raise SelectionReview("Option changed before selection; no option was clicked.")
        selector = ('[id=' + json.dumps(option['listbox_id']) + '] [role="option"][id='
                    + json.dumps(option['id']) + ']')
        if choice.country_code:
            # Address the option by flag identity, not list position, so a re-ordered list
            # cannot redirect the click to another country.
            selector += ':has(.iti__flag.iti__' + choice.country_code + ')'
        self.client.click(selector)
        for attempt in range(24):
            actual = self.read_field(field)
            if actual.found and self._matches(choice, actual.value, actual.country_code):
                return actual
            time.sleep(0.25)
        time.sleep(1.0)
        last = self.read_field(field)
        if last.found and self._matches(choice, last.value, last.country_code):
            return last
        last = self._combo_state(field)
        error = SelectionReview(
            "Selection was attempted but committed value did not verify "
            f"(expanded={last.get('expanded')}, shown_values={last.get('nshown')}, "
            f"listboxes={last.get('listboxes')}, selected={last.get('selected')!r}, "
            f"code={last.get('country_code')!r}).")
        error.wrong_value_committed = last.get("selected") is not None
        raise error

    def _file_trigger(self, field: FieldObservation) -> str:
        """Selector of the single 'Attach' button sharing a wrapper with the file input."""
        if field.field_type != "file" or not field.field_id:
            raise SelectionReview("Not a supported file field.")
        selector = 'div:has(> input[id=' + json.dumps(field.field_id) + '][type="file"]) > button'
        info = self.client.evaluate_readonly(
            '(() => { const b = Array.from(document.querySelectorAll(' + json.dumps(selector) + '));'
            ' return {count:b.length, text:b[0]?.innerText.trim() || null, '
            'inputs:Array.from(document.querySelectorAll("[id]")).filter(e => e.id === '
            + json.dumps(field.field_id) + ').length}; })()')
        if not isinstance(info, dict) or info.get("count") != 1 or info.get("inputs") != 1 \
                or (info.get("text") or "").casefold() != "attach":
            raise SelectionReview("Cannot uniquely identify the file attach control.")
        return selector

    def upload_file(self, field: FieldObservation, path: str) -> None:
        file = Path(path)
        if not file.is_absolute() or not file.is_file():
            raise BrowserError("Upload source must be an existing absolute file path.")
        if field not in self.observe_page().fields:
            raise BrowserError("Field label or metadata changed; re-plan before uploading.")
        self.client.upload(self._file_trigger(field), str(file))

    def read_file(self, field: FieldObservation, expected_name: str) -> FileReadback:
        if field.field_type != "file" or not field.field_id:
            return FileReadback(found=False, filenames=[])
        query = r'''((id) => {
            const matches = Array.from(document.querySelectorAll('[id]')).filter(el => el.id === id);
            const input = matches.length === 1 && matches[0].type === 'file' ? matches[0] : null;
            // Greenhouse may swap the input out after upload; the label node stays.
            const label = document.getElementById('upload-label-' + id);
            const group = input?.closest('[role="group"]') || label?.closest('[role="group"]');
            if (matches.length > 1 || !group) return {found:false, filenames:[], text:''};
            return {found:true, filenames:input ? Array.from(input.files).map(f => f.name) : [],
                    text:group.innerText};
        })'''
        state = self.client.evaluate_readonly(query + '(' + json.dumps(field.field_id) + ')')
        if not isinstance(state, dict) or not isinstance(state.get("found"), bool):
            raise BrowserError("Invalid file readback.")
        names = [n for n in state.get("filenames", []) if isinstance(n, str)]
        text = state.get("text") if isinstance(state.get("text"), str) else ""
        return FileReadback(found=state["found"], filenames=names,
                            shown_in_ui=bool(expected_name) and expected_name in text)

    CONFIRMATION = re.compile(
        r"thank you for applying|application (?:has been )?(?:submitted|received)|"
        r"we(?:'ve| have) received your application", re.IGNORECASE)

    def submit_application(self) -> SubmitOutcome:
        """Click the single visible Submit button once. Never re-clicked, even on timeout."""
        selector = 'form button[type="submit"]'
        info = self.client.evaluate_readonly(
            '(() => { const all = Array.from(document.querySelectorAll(' + json.dumps(selector) + '));'
            ' return {count:all.length, visible:all.filter(b => b.getClientRects().length).length,'
            ' text:all[0]?.innerText.trim() || "", disabled:!!all[0]?.disabled}; })()')
        if not isinstance(info, dict) or info.get("count") != 1 or info.get("visible") != 1 \
                or info.get("disabled") or not re.fullmatch(r"submit(?: application)?", (info.get("text") or "").casefold()):
            raise SelectionReview("Cannot uniquely identify an enabled Submit control; nothing was clicked.")
        self.observe_page()  # URL guard immediately before the irreversible click
        self.client.click(selector)
        detail = "no confirmation text observed"
        for attempt in range(40):
            time.sleep(1.0)
            state = self.client.evaluate_readonly(
                '({text: document.body.innerText.slice(0, 6000)})')
            text = state.get("text", "") if isinstance(state, dict) else ""
            if self.CONFIRMATION.search(text):
                return SubmitOutcome(status="CONFIRMED", detail="Confirmation text observed.")
            if re.search(r"security code|verification code", text, re.IGNORECASE):
                detail = "page asks for an emailed security/verification code"
                break
            if re.search(r"captcha|are you a robot", text, re.IGNORECASE):
                detail = "page shows a captcha challenge"
                break
        return SubmitOutcome(status="UNCONFIRMED", detail=detail)

    def handoff(self) -> str:
        return (f"BrowserSkill session {self.client.session_id}, tab {self.client.tab_id} "
                "left open for human review. Nothing submitted.")
