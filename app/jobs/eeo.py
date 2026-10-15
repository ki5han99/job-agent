"""Voluntary EEO questions: only an explicit decline option is ever chosen; never a fact."""
import re

EEO_TERMS = re.compile(
    r"\b(gender|hispanic|latino|latina|latinx|race|ethnicity|veteran|disabilit\w*|sexual orientation|transgender|lgbtq\w*)\b",
    re.IGNORECASE)

# Exact (case/space-folded) option labels that mean "I decline to answer". A fact such as
# "I am not a protected veteran" is deliberately absent: that would assert something.
DECLINE_LABELS = [
    "decline to self identify", "decline to self-identify", "i decline to self identify",
    "i decline to self-identify", "decline to answer", "i decline to answer",
    "decline to state", "decline to identify", "decline to disclose",
    "prefer not to say", "i prefer not to say", "prefer not to answer", "i prefer not to answer",
    "prefer not to disclose", "i prefer not to disclose", "prefer not to specify",
    "i don't wish to answer", "i don’t wish to answer", "i do not wish to answer",
    "i don't want to answer", "i don’t want to answer", "i do not want to answer",
    "i choose not to disclose", "i choose not to answer", "choose not to disclose",
    "i do not wish to self-identify", "i don't wish to self-identify",
    "i don’t wish to self-identify", "i do not wish to self identify",
]


def is_eeo_question(label: str) -> bool:
    text = " ".join(label.split())
    return 0 < len(text) <= 100 and bool(EEO_TERMS.search(text))
