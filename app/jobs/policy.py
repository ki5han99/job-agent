"""Semantic question intents -> deterministic answers from approved facts and policies.

Intent classification may be fuzzy (regex first, an optional LLM second); the ANSWER never is:
it always comes from profile.yaml, preferences.yaml, answers.yaml or the application ledger.
"""
import re
from dataclasses import dataclass, field as dc_field
from datetime import date
from typing import Callable

from app.browser.interface import ChoiceRequest
from app.jobs import profile_facts as facts
from app.jobs.consent import classify_consent
from app.jobs.eeo import DECLINE_LABELS, is_eeo_question
from app.jobs.review_field_resolver import approved_sensitive_intent, normalized_question

INTENTS = {
    "US_AUTHORIZATION", "SPONSORSHIP", "RELOCATION", "ONSITE", "RELOCATION_ONSITE", "PRODUCT_FAMILIARITY",
    "PRIOR_EMPLOYMENT", "PRIOR_APPLICATION", "EDUCATION", "YEARS_EXPERIENCE", "PREFERRED_LOCATION",
    "REFERRAL_SOURCE", "LANGUAGES", "MILITARY", "VETERAN", "SALARY", "ADDRESS", "EEO", "RACE", "HISPANIC", "COVER_LETTER", "SCHOOL", "DEGREE", "DISCIPLINE", "CURRENT_COMPANY",
    "CURRENT_TITLE", "PREFERRED_NAME", "LEGAL_NAME", "THRESHOLD_YEARS", "DEGREE_HELD", "JOB_COUNTRY_AUTH", "AUTH_CATEGORY",
    "EMPLOYMENT_HISTORY", "CONSENT", "UNAPPROVED_CONSENT",
}


@dataclass
class Intent:
    name: str
    company: str | None = None   # PRIOR_EMPLOYMENT / PRIOR_APPLICATION target
    skill: str | None = None     # YEARS_EXPERIENCE in a specific skill
    part: str | None = None      # ADDRESS part
    number: float | None = None  # THRESHOLD_YEARS minimum
    text: str | None = None      # THRESHOLD_YEARS domain / DEGREE_HELD field
    source: str = "regex"


@dataclass
class Context:
    profile: object
    preferences: object
    answers: object
    company: str = ""            # the company being applied to
    job_location: str = ""
    ledger: dict = None
    today: date = None
    llm_classify: Callable[[str], dict | None] | None = None
    cache: dict = dc_field(default_factory=dict)


# ------------------------------------------------------------------ classification

_COMPANY = r"(?P<company>[A-Za-z0-9][A-Za-z0-9&.'\- ]*?)(?=\s+(?:before|previously|in the past|in the last|within|as|or|and|ever|now|currently|at any)\b|[,?;]|$)"
_HERE = {"here", "us", "this company", "the company", "our company", "this organization", "the organization",
         "this position", "this role", "this job", "this opportunity", "this team"}
_PRIOR_EMPLOYMENT = re.compile(
    r"\b(?:have you|were you|are you|did you)\b[^?]*?\b(?:employed (?:by|at|with)|worked (?:for|at)|"
    r"(?:employee|contractor|consultant) (?:of|at|for|with))\s+" + _COMPANY, re.IGNORECASE)
_PRIOR_APPLICATION = re.compile(
    r"\b(?:have you|did you)\b[^?]*?\bapplied (?:to|at|for|with)(?: work (?:at|for|with))?\s+" + _COMPANY, re.IGNORECASE)
_PRODUCT = re.compile(
    r"(?:\bhave you (?:ever )?(?:used|tried|tested|heard of)\s+|\bare you familiar with\s+)(?P<product>[A-Za-z0-9][A-Za-z0-9&.'\- ]*?)"
    r"(?=\s+before\b|[,?;]|$)", re.IGNORECASE)
_PRODUCT_EXCLUDE = re.compile(
    r"\b(?:years?|experience|proficien\w*|expert\w*|level|rate|rating|ai|chatgpt|llm|gpt|generat\w*|assist\w*|"
    r"to (?:write|draft|complete|answer))\b|\bhow (?:much|long|often)\b", re.IGNORECASE)

_RELOC_EXCLUDE = re.compile(r"assistance|package|bonus|reimburs|stipend|cover|pay for|require relocation|need relocation", re.I)
_OFFICE_WORDS = re.compile(r"on-?site|in[- ]office|in the office|\boffice\b|hybrid|days? (?:a|per) week|days in", re.I)
_WILLING = re.compile(r"\b(?:willing|able|comfortable|open to|okay with|ok with|can you|would you|planning to)\b", re.I)

_SCHOOL = {"school", "university", "college", "school name", "institution", "school or university"}
_DEGREE = {"degree", "degree type", "level of degree"}
_DISCIPLINE = {"discipline", "field of study", "major"}
_CURRENT_TITLE = {"current title", "current job title", "current position", "most recent title", "most recent job title"}
_CURRENT_COMPANY = {"current company", "current employer", "most recent company", "most recent employer"}
_THRESHOLD = re.compile(r"(\d+)\s*\+?\s*\)?\s*(?:or more\s+)?years?\b")
_DEGREE_HELD = re.compile(
    r"\b(?:do you|have you)\s+(?:currently\s+)?(?:have|hold|possess|completed|earned)\s+(?:a|an|your)?\s*"
    r"(?P<level>bachelor\S*|master\S*|doctor\S*|ph\.?d\S*|high school)(?:\s+degree)?(?:\s+or\s+(?:equivalent|higher|above))?"
    r"(?:\s+(?:in|from)\s+(?P<field>[^?]+))?")
