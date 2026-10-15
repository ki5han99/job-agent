"""Small browser-neutral contract for the first Greenhouse migration slice."""
from typing import Callable, Protocol

from pydantic import BaseModel


class BrowserError(RuntimeError):
    """Execution outcome is uncertain; stop mutations and ask for review."""


class SelectionReview(BrowserError):
    """No unique supported selection; human review is required."""


class FieldObservation(BaseModel):
    label: str
    field_type: str
    name: str | None
    field_id: str | None
    role: str | None
    required: bool


class PageObservation(BaseModel):
    url: str
    title: str
    heading: str
    text: str
    fields: list[FieldObservation]


class FieldReadback(BaseModel):
    found: bool
    value: str | None
    country_code: str | None = None


class FileReadback(BaseModel):
    found: bool
    filenames: list[str]
    shown_in_ui: bool = False


class SubmitOutcome(BaseModel):
    status: str  # CONFIRMED | UNCONFIRMED
    detail: str


class ChoiceRequest(BaseModel):
    search: str
    labels: list[str]
    country_code: str | None = None
    # Only for multi-part place labels, where identical duplicate rows are indistinguishable.
    identical_duplicates_ok: bool = False
    # Only pick from options already listed; never type into the combobox to filter.
    no_search: bool = False
    # Policy-driven choice among whatever options the page lists (education, ranges, ...).
    # The adapter calls pick(option_labels) once, then sets labels/search/chosen to the result.
    pick: Callable[[list[str]], str | None] | None = None
    chosen: str | None = None
    # Typeaheads: shorter terms tried in order when the full search lists nothing usable.
    search_fallbacks: list[str] = []


class Browser(Protocol):
    def start(self) -> None: ...
    def attach(self, session_id: str, tab_id: int, expected_url: str) -> None: ...
    def open(self, url: str) -> None: ...
    def observe_page(self) -> PageObservation: ...
    def fill_text(self, field: FieldObservation, value: str) -> None: ...
    def read_field(self, field: FieldObservation) -> FieldReadback: ...
    def select_choice(self, field: FieldObservation, choice: ChoiceRequest) -> FieldReadback: ...
    def set_checkbox(self, field: FieldObservation) -> FieldReadback: ...
    def upload_file(self, field: FieldObservation, path: str) -> None: ...
    def read_file(self, field: FieldObservation, expected_name: str) -> FileReadback: ...
    def submit_application(self) -> SubmitOutcome: ...
    def handoff(self) -> str: ...
