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
            const textual = (el.tagName === 'INPUT' && ['text','email','tel','number'].includes(el.type)) ||
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
        if field.role == "combobox" or field.field_type not in {"text", "email", "tel", "number", "textarea"}:
            raise BrowserError("Unsupported action: not a plain text field.")
        if field not in self.observe_page().fields:
            raise BrowserError("Field label or metadata changed; re-plan before filling.")
        if not self._query_field(field).found:
            raise BrowserError("Text field is missing, ambiguous, disabled, or changed.")
        self.client.fill('[id=' + json.dumps(field.field_id) + ']', value)

    def read_field(self, field: FieldObservation) -> FieldReadback:
        if field.field_type == "checkbox":
            return self._read_checkbox(field)
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
            // Multi-select widgets show each choice as a chip and hide it from the option list.
            const chips = Array.from(shell.querySelectorAll('.select__multi-value__label')).filter(visible);
            const total = selected.length + chips.length;
            const closed = el.getAttribute('aria-expanded') !== 'true';
            const committed = closed && selected.length === 1 && chips.length === 0;
            const chipped = closed && chips.length > 0 && selected.length === 0;
            return {found:true, options, expanded:el.getAttribute('aria-expanded'), nshown:total, listboxes:boxes.length,
                chips:chips.map(c => c.innerText.trim()),
                selected:committed ? selected[0].innerText.trim() : (chipped ? chips.map(c => c.innerText.trim()).join('; ') : null),
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
                if not (getattr(error, "wrong_value_committed", False) or getattr(error, "nothing_committed", False)):
                    raise
            # A different value was committed (option list re-ordered under the click), or the click was
            # lost to a re-render and nothing was committed. Re-selecting is idempotent and verified again;
            # never retried more than once. A multi-select keeps the wrong chip, so remove it first.
            self._remove_wrong_chips(field, choice)
            return self._select_choice_once(field, choice)
        except SelectionReview:
            # Never leave an open dropdown covering later controls (e.g. the Attach button).
            try:
                self.client.press("Escape", '[id=' + json.dumps(field.field_id) + ']')
            except BrowserError:
                pass
            raise

    def _remove_wrong_chips(self, field: FieldObservation, choice: ChoiceRequest) -> None:
        """Remove multi-select chips that are not the approved choice, then require a clean state."""
        chips = self._combo_state(field).get("chips") or []
        for chip in chips:
            if self._matches(choice, chip, None):
                continue
            self.client.click('.select-shell:has([id=' + json.dumps(field.field_id) + ']) button[aria-label='
                              + json.dumps("Remove " + chip) + ']')
        left = [c for c in (self._combo_state(field).get("chips") or []) if not self._matches(choice, c, None)]
        if left:
            raise SelectionReview(f"Wrong multi-select values could not be removed: {left}")

    def _select_choice_once(self, field: FieldObservation, choice: ChoiceRequest) -> FieldReadback:
        if field.role != "combobox" or not choice.search.strip() or not (choice.labels or choice.pick):
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
        if choice.pick is not None:
            def listed_options() -> list[dict]:
                return [o for o in self._combo_state(field)['options'] if o.get('label') and not o.get('disabled')]

            def poll(attempts: int) -> list[dict]:
                found: list[dict] = []
                for attempt in range(attempts):   # async option lists may populate just after opening
                    found = listed_options()
                    if found:
                        break
                    time.sleep(0.25)
                return found

            visible = poll(16)                     # a long list can take a few seconds to load
            if not visible and choice.no_search:   # an already-open menu toggles shut on click: open it once more
                self.client.click('[id=' + json.dumps(field.field_id) + ']')
                visible = poll(8)
            picked = choice.pick([o['label'] for o in visible]) if visible else None
            if not picked and not choice.no_search:   # a typeahead lists everything until searched
                for term in [choice.search, *choice.search_fallbacks]:
                    self.client.fill('[id=' + json.dumps(field.field_id) + ']', term)
                    time.sleep(0.5)
                    visible = poll(16 if choice.search_fallbacks else 40)   # server-side searches can take a while
                    picked = choice.pick([o['label'] for o in visible]) if visible else None
                    if picked:
                        break
            if not picked:
                listed = "; ".join(o['label'][:70] for o in visible[:14]) or "none"
                now = self._combo_state(field)
                raise SelectionReview("No listed option satisfies the approved policy; nothing was clicked. "
                                      f"Options seen ({len(visible)}): {listed} "
                                      f"[expanded={now.get('expanded')}, listboxes={now.get('listboxes')}, shown={now.get('nshown')}]")
            choice.labels, choice.search, choice.chosen, choice.pick = [picked], picked, picked, None
            state = self._combo_state(field)          # the list as it is now (a search may have filtered it)
            if self._matches(choice, current.value, current.country_code):
                self.client.press("Escape", '[id=' + json.dumps(field.field_id) + ']')
                return current
        options = [o for o in state['options'] if self._matches(choice, o.get('label'), o.get('country_code'))]
        if not options and not choice.no_search:
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
            listed = "; ".join((o.get('label') or '')[:50] for o in state['options'][:10]) or "none"
            raise SelectionReview(
                "No unique enabled matching option; selection left for review. "
                f"Wanted: {choice.labels[:2]}; matching={len(options)} "
                f"unique={[bool(o.get('unique')) for o in options]} disabled={[bool(o.get('disabled')) for o in options]}; "
                f"options seen: {listed}")
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
        error.nothing_committed = last.get("selected") is None and not last.get("expanded") == "true"
        raise error

    def _read_checkbox(self, field: FieldObservation) -> FieldReadback:
        if field.field_type != "checkbox" or not field.field_id:
            return FieldReadback(found=False, value=None)
        query = r'''((id, url) => {
            const matches = Array.from(document.querySelectorAll('[id]')).filter(el => el.id === id);
            const el = matches.length === 1 ? matches[0] : null;
            if (!el || el.type !== 'checkbox' || location.href !== url || el.disabled || !el.getClientRects().length)
                return {found:false, value:null};
            return {found:true, value:el.checked ? 'checked' : 'unchecked'};
        })'''
        try:
            return FieldReadback.model_validate(self.client.evaluate_readonly(
                query + '(' + json.dumps(field.field_id) + ',' + json.dumps(self.observe_page().url) + ')'))
        except ValidationError as error:
            raise BrowserError("Invalid checkbox readback.") from error

    def set_checkbox(self, field: FieldObservation) -> FieldReadback:
        """Tick one uniquely identified checkbox (never untick); returns the verified readback."""
        if field not in self.observe_page().fields:
            raise BrowserError("Field label or metadata changed; re-plan before ticking.")
        current = self._read_checkbox(field)
        if not current.found:
            raise SelectionReview("Checkbox is missing, disabled, or ambiguous.")
        if current.value != "checked":
            # Styled checkboxes often swallow a click on the bare input; the label is the real hit target.
            for selector in ('[id=' + json.dumps(field.field_id) + ']',
                             'label[for=' + json.dumps(field.field_id) + ']'):
                try:
                    self.client.click(selector)
                except BrowserError:
                    continue
                for attempt in range(6):
                    current = self._read_checkbox(field)
                    if current.found and current.value == "checked":
                        return current
                    time.sleep(0.25)
        return current

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

    def _file_drop_target(self, field: FieldObservation) -> str:
        selector = 'div:has(> input[id=' + json.dumps(field.field_id) + '][type="file"])'
        info = self.client.evaluate_readonly(
            '(() => ({count: document.querySelectorAll(' + json.dumps(selector) + ').length}))()')
        if not isinstance(info, dict) or info.get("count") != 1:
            raise SelectionReview("Cannot uniquely identify a drop target for the file field.")
        return selector

    def upload_file(self, field: FieldObservation, path: str) -> None:
        file = Path(path)
        if not file.is_absolute() or not file.is_file():
            raise BrowserError("Upload source must be an existing absolute file path.")
        if field not in self.observe_page().fields:
            raise BrowserError("Field label or metadata changed; re-plan before uploading.")
        trigger = self._file_trigger(field)
        try:
            self.client.upload(trigger, str(file))
        except BrowserError as error:
            # Pickers built on showOpenFilePicker() reject the trigger. Deliver once to the single wrapper
            # that owns this input; the caller still verifies the attachment independently.
            if "unsupported" not in str(error).lower():
                raise
            self.client.upload(self._file_drop_target(field), str(file), mode="drop")

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
                "left open for human review.")