_LEVEL_WORDS = {"bach": "Bachelor's", "mast": "Master's", "doct": "Doctorate", "ph.d": "Doctorate", "phd": "Doctorate", "high": "High school"}
_US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
_FOREIGN_LOC = re.compile(r"canada|\bindia\b|\buk\b|united kingdom|london|germany|poland|spain|brazil|ireland|toronto|emea|apac|singapore|latam|(?<!new )mexico|australia", re.I)


def us_location(location: str) -> bool:
    """True only on an explicit U.S. marker; 'Remote' alone is not evidence."""
    if not location or _FOREIGN_LOC.search(location):
        return False
    if re.search(r"united states", location, re.I) or re.search(r"(?<![A-Za-z])U\.?S\.?A?(?![A-Za-z])", location):
        return True
    return any(code in _US_STATES for code in re.findall(r",\s*([A-Z]{2})\b", location))


def _sponsorship_variant(q: str, ctx) -> bool:
    """'Now or in the future' sponsorship questions phrased differently from the exact approved wording.

    Timing must still be 'now or in the future' and the subject must be sponsorship. Tails naming a place
    ("to work at <this company>", "in the country in which you are applying") are only accepted when they
    refer to the company applied to, or the job is explicitly in the U.S.
    """
    text = re.sub(r"\s*\([^)]*\)", "", q.replace(",", " "))
    text = " ".join(text.split())
    m = re.fullmatch(
        r"(?:do|will) you (?:now )?or (?:will you )?(?:at any point )?in the future (?:require|need) "
        r"(?:visa |immigration |employment visa |work )?sponsorship(?P<tail>.*)", text)
    if not m:
        return False
    tail = m.group("tail").strip()
    if not tail or re.fullmatch(r"for (?:a |an )?(?:employment |work )?visa(?: status)?|for employment (?:visa )?status", tail):
        return True
    if re.fullmatch(r"to work in (?:the )?(?:united states(?: of america)?|u\.s\.?|us|usa)", tail):
        return True
    company = normalized_question(getattr(ctx, "company", "") or "")
    work_at = re.fullmatch(r"to work (?:at|for|with) (?P<c>.+)", tail)
    if work_at and company and work_at.group("c").strip().startswith(company):
        return True
    if re.fullmatch(r"(?:for employment (?:visa )?status )?in the country (?:in which you are applying|(?:outlined|listed) for this (?:job|role|position)|of this (?:job|role|position))", tail):
        return us_location(getattr(ctx, "job_location", ""))
    return False


_ADDRESS_PARTS = {
    "line1": {"address", "address line 1", "address line one", "street address", "street address line 1", "address 1", "street"},
    "line2": {"address line 2", "address line two", "street address line 2", "address 2", "apartment", "apt, suite, etc"},
    "city": {"city", "town", "city/town"},
    "state": {"state", "state/province", "state / province", "province", "state or province", "state/region"},
    "postal": {"postal/zip code", "zip code", "zip", "postal code", "zip/postal code", "zip / postal code", "postcode"},
    "country": {"country", "country/region"},
}


def classify_intent(label: str, ctx: Context | None = None) -> Intent | None:
    """Regex first; falls back to ctx.llm_classify (validated) when no pattern matches."""
    if ctx is not None and label in ctx.cache:
        return ctx.cache[label]
    intent = _classify(label, ctx)
    if ctx is not None:
        ctx.cache[label] = intent
    return intent


