"""Deterministic facts derived from profile.yaml and the application ledger. No LLM here."""
import math
import re
from datetime import date

from app.profile_utils import parse_profile_date

COMPANY_SUFFIXES = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "gmbh"}


def normalize_company(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", name.casefold()).split()
    while words and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def squash(name: str) -> str:
    return normalize_company(name).replace(" ", "")


def worked_at(company: str, profile) -> bool:
    """Employment history is authoritative and complete: listed -> True, otherwise False."""
    asked = normalize_company(company)
    if not asked:
        raise ValueError("company is empty")
    for job in profile.experience:
        known = normalize_company(job.company)
        # 'Amazon Web Services' is Amazon; 'Raven Software' is Raven Software Solutions.
        if asked == known or asked.startswith(known + " ") or known.startswith(asked + " "):
            return True
    return False


# ---------------- education ----------------

LEVELS = ["High school", "Bachelor's", "Master's", "Doctorate"]
_LEVEL_PATTERNS = [
    ("Doctorate", r"(?<![a-z])(?:ph\.?\s?d|doctor\w*|dphil|edd)(?![a-z])"),
    ("Master's", r"(?<![a-z])(?:m\.?\s?s\.?c?|m\.?\s?tech|m\.?\s?eng|m\.?a|mba|master\w*|mca)(?![a-z])"),
    ("Bachelor's", r"(?<![a-z])(?:b\.?\s?s\.?c?|b\.?\s?tech|b\.?\s?e|b\.?a|bachelor\w*|bca|b\.?\s?eng)(?![a-z])"),
    ("High school", r"(?<![a-z])(?:high school|ged|secondary)(?![a-z])"),
]


def degree_level(degree: str) -> str | None:
    text = degree.casefold().strip()
    for level, pattern in _LEVEL_PATTERNS:
        if re.search(pattern, text):
            return level
    return None


def highest_education(profile, today: date | None = None) -> str | None:
    """Highest *completed* degree level, from profile dates; None if none can be established."""
    today = today or date.today()
    best = -1
    for item in profile.education:
        if not item.end_date:
            continue
        if parse_profile_date(item.end_date).date() > today:
            continue  # not finished yet
        level = degree_level(item.degree)
        if level:
            best = max(best, LEVELS.index(level))
    return LEVELS[best] if best >= 0 else None


# ---------------- experience ----------------

def _month_index(value: str) -> int:
    parsed = parse_profile_date(value)
    return parsed.year * 12 + parsed.month - 1


def _merged_months(intervals: list[tuple[int, int]]) -> int:
    """Total months covered by [start, end) intervals; overlaps are never double-counted."""
    total, current_end = 0, None
    for start, end in sorted(intervals):
        if current_end is None or start > current_end:
            total += end - start
            current_end = end
        elif end > current_end:
            total += end - current_end
            current_end = end
    return total


def _interval(job, today: date) -> tuple[int, int]:
    start = _month_index(job.start_date)
    end = _month_index(job.end_date) + 1 if job.end_date else today.year * 12 + today.month  # months inclusive
    return start, max(end, start)


def experience_years(profile, today: date | None = None, skill: str | None = None) -> float | None:
    """Years from employment dates (gaps excluded, overlaps merged). With `skill`, only jobs whose
    technologies list it; None when no employment evidence supports the skill."""
    today = today or date.today()
    jobs = profile.experience
    if skill is not None:
        wanted = skill.casefold().strip()
        jobs = [j for j in jobs if wanted in {t.casefold().strip() for t in j.technologies}]
        if not jobs:
            return None
    return _merged_months([_interval(j, today) for j in jobs]) / 12


def whole_years(years: float) -> int:
    """Years are always rounded up, never down (user policy): 3.9 -> 4, 0.92 -> 1, exactly 3.0 -> 3."""
    return int(math.ceil(years - 1e-9))


_RANGE = re.compile(
    r"(?:(?P<lt>less than|under|<)\s*(?P<lt_n>\d+))|"
    r"(?:(?P<lo>\d+)\s*(?:-|–|to)\s*(?P<hi>\d+))|"
    r"(?:(?P<plus>\d+)\s*(?:\+|or more|and (?:above|over)|plus))", re.IGNORECASE)


def pick_year_range(labels: list[str], years: float) -> str | None:
    """The single option whose numeric range contains `years`.

    Ranges that share a boundary ("1-3", "3-5") are half-open at the shared number, so 3.9 years is
    unambiguously "3-5"; otherwise "3-5" covers everything up to 5.99.
    """
    parsed = []
    for label in labels:
        m = _RANGE.search(label)
        if not m:
            continue
        if m.group("lt"):
            parsed.append((label, 0.0, float(m.group("lt_n")), True))
        elif m.group("lo"):
            parsed.append((label, float(m.group("lo")), float(m.group("hi")), None))
        else:
            parsed.append((label, float(m.group("plus")), math.inf, True))
    starts = {lo for _, lo, _, _ in parsed}
    matches = []
    for label, lo, hi, exclusive in parsed:
        end = hi if (exclusive or hi in starts) else hi + 1
        if lo <= years < end:
            matches.append(label)
    return matches[0] if len(matches) == 1 else None


# ---------------- application ledger ----------------

def prior_application(company: str, ledger: dict) -> bool | None:
    """True: confirmed prior application. False: none recorded. None: ledger is ambiguous."""
    target = squash(company)
    statuses = []
    for url, status in ledger.items():
        parts = re.sub(r"^https?://[^/]+/", "", url).split("/")
        if parts and squash(parts[0].replace("-", " ")) == target:
            statuses.append(status)
    if "CONFIRMED" in statuses:
        return True
    if any(s in {"ATTEMPTING", "UNCONFIRMED"} for s in statuses):
        return None  # a click may have gone through; a person must decide
    return False


# ---------------- education records, employer, names ----------------

def completed_education(profile, today: date | None = None) -> list:
    """Education records with a finished end date, best (highest level, then latest) first."""
    today = today or date.today()
    done = []
    for item in profile.education:
        if item.end_date and parse_profile_date(item.end_date).date() <= today:
            level = degree_level(item.degree)
            rank = LEVELS.index(level) if level else -1
            done.append((rank, parse_profile_date(item.end_date), item))
    done.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [item for _, _, item in done]


def top_education(profile, today: date | None = None):
    records = completed_education(profile, today)
    return records[0] if records else None


def most_recent_job(profile, today: date | None = None):
    """The current job if any, else the one that ended last."""
    today = today or date.today()
    jobs = list(profile.experience)
    if not jobs:
        return None
    return max(jobs, key=lambda j: _interval(j, today)[1])


def legal_full_name(profile) -> str:
    c = profile.candidate
    return " ".join(p.strip() for p in (c.first_name, getattr(c, "middle_name", ""), c.last_name) if p and p.strip())


# ---------------- thresholds ("at least 5 years ...") ----------------

GENERIC_EXPERIENCE = re.compile(
    r"^(?:(?:professional|relevant|work|industry|total|overall|full[- ]time|related|hands[- ]on|software|engineering)\s*)+$", re.I)

# domain keyword -> evidence terms looked for in a job's technologies and description
DOMAIN_EVIDENCE = {
    "etl": ["etl", "elt", "pipeline", "airflow", "aws glue", "glue", "dbt", "pyspark", "spark", "ssis", "informatica", "datastage"],
    "data pipeline": ["pipeline", "etl", "airflow", "aws glue", "dbt", "pyspark", "spark"],
    "data engineering": ["data engineer"],
    "data warehouse": ["redshift", "warehouse", "snowflake", "bigquery"],
    "analytics": ["analytics", "analyst", "tableau", "reporting"],
}


def _job_matches(job, terms: list[str]) -> bool:
    haystack = " ".join([job.title, job.description, *job.technologies]).casefold()
    return any(term in haystack for term in terms)


def domain_years(profile, domain: str, today: date | None = None) -> float | None:
    """Years of *supported* experience in `domain`; None when the evidence cannot say."""
    today = today or date.today()
    text = re.sub(r"\([^)]*\)", " ", domain.casefold())
    text = " ".join(text.split())
    if not text or GENERIC_EXPERIENCE.match(text):
        return experience_years(profile, today)
    matched = [k for k in DOMAIN_EVIDENCE if k in text]
    if len({k for k in matched if k not in ("etl", "data pipeline")} | ({"etl"} if {"etl", "data pipeline"} & set(matched) else set())) > 1:
        return None   # a compound requirement ("data engineering and analytics") needs evidence for every part
    for key, terms in DOMAIN_EVIDENCE.items():
        if key in text:
            jobs = [j for j in profile.experience if _job_matches(j, terms)]
            return _merged_months([_interval(j, today) for j in jobs]) / 12 if jobs else 0.0
    named = [t for t in sorted({t for j in profile.experience for t in j.technologies}, key=len, reverse=True)
             if re.search(r"(?<![a-z0-9+#])" + re.escape(t.casefold()) + r"(?![a-z0-9+#])", text)]
    from app.jobs.grounding import TECH_VOCAB   # lazy: grounding imports this module
    mentioned = {t for t in TECH_VOCAB if re.search(r"(?<![a-z0-9+#])" + re.escape(t) + r"(?![a-z0-9+#])", text)}
    if len(mentioned | {t.casefold() for t in named}) > 1:
        return None   # "Python and Java": one technology's years do not establish the other
    return experience_years(profile, today, named[0]) if named else None


def meets_experience_threshold(profile, minimum: float, domain: str = "", today: date | None = None) -> bool | None:
    """True/False when the dates decide it; None when they cannot. Years are exact, never rounded up.

    If *total* experience is already below the minimum, no sub-domain can reach it, so the answer is
    No even for domains the evidence cannot isolate.
    """
    today = today or date.today()
    total = experience_years(profile, today) or 0.0
    if total < minimum - 1e-9:
        return False
    years = domain_years(profile, domain, today)
    if years is None:
        return None
    return years >= minimum - 1e-9


# ---------------- degree held ("Do you have a Bachelor's degree in ...?") ----------------

_QUANT_FIELDS = re.compile(
    r"computer|software|information|data|math|statistic|engineering|physic|econom|operations research|analytics|quantitative|science", re.I)


def holds_degree(profile, level: str, field_text: str = "", today: date | None = None) -> bool | None:
    """True/False from completed education records; None when the named field cannot be matched."""
    if level not in LEVELS:
        return None
    rank = LEVELS.index(level)
    qualifying = [e for e in completed_education(profile, today)
                  if (degree_level(e.degree) in LEVELS and LEVELS.index(degree_level(e.degree)) >= rank)]
    if not qualifying:
        return False
    text = " ".join(field_text.casefold().split())
    if not text:
        return True
    terms = [re.sub(r"^(?:a|an|the)\s+|\s+(?:field|fields|related|discipline)s?$", "", t.strip()) for t in re.split(r"\bor\b|,|/", text)]
    for record in qualifying:
        field = record.field_of_study.casefold()
        for term in terms:
            if not term:
                continue
            if term in field or field in term:
                return True
            if re.search(r"quant", term) and _QUANT_FIELDS.search(field):
                return True
    return None
