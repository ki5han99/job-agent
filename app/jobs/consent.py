"""Classify consent/acknowledgment checkboxes against the user's approved categories (answers.yaml)."""
import re
from dataclasses import dataclass

# Categories the label can express; ALL of them must be approved for the box to be ticked.
CATEGORIES = [
    ("BACKGROUND_CHECK_AUTH", r"background (?:check|screening|investigation)|criminal|credit (?:check|report)|screening|drug (?:test|screen)"),
    ("ARBITRATION", r"arbitrat|class[- ]action|jury"),
    ("TRUTHFULNESS_CERT", r"certif|attest|\btrue\b|truthful|accurate|complete and correct|correct and complete|falsif|misrepresent|knowingly"),
    ("RECORDING_CONSENT", r"record(?:ed|ing)\b|bright ?hire|transcri\w+|\baudio\b|\bvideo\b"),
    ("AI_USE_ACK", r"\bai\b|artificial intelligence|automated|machine learning|algorithm"),
    ("DATA_PROCESSING_ACK", r"(?:processing|collection|storage|retention|use) of (?:my |your )?(?:personal )?(?:data|information)|"
                            r"data (?:protection|processing)|gdpr|personal (?:data|information)|"
                            r"(?:collect\w*|stor\w*|process\w*|retain\w*)[^.]{0,80}\b(?:my|your)\b[^.]{0,30}\b(?:data|information|responses|answers)\b"),
    ("PRIVACY_ACK", r"privacy"),
    ("TERMS_ACK", r"application terms|terms (?:of use|of service|and conditions)|\bterms\b|conditions of|"
                  r"(?:applicant|candidate|application) agreement"),
]
# Never auto-accepted: marketing/contact opt-ins and legal effects outside the approved list.
UNAPPROVED = [
    ("marketing / promotional opt-in", r"marketing|newsletter|promotion|advertis|sms|text message|e-?mail(?:s| me| updates)|"
                                       r"contact me|communicat|updates?|talent (?:pool|community|network)|future (?:job|opportunit|role|position)|stay in touch"),
    ("data sharing / sale", r"\bshare\b|\bsell\b|\bsale\b|disclos|affiliates?\b|third[- ]part(?:y|ies)(?! background)"),
    ("rights waiver / assignment", r"waive|release (?:of|any)|indemnif|non-?compete|assign(?:ment)? of|confidentiality agreement"),
    ("opposite polarity", r"\bdo not (?:consent|agree|want)|\bdon'?t (?:consent|agree|want)|opt[- ]out|unsubscribe|withdraw|decline|refuse|\bno,"),
]
BARE_PRIVACY = {"privacy", "privacy policy", "privacy notice", "privacy statement"}


@dataclass(frozen=True)
class ConsentDecision:
    categories: tuple[str, ...]
    eligible: bool
    reason: str

    @property
    def category(self) -> str:       # primary category, for logs
        return self.categories[0] if self.categories else "REVIEW"


def _norm(label: str) -> str:
    return " ".join(label.replace("’", "'").casefold().split()).rstrip("*").strip()


def classify_consent(label: str, approved: set[str] | frozenset[str] | list[str] = frozenset()) -> ConsentDecision:
    text = _norm(label)
    approved = set(approved)
    if not text:
        return ConsentDecision((), False, "empty label")
    for reason, pattern in UNAPPROVED:
        if re.search(pattern, text):
            return ConsentDecision((), False, reason)
    if text in BARE_PRIVACY:
        found = ["PRIVACY_ACK"]
    else:
        found = [name for name, pattern in CATEGORIES if re.search(pattern, text)]
    if not found:
        return ConsentDecision((), False, "wording is not a recognized consent category")
    missing = [c for c in found if c not in approved]
    if missing:
        return ConsentDecision(tuple(found), False, "category not approved: " + ", ".join(missing))
    return ConsentDecision(tuple(found), True, "approved category: " + ", ".join(found))