def _classify(label: str, ctx: Context | None) -> Intent | None:
    q = normalized_question(label)
    if not q:
        return None
    if re.match(r"cover letter\b", q):
        return Intent("COVER_LETTER")
    legacy = approved_sensitive_intent(label)
    if legacy is None and approved_sensitive_intent(re.sub(r"\s*\([^)]*\)", "", label)) == "DESIRED_SALARY":
        legacy = "DESIRED_SALARY"   # e.g. "Expected salary (numbers only)"
    if legacy == "US_AUTHORIZATION":
        return Intent("US_AUTHORIZATION")
    if legacy == "SPONSORSHIP_NOW_OR_FUTURE":
        return Intent("SPONSORSHIP")
    if legacy == "DESIRED_SALARY":
        return Intent("SALARY")
    if legacy == "NYC_ONSITE":
        return Intent("RELOCATION_ONSITE")
    if legacy is None and _sponsorship_variant(q, ctx):
        return Intent("SPONSORSHIP")
    for part, names in _ADDRESS_PARTS.items():
        if q in names:
            return Intent("ADDRESS", part=part)
    if q in _SCHOOL:
        return Intent("SCHOOL")
    if q in _DEGREE:
        return Intent("DEGREE")
    if q in _DISCIPLINE:
        return Intent("DISCIPLINE")
    if q in _CURRENT_TITLE:
        return Intent("CURRENT_TITLE")
    if q in _CURRENT_COMPANY or re.search(r"(?:your )?(?:current|most recent)(?: \(or most recent\))? (?:company|employer)\b", q):
        return Intent("CURRENT_COMPANY")
    if re.search(r"preferred (?:first )?name", q) and "last" not in q:
        return Intent("PREFERRED_NAME")
    if re.search(r"\bfull (?:legal )?name\b", q) and re.search(r"government|legal|passport|identification|\bid\b", q) or "legal name" in q:
        return Intent("LEGAL_NAME")
    if re.search(r"minimum (?:annual )?(?:base )?salary (?:desired|expected|requested)|desired (?:minimum )?(?:annual )?salary", q):
        return Intent("SALARY")
    m = _THRESHOLD.search(q)
    if m and "experience" in q and not re.search(r"how many|number of|do you have \d+ or", q):
        rest = q[m.end():]
        before = re.match(r"\s*of\s+(.*?)\s*experience\b", rest)
        after = rest[before.end():] if before else rest
        domain = " ".join(((before.group(1) if before else ""), re.sub(r"^\s*(?:working )?(?:with|in|using|including)\b", "", after.strip(" .,:;"))))
        return Intent("THRESHOLD_YEARS", number=float(m.group(1)), text=domain.strip())
    m = _DEGREE_HELD.search(q)
    if m:
        return Intent("DEGREE_HELD", skill=_LEVEL_WORDS[m.group("level").split()[0].rstrip("'s")[:4]], text=(m.group("field") or "").strip())
    if re.search(r"\b(?:legally )?authori[sz]ed to work in the (?:country|location|region)\b.*(?:outlined|listed|for which|in which|where|applying|applied|this (?:job|role|position)|of the (?:job|position|role))", q):
        return Intent("JOB_COUNTRY_AUTH")
    if re.search(r"which (?:work )?(?:authori[sz]ation|status)\b[^?]*describes? you|(?:work )?authori[sz]ation[^?]*best describes", q):
        return Intent("AUTH_CATEGORY")
    if re.search(r"employment history", q):
        return Intent("EMPLOYMENT_HISTORY")
    if re.search(r"\b(?:have you|were you|did you|are you)\b[^?]*\b(?:worked|work|been employed|employed) "
                 r"(?:here|for us|at our company|for this company|with us)\b", q):
        return Intent("PRIOR_EMPLOYMENT", company="")
    if re.search(r"\bapplied (?:to|at|for|with)\b", q):
        m = _PRIOR_APPLICATION.search(label)
        company = _company_of(m.group("company")) if m else None
        if company is not None:
            return Intent("PRIOR_APPLICATION", company=company)
    if (re.search(r"\b(?:employed (?:by|at|with)|worked (?:for|at)|(?:employee|contractor|consultant) (?:of|at|for|with))\b", q)
            and not re.search(r"sponsor|\bvisa\b|authori[sz]ed to work|relocat", q)):
        m = _PRIOR_EMPLOYMENT.search(label)
        company = _company_of(m.group("company")) if m else None
        if company is not None:
            return Intent("PRIOR_EMPLOYMENT", company=company)
    if "relocat" in q and not _RELOC_EXCLUDE.search(q) and not re.search(r"sponsor|\bvisa\b", q):
        return Intent("RELOCATION_ONSITE" if _OFFICE_WORDS.search(q) else "RELOCATION")
    if _OFFICE_WORDS.search(q) and _WILLING.search(q) and not re.search(r"sponsor|\bvisa\b", q):
        return Intent("ONSITE")
    m = _PRODUCT.search(label)
    if m and not _PRODUCT_EXCLUDE.search(label) and m.group("product")[0].isupper():
        return Intent("PRODUCT_FAMILIARITY", company=m.group("product").strip())
    if re.search(r"highest (?:level of )?(?:completed )?(?:education|degree)|education(?:al)? level|level of education", q):
        return Intent("EDUCATION")
    if re.search(r"\byears?\b.*\bexperience\b|\bexperience\b.*\byears?\b|how many years", q):
        if re.fullmatch(r"(?:total |how many )?years? of (?:(?:work|professional|relevant|total|overall|industry|full[- ]time|related) )*experience"
                        r"(?: do you have)?", q):
            return Intent("YEARS_EXPERIENCE")
        skill = re.search(r"\b(?:with|in|using|working with)\s+(?P<s>[a-z0-9+#.\- ]+)$", q)
        if skill:
            return Intent("YEARS_EXPERIENCE", skill=skill.group("s").strip())
        return None   # e.g. "Do you have 3+ years...": a threshold question, not a number to enter
    if re.search(r"(?:preferred|desired) (?:work )?location|from where do you intend to work|where do you (?:intend|plan|want) to work", q):
        return Intent("PREFERRED_LOCATION")
    if re.search(r"how did you (?:hear|learn|find)|where did you (?:hear|learn|find)|referral source", q):
        return Intent("REFERRAL_SOURCE")
    if re.search(r"language", q) and re.search(r"fluent|speak|spoken|written|proficien", q):
        return Intent("LANGUAGES")
    if re.search(r"hispanic|latin[oax]\b", q):
        return Intent("HISPANIC")  # asked on its own, separate from race
    if re.search(r"\b(?:race|ethnic\w*)\b", q):
        return Intent("RACE")
    if re.search(r"\bveteran\b", q):
        return Intent("VETERAN")
    if re.search(r"served in the (?:u\.?s\.? )?(?:military|armed forces)|military (?:service|status)", q):
        return Intent("MILITARY")
    if is_eeo_question(label):
        return Intent("EEO")
    if ctx is not None:
        approved = set(getattr(getattr(ctx.answers, "consent", None), "approved_categories", None) or [])
        decision = classify_consent(label, approved)
        if decision.eligible:                                # a routine consent: never ask the LLM to reinterpret it
            return Intent("CONSENT")
        if decision.reason not in {"wording is not a recognized consent category", "empty label"}:
            return Intent("UNAPPROVED_CONSENT")           # recognized but not approved (recording, marketing, sharing ...)
    if ctx is not None and ctx.llm_classify is not None and len(q.split()) >= 4:
        return _llm_intent(label, ctx)
    return None


def _company_of(raw: str) -> str | None:
    name = raw.strip(" .,'")
    if name.casefold() in _HERE:
        return ""            # "" = the company being applied to
    if not name or name[0].islower() or name.casefold().split()[0] in {"a", "an", "the", "any", "another"}:
        return None          # not a named company
    return name


_LLM_NEEDS = {
    "US_AUTHORIZATION": r"authori[sz]|eligible to work|right to work|work in the (?:u\.?s|united states)",
    "SPONSORSHIP": r"sponsor|visa",
    "RELOCATION": r"relocat|move to|moving",
    "ONSITE": r"on-?site|office|hybrid|in person|commute",
    "RELOCATION_ONSITE": r"relocat",
    "PRODUCT_FAMILIARITY": r"\bused\b|familiar|heard of|tried",
    "PRIOR_EMPLOYMENT": r"employ|worked|former|contractor|intern",
    "PRIOR_APPLICATION": r"appl(?:y|ied|ication)",
    "EDUCATION": r"educat|degree|diploma|school",
    "YEARS_EXPERIENCE": r"years?|experience",
    "PREFERRED_LOCATION": r"location|office|city|work from",
    "REFERRAL_SOURCE": r"hear|learn|find|source|referr",
    "LANGUAGES": r"language|fluent|speak",
    "MILITARY": r"military|armed forces|served",
    "VETERAN": r"veteran",
    "SALARY": r"salary|compensation|pay",
    "EEO": r"gender|race|ethnic|disab|orientation|transgender|lgbt|veteran|hispanic|latin",
}


def _llm_intent(label: str, ctx: Context) -> Intent | None:
    """The LLM only names the intent (and a company/skill); it never supplies an answer."""
    try:
        data = ctx.llm_classify(label)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("intent") not in INTENTS:
        return None
    if data.get("negated") is True:                       # polarity unclear -> a person decides
        return None
    country = data.get("country")
    if data["intent"] in {"US_AUTHORIZATION", "SPONSORSHIP"} and country not in (None, "", "US", "USA", "United States"):
        return None
    if data["intent"] in {"US_AUTHORIZATION", "SPONSORSHIP"} and re.search(
            r"unrestricted|without restriction|any employer|permanent|indefinite|citizen|green card|current employer|present employer",
            label, re.I):
        return None          # unrestricted / category questions are not the approved current-authorization fact
    needs = _LLM_NEEDS.get(data["intent"])
    if needs is None or not re.search(needs, label, re.I):
        return None          # a guess the question's own words do not support is ignored
    return Intent(data["intent"], company=data.get("company") or None, skill=data.get("skill") or None, source="llm")


# ------------------------------------------------------------------ bool answers

def _flag(value) -> bool | None:
    return value if isinstance(value, bool) else None


def bool_answer(intent: Intent, ctx: Context) -> bool | None:
    p, prefs, ans = ctx.profile, ctx.preferences, ctx.answers
    n = intent.name
    if n == "US_AUTHORIZATION":
        return _flag(p.work_authorization.authorized_to_work_us)
    if n == "SPONSORSHIP":
        return _flag(p.work_authorization.requires_sponsorship_now_or_in_future)
    if n == "RELOCATION":
        return True if _flag(getattr(getattr(prefs, "relocation", None), "willing_anywhere", None)) else None
    if n == "ONSITE":
        return True if _flag(getattr(getattr(prefs, "onsite", None), "willing", None)) else None
    if n == "RELOCATION_ONSITE":
        reloc = _flag(getattr(getattr(prefs, "relocation", None), "willing_anywhere", None))
        onsite = _flag(getattr(getattr(prefs, "onsite", None), "willing", None))
        return True if reloc and onsite else None
    if n == "PRODUCT_FAMILIARITY":
        return True if _flag(getattr(ans, "product_familiarity_default", None)) else None
    if n == "PRIOR_EMPLOYMENT":
        company = intent.company if intent.company else ctx.company
        return facts.worked_at(company, p) if company else None
    if n == "PRIOR_APPLICATION":
        company = intent.company if intent.company else ctx.company
        return facts.prior_application(company, ctx.ledger or {}) if company else None
    if n == "THRESHOLD_YEARS":
        return facts.meets_experience_threshold(p, intent.number, intent.text or "", ctx.today)
    if n == "DEGREE_HELD":
        return facts.holds_degree(p, intent.skill, intent.text or "", ctx.today)
    if n == "JOB_COUNTRY_AUTH":
        # The question names "the country of this job": only answerable when the job is explicitly in the U.S.
        return _flag(p.work_authorization.authorized_to_work_us) if us_location(ctx.job_location) else None
    if n == "MILITARY":
        return _flag(getattr(p.military, "served", None))
    if n == "VETERAN":
        return _flag(getattr(p.military, "is_veteran", None))
    return None


# ------------------------------------------------------------------ option pickers

def pick_yes_no(word: str) -> Callable[[list[str]], str | None]:
    """'Yes'/'No' exactly, else the single option that starts with it ('Yes, I am located in the US')."""
    def pick(labels: list[str]) -> str | None:
        exact = [l for l in labels if l.strip().casefold() == word.casefold()]
        if len(exact) == 1:
            return exact[0]
        starts = [l for l in labels if re.match(re.escape(word) + r"\b[\s,.:;-]", l.strip() + " ", re.I)]
        return starts[0] if len(starts) == 1 and not exact else None
    return pick


_PLACEHOLDER = re.compile(r"^(?:select|please select|choose|--|—|\.\.\.|none selected)", re.I)


def first_valid(labels: list[str]) -> str | None:
    for label in labels:
        if label.strip() and not _PLACEHOLDER.match(label.strip()):
            return label
    return None


def pick_product_usage(detail: str | None) -> Callable[[list[str]], str | None]:
    """'Yes' if offered plainly; else the single detailed Yes that matches the approved detail (e.g. 'personal')."""
    def pick(labels: list[str]) -> str | None:
        plain = pick_yes_no("Yes")(labels)
        if plain is not None:
            return plain
        if detail != "personal":
            return None
        yes = [l for l in labels if re.match(r"yes\b", l.strip(), re.I)]
        hits = [l for l in yes if re.search(r"personal", l, re.I) and not re.search(r"\b(?:work|both|professional|employer|company|team)\b", l, re.I)]
        return hits[0] if len(hits) == 1 else None
    return pick


def pick_sponsorship_not_needed(labels: list[str]) -> str | None:
    hits = [l for l in labels if re.search(r"sponsor", l, re.I)
            and re.search(r"do(?:es)? not (?:currently |now )?(?:need|require)|don'?t (?:need|require)|no sponsorship|without|not require", l, re.I)]
    return hits[0] if len(hits) == 1 else None


_AUTH_CATEGORY_WORDS = re.compile(r"citizen|national|permanent|green card|resident|visa|h-?1b|opt\b|\bead\b|\btn\b|e-?3|l-?1|refugee|asylum|dependent", re.I)


def pick_authorized(sponsorship_needed: bool | None, allow_category: bool) -> Callable[[list[str]], str | None]:
    """Option that says 'authorized to work in the U.S.' (narrowed by the sponsorship fact).
    Visa/citizenship categories are never guessed unless `allow_category` and they are the only candidate."""
    def pick(labels: list[str]) -> str | None:
        if any(re.match(r"\s*(?:yes|no)\b", l, re.I) for l in labels):
            return None      # a Yes/No-style list is handled (or left ambiguous) by pick_yes_no, not guessed here
        cands = [l for l in labels if re.search(r"authori[sz]ed", l, re.I) and not re.search(r"\bnot (?:legally )?authori|unauthori|(?<!not )(?<!n't )(?:require|need) sponsorship|will require", l, re.I)]
        if len(cands) > 1 and sponsorship_needed is False:
            narrowed = [l for l in cands if re.search(r"without|no sponsorship|do(?:es)? not (?:need|require)|not require", l, re.I)]
            cands = narrowed or cands
        if not allow_category:
            cands = [l for l in cands if not _AUTH_CATEGORY_WORDS.search(l)] if len(cands) != 1 else cands
        return cands[0] if len(cands) == 1 else None
    return pick


def chain(*pickers: Callable[[list[str]], str | None]) -> Callable[[list[str]], str | None]:
    def pick(labels: list[str]) -> str | None:
        for picker in pickers:
            result = picker(labels)
            if result is not None:
                return result
        return None
    return pick


_COUNTRY_US = {"united states", "united states of america", "usa", "us", "u.s.", "u.s.a."}


def pick_country_us(labels: list[str]) -> str | None:
    hits = [l for l in labels if " ".join(l.casefold().split()) in _COUNTRY_US]
    return hits[0] if len(hits) == 1 else None


def pick_contains(value: str) -> Callable[[list[str]], str | None]:
    """Exact option, else the single option containing `value` (e.g. a discipline)."""
    word = value.casefold().strip()

    def pick(labels: list[str]) -> str | None:
        exact = [l for l in labels if l.strip().casefold() == word]
        if len(exact) == 1:
            return exact[0]
        part = [l for l in labels if word in l.casefold()]
        return part[0] if len(part) == 1 and not exact else None
    return pick


_SCHOOL_STOP = {"the", "of", "at", "and", "in"}


def _school_words(name: str) -> frozenset[str]:
    """Significant words only: 'University of Texas - Dallas' and 'University of Texas at Dallas' are the same set."""
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]+", " ", name.casefold()).split() if w not in _SCHOOL_STOP)


def pick_school(name: str) -> Callable[[list[str]], str | None]:
    """The same institution regardless of case, punctuation, 'the/of/at'; or the single listing that contains all
    of its words. 'University of Dallas' and other campuses never match 'University of Texas at Dallas'."""
    want = _school_words(name)

    def pick(labels: list[str]) -> str | None:
        if not want:
            return None
        keyed = [(l, _school_words(l)) for l in labels]
        exact = [l for l, words in keyed if words == want]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None
        near = [l for l, words in keyed if want < words]
        return near[0] if len(near) == 1 else None
    return pick


def school_search_terms(name: str) -> list[str]:
    """Full name, then its distinctive words, then the last one: shorter terms for finicky typeaheads."""
    stop = {"the", "of", "at", "university", "college", "institute", "school", "and"}
    words = [w for w in re.sub(r"[^A-Za-z0-9 ]+", " ", name).split() if w.casefold() not in stop]
    terms = [name, " ".join(words), words[-1] if words else ""]
    seen, out = set(), []
    for term in terms:
        if term.strip() and term.casefold() not in seen:
            seen.add(term.casefold())
            out.append(term)
    return out


def pick_never_worked(labels: list[str]) -> str | None:
    hits = [l for l in labels if re.search(r"never (?:worked|been employed)|have not (?:previously |ever )?(?:worked|been employed)|no prior", l, re.I)]
    return hits[0] if len(hits) == 1 else None


_DECLINE_WORDS = re.compile(r"decline|prefer not|do(?:n'?t| not) (?:wish|want)|choose not|not (?:to )?(?:say|disclose|answer|specify|identify)|rather not", re.I)


def pick_decline_semantic(labels: list[str]) -> str | None:
    """The single option that means 'decline to answer' (never a fact). Ambiguity -> None."""
    hits = [l for l in labels if _DECLINE_WORDS.search(l.replace("\u2019", "'"))]
    return hits[0] if len(hits) == 1 else None


_AFFIRM = re.compile(r"^(?:yes|i (?:acknowledge|agree|consent|accept|understand|have read|confirm)|agree|accept|acknowledge|consent)\b", re.I)
_NEGATIVE = re.compile(r"\b(?:no|not|decline|disagree|do not|don't)\b", re.I)


def pick_affirmative(labels: list[str]) -> str | None:
    """The single option that affirms ('Yes', 'I acknowledge', 'I agree'); None if absent or ambiguous."""
    hits = [l for l in labels if _AFFIRM.match(l.strip()) and not _NEGATIVE.search(l)]
    return hits[0] if len(hits) == 1 else None


def pick_exact(value: str) -> Callable[[list[str]], str | None]:
    def pick(labels: list[str]) -> str | None:
        hits = [l for l in labels if l.strip().casefold() == value.casefold()]
        return hits[0] if len(hits) == 1 else None
    return pick


_LEVEL_OPTION = {
    "Master's": r"master|(?<![a-z])m\.?s\.?(?![a-z])|msc|mba",
    "Bachelor's": r"bachelor|(?<![a-z])b\.?s\.?(?![a-z])|b\.?tech",
    "Doctorate": r"doctor|ph\.?d",
    "High school": r"high school|(?<![a-z])ged(?![a-z])",
}
_NOT_COMPLETED = re.compile(r"some |in progress|incomplete|currently|enrolled|candidate|associate|unfinished", re.I)


_PLAIN_LEVEL = {
    "Master's": r"master'?s?(?:\s+degree)?", "Bachelor's": r"bachelor'?s?(?:\s+degree)?",
    "Doctorate": r"doctorate(?:\s+degree)?|ph\.?\s?d\.?", "High school": r"high school(?:\s+(?:diploma|degree))?",
}


def pick_education(level: str) -> Callable[[list[str]], str | None]:
    def pick(labels: list[str]) -> str | None:
        usable = [l for l in labels if not _NOT_COMPLETED.search(l)]
        plain = [l for l in usable if re.fullmatch(_PLAIN_LEVEL[level], re.sub(r"[^\w' .]", "", l).strip(), re.I)]
        if len(plain) == 1:
            return plain[0]
        hits = [l for l in usable if re.search(_LEVEL_OPTION[level], l, re.I)]
        return hits[0] if len(hits) == 1 and not plain else None
    return pick


_REFERRAL_OPTIONS = [
    r"company (?:career )?web ?site|company site|corporate (?:career )?web ?site|company'?s? web ?site|^website$",
    r"(?:careers?|jobs?)(?: page| site| web ?site| board)|company careers?|career ?(?:page|site)",
    r"direct (?:application|apply)|^direct$",
]
_REFERRAL_EXCLUDE = re.compile(r"referr|employee|linkedin|indeed|glassdoor|agency|recruiter|event|friend|social|job board|university", re.I)


def pick_referral(labels: list[str]) -> str | None:
    usable = [l for l in labels if not _REFERRAL_EXCLUDE.search(l)]
    for pattern in _REFERRAL_OPTIONS:
        for label in usable:
            if re.search(pattern, label, re.I):
                return label
    return None


_REGIONAL_ASIAN = re.compile(r"\b(?:east|south|southeast|south-east|central|west|western)\s+asian\b", re.I)
_MIXED = re.compile(r"two or more|multi|mixed|prefer|decline|wish", re.I)


def pick_race(value: str, also: tuple[str, ...] | list[str] = ()) -> Callable[[list[str]], str | None]:
    """Option that clearly means `value` (tiered: exact, then 'Value (...)', then a broader grouping).
    Region-specific or mixed categories are never guessed; ambiguity returns None -> REVIEW."""
    word = value.strip().casefold()

    def pick(labels: list[str]) -> str | None:
        cleaned = [(l, re.sub(r"\(\s*not hispanic[^)]*\)", "", l, flags=re.I).strip()) for l in labels]
        usable = [(l, c) for l, c in cleaned if not _MIXED.search(c) and not re.search(r"hispanic|latin", c, re.I)
                  and not _REGIONAL_ASIAN.search(c)]
        tiers = [
            [l for l, c in usable if c.casefold() == word],
            [l for l, c in usable if re.match(re.escape(word) + r"\b", c, re.I) and "pacific" not in c.casefold()],
            [l for l, c in usable if re.search(r"\b" + re.escape(word) + r"\b", c, re.I)],
        ]
        for hits in tiers:
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                return None
        # No plain match: an explicitly approved equivalent (e.g. "South Asian") is exactly as acceptable.
        for alternative in (a.strip().casefold() for a in also if a.strip()):
            hits = [l for l, c in cleaned if c.casefold() == alternative and not _MIXED.search(c)
                    and not re.search(r"hispanic|latin", c, re.I)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                return None
        return None
    return pick


def pick_hispanic(is_hispanic: bool) -> Callable[[list[str]], str | None]:
    """'No' / 'Not Hispanic or Latino' (or the Yes equivalents); mixed or decline options are never chosen."""
    def pick(labels: list[str]) -> str | None:
        usable = [l for l in labels if not _MIXED.search(l)]
        if is_hispanic:
            tiers = [[l for l in usable if re.fullmatch(r"\s*yes\.?\s*", l, re.I)],
                     [l for l in usable if re.match(r"(?:yes\b|(?:i am )?(?:hispanic|latin[oax]))", l.strip(), re.I)
                      and not re.search(r"\bnot\b|non[- ]?hispanic", l, re.I)]]
        else:
            tiers = [[l for l in usable if re.fullmatch(r"\s*no\.?\s*", l, re.I)],
                     [l for l in usable if re.match(r"(?:no\b|(?:i am )?not\b|non[- ]?hispanic)", l.strip(), re.I)
                      and re.search(r"hispanic|latin|^no\b", l, re.I)]]
        for hits in tiers:
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                return None
        return None
    return pick


_NOT_VETERAN = re.compile(r"\bi am not a (?:protected )?veteran|\bnot a (?:protected )?veteran|\bi am not\b.*\bveteran|never served|"
                          r"no military service|(?:have|did) not (?:served|serve)|^no$", re.I)
_VETERAN_EXCLUDE = re.compile(r"identify as|\bi am (?:a|one)\b|disabled veteran|recently separated|service medal|decline|wish to|prefer not", re.I)


def pick_not_veteran(labels: list[str]) -> str | None:
    for label in labels:
        if _NOT_VETERAN.search(label.strip()) and not _VETERAN_EXCLUDE.search(label):
            return label
    return None


def pick_decline(labels: list[str]) -> str | None:
    known = {" ".join(x.replace("’", "'").casefold().split()) for x in DECLINE_LABELS}
    for label in labels:
        if " ".join(label.replace("’", "'").casefold().split()) in known:
            return label
    return None


# ------------------------------------------------------------------ resolution

def salary_text(field, ctx: Context) -> str | None:
    amount = getattr(ctx.answers, "desired_salary_usd", None)
    if not isinstance(amount, int) or isinstance(amount, bool):
        return None
    numeric = field.field_type == "number" or re.search(r"numeric|numbers? only|digits only|in usd|\\(usd\\)", field.label, re.I)
    return str(amount) if numeric else f"${amount:,}"


def _address_text(part: str, ctx: Context) -> str | None:
    p = ctx.profile
    value = {"line1": getattr(p.address, "line1", ""), "line2": getattr(p.address, "line2", ""),
             "postal": getattr(p.address, "postal_code", ""), "city": p.location.city,
             "state": p.location.state, "country": p.location.country}.get(part, "")
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_text(field, ctx: Context) -> str | None:
    """Value for a plain text/number field, or None (the caller keeps its own handling)."""
    if field.role == "combobox" or field.field_type not in {"text", "number", "textarea", "tel", "email"}:
        return None
    intent = classify_intent(field.label, ctx)
    if intent is None:
        return None
    p, prefs = ctx.profile, ctx.preferences
    if field.field_type == "textarea" and intent.name not in {"LANGUAGES"}:
        return None
    if intent.name == "SALARY":
        return salary_text(field, ctx)
    if intent.name in {"SCHOOL", "DEGREE", "DISCIPLINE"}:
        record = facts.top_education(p, ctx.today)
        if record is None:
            return None
        return {"SCHOOL": record.institution, "DEGREE": record.degree, "DISCIPLINE": record.field_of_study}[intent.name].strip() or None
    if intent.name in {"CURRENT_COMPANY", "CURRENT_TITLE"}:
        job = facts.most_recent_job(p, ctx.today)
        return None if job is None else (job.company if intent.name == "CURRENT_COMPANY" else job.title).strip() or None
    if intent.name == "PREFERRED_NAME":
        return (getattr(p.candidate, "preferred_name", "") or "").strip() or None
    if intent.name == "LEGAL_NAME":
        return facts.legal_full_name(p) or None
    if intent.name == "ADDRESS":
        return _address_text(intent.part, ctx)
    if intent.name == "YEARS_EXPERIENCE":
        years = facts.experience_years(p, ctx.today, intent.skill)
        return None if years is None else str(facts.whole_years(years))
    if intent.name == "PREFERRED_LOCATION":
        return getattr(getattr(prefs, "application_defaults", None), "preferred_location_fallback", None) or None
    if intent.name == "REFERRAL_SOURCE":
        return getattr(getattr(prefs, "application_defaults", None), "referral_source", None) or None
    if intent.name == "LANGUAGES":
        langs = [l for l in getattr(p, "languages", []) if isinstance(l, str) and l.strip()]
        if not langs:
            return None
        if re.search(r"other than english|besides english|in addition to english", field.label, re.I):
            langs = [l for l in langs if l.casefold() != "english"]
        return ", ".join(langs) or None
    return None


def resolve_choice(field, ctx: Context) -> ChoiceRequest | None:
    """ChoiceRequest for a combobox, or None. Every request is verified after selection."""
    if field.role != "combobox":
        return None
    intent = classify_intent(field.label, ctx)
    if intent is None:
        return None
    n, p, prefs = intent.name, ctx.profile, ctx.preferences
    if n == "CONSENT":                                            # a consent presented as a dropdown
        return ChoiceRequest(search="yes", labels=[], pick=pick_affirmative, no_search=True)
    if n == "AUTH_CATEGORY":
        auth = _flag(p.work_authorization.authorized_to_work_us)
        need = _flag(p.work_authorization.requires_sponsorship_now_or_in_future)
        if auth is True and need is False:
            return ChoiceRequest(search="authorized", labels=[], pick=pick_authorized(False, allow_category=False), no_search=True)
        return None
    if n == "EMPLOYMENT_HISTORY":
        company = ctx.company
        if company and not facts.worked_at(company, p):
            return ChoiceRequest(search="never", labels=[], pick=pick_never_worked, no_search=True)
        return None
    if n in {"SCHOOL", "DEGREE", "DISCIPLINE"}:
        record = facts.top_education(p, ctx.today)
        if record is None:
            return None
        if n == "SCHOOL":
            terms = school_search_terms(record.institution)
            return ChoiceRequest(search=terms[0], labels=[], pick=pick_school(record.institution), search_fallbacks=terms[1:])
        if n == "DEGREE":
            level = facts.degree_level(record.degree)
            return ChoiceRequest(search=level, labels=[], pick=pick_education(level), no_search=True) if level else None
        return ChoiceRequest(search=record.field_of_study, labels=[], pick=pick_contains(record.field_of_study), no_search=True)
    if n == "ADDRESS" and intent.part == "country":
        if field.field_id == "country":
            return None           # the phone-country selector; handled by the flag-aware legacy path
        return ChoiceRequest(search="united states", labels=[], pick=pick_country_us, no_search=True) \
            if (getattr(p.location, "country", "") or "").casefold() in _COUNTRY_US else None
    if n in {"US_AUTHORIZATION", "SPONSORSHIP", "RELOCATION", "ONSITE", "RELOCATION_ONSITE", "PRODUCT_FAMILIARITY",
             "PRIOR_EMPLOYMENT", "PRIOR_APPLICATION", "MILITARY", "THRESHOLD_YEARS", "DEGREE_HELD", "JOB_COUNTRY_AUTH"}:
        value = bool_answer(intent, ctx)
        if value is None:
            return None
        word = "Yes" if value else "No"
        if n == "PRODUCT_FAMILIARITY" and value:
            detail = getattr(ctx.answers, "product_usage_detail", None)
            return ChoiceRequest(search=word, labels=[], pick=pick_product_usage(detail), no_search=True)
        if n == "US_AUTHORIZATION" and value:
            need = _flag(p.work_authorization.requires_sponsorship_now_or_in_future)
            return ChoiceRequest(search=word, labels=[], pick=chain(pick_yes_no(word), pick_authorized(need, allow_category=False)), no_search=True)
        if n == "SPONSORSHIP" and not value:
            return ChoiceRequest(search=word, labels=[], pick=chain(pick_yes_no(word), pick_sponsorship_not_needed), no_search=True)
        return ChoiceRequest(search=word, labels=[], pick=pick_yes_no(word), no_search=True)
    if n == "VETERAN":
        if bool_answer(intent, ctx) is False:
            return ChoiceRequest(search="not a veteran", labels=[], pick=pick_not_veteran, no_search=True)
        return None   # an explicit fact exists; never fall back to "decline" for veterans
    if n == "HISPANIC":
        fact = getattr(getattr(p, "demographics", None), "hispanic_latino", None)
        if isinstance(fact, bool):
            return ChoiceRequest(search="no" if not fact else "yes", labels=[], pick=pick_hispanic(fact), no_search=True)
    if n == "RACE":
        fact = getattr(getattr(p, "demographics", None), "race_ethnicity", None)
        if isinstance(fact, str) and fact.strip():
            # An explicit fact exists: pick it, or leave the question for review. Never fall back to "decline".
            also = [a for a in (getattr(getattr(p, "demographics", None), "race_ethnicity_also", None) or []) if isinstance(a, str)]
            return ChoiceRequest(search=fact, labels=[], pick=pick_race(fact, also), no_search=True)
    if n in {"EEO", "RACE", "HISPANIC"}:
        if getattr(ctx.answers, "eeo_default", None) != "decline":
            return None
        return ChoiceRequest(search="decline", labels=list(DECLINE_LABELS), pick=chain(pick_decline, pick_decline_semantic), no_search=True)
    if n == "LANGUAGES":
        langs = [l for l in getattr(p, "languages", []) if isinstance(l, str) and l.strip()]
        if re.search(r"other than english|besides english|in addition to english", field.label, re.I):
            langs = [l for l in langs if l.casefold() != "english"]
        return ChoiceRequest(search=langs[0], labels=[], pick=pick_exact(langs[0]), no_search=True) if len(langs) == 1 else None
    if n == "EDUCATION":
        level = facts.highest_education(p, ctx.today)
        return ChoiceRequest(search=level, labels=[], pick=pick_education(level), no_search=True) if level else None
    if n == "YEARS_EXPERIENCE":
        years = facts.experience_years(p, ctx.today, intent.skill)
        if years is None:
            return None
        rounded = facts.whole_years(years)   # same round-up rule as text fields
        return ChoiceRequest(search="years", labels=[], pick=lambda labels, y=rounded: facts.pick_year_range(labels, y),
                             no_search=True)
    if n == "PREFERRED_LOCATION":
        return ChoiceRequest(search="first", labels=[], pick=first_valid, no_search=True)
    if n == "REFERRAL_SOURCE":
        if not getattr(getattr(prefs, "application_defaults", None), "referral_source", None):
            return None
        return ChoiceRequest(search="company website", labels=[], pick=pick_referral, no_search=True)
    if n == "ADDRESS" and intent.part == "state":
        from app.jobs.browserskill_greenhouse import US_STATE_NAMES   # lazy: avoids a circular import
        state = _address_text("state", ctx)
        return ChoiceRequest(search=state, labels=[state, US_STATE_NAMES.get(state, state)]) if state else None
    return None
