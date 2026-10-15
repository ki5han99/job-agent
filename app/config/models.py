from pydantic import BaseModel


class Candidate(BaseModel):
    first_name: str
    middle_name: str
    last_name: str
    preferred_name: str


class Contact(BaseModel):
    email: str
    phone: str


class Location(BaseModel):
    city: str
    state: str
    country: str


class Links(BaseModel):
    linkedin: str
    github: str
    portfolio: str


class WorkAuthorization(BaseModel):
    authorized_to_work_us: bool | None
    requires_sponsorship: bool | None
    requires_sponsorship_now_or_in_future: bool | None = None
    authorization_type: str


class ApprovedAnswers(BaseModel):
    """Explicitly user-approved facts; never inferred. None means unknown -> REVIEW."""
    desired_salary: str | None = None
    nyc_based_or_willing_to_relocate: bool | None = None
    onsite_days_per_week_willing: int | None = None


class Military(BaseModel):
    """Explicit user-approved facts; None means unknown -> REVIEW."""
    served: bool | None = None
    is_veteran: bool | None = None


class Demographics(BaseModel):
    """Explicitly approved EEO facts. None = no approved fact -> the EEO decline default applies."""
    race_ethnicity: str | None = None
    race_ethnicity_also: list[str] = []      # equally acceptable categories when the primary one is not offered
    hispanic_latino: bool | None = None


class Address(BaseModel):
    """Street-level address; city/state/country come from Profile.location (single source)."""
    line1: str = ""
    line2: str = ""
    postal_code: str = ""


class Education(BaseModel):
    institution: str
    degree: str
    field_of_study: str
    start_date: str | None
    end_date: str | None


class Experience(BaseModel):
    company: str
    title: str
    location: str
    start_date: str
    end_date: str | None
    current: bool
    description: str
    technologies: list[str]


class Skills(BaseModel):
    programming: list[str]
    data_engineering: list[str]
    cloud: list[str]
    databases: list[str]
    orchestration: list[str]
    devops: list[str]
    analytics: list[str]
    ai_ml: list[str]


class Project(BaseModel):
    name: str
    description: str
    technologies: list[str]


class Profile(BaseModel):
    candidate: Candidate
    contact: Contact
    location: Location
    links: Links
    work_authorization: WorkAuthorization
    approved_answers: ApprovedAnswers = ApprovedAnswers()
    address: Address = Address()
    languages: list[str] = []
    military: Military = Military()
    demographics: Demographics = Demographics()
    education: list[Education]
    experience: list[Experience]
    projects: list[Project]
    skills: Skills


class TestJobConfig(BaseModel):
    company: str
    title: str
    url: str


class TestJobsConfig(BaseModel):
    default_job: str
    jobs: dict[str, TestJobConfig]


class WorkArrangements(BaseModel):
    remote: bool
    hybrid: bool
    onsite: bool


class LocationPreferences(BaseModel):
    preferred: list[str]
    excluded: list[str]


class ExperiencePreferences(BaseModel):
    maximum_required_years: int


class SeniorityPreferences(BaseModel):
    allowed: list[str]
    excluded: list[str]


class HardFilters(BaseModel):
    active_security_clearance_required: bool
    explicit_no_sponsorship: bool | None


class ScoringPreferences(BaseModel):
    auto_apply_minimum: int
    review_minimum: int


class RelocationPreferences(BaseModel):
    willing_anywhere: bool | None = None


class OnsitePreferences(BaseModel):
    willing: bool | None = None


class ApplicationDefaults(BaseModel):
    preferred_location_fallback: str | None = None  # free-text location when no options exist
    referral_source: str | None = None


class ConsentPolicy(BaseModel):
    """Consent categories the user approved for employment-application checkboxes."""
    approved_categories: list[str] = []


class AnswerPolicies(BaseModel):
    """Approved standing answers/policies (data/answers.yaml); empty means nothing approved."""
    desired_salary_usd: int | None = None
    product_familiarity_default: bool | None = None
    product_usage_detail: str | None = None   # "personal": which 'Yes, ...' option to take when several exist
    eeo_default: str | None = None  # "decline"
    consent: ConsentPolicy = ConsentPolicy()
    cover_letter_generation: bool | None = None


class Preferences(BaseModel):
    target_roles: list[str]
    work_arrangements: WorkArrangements
    locations: LocationPreferences
    experience: ExperiencePreferences
    seniority: SeniorityPreferences
    employment_types: list[str]
    hard_filters: HardFilters
    scoring: ScoringPreferences
    relocation: RelocationPreferences = RelocationPreferences()
    onsite: OnsitePreferences = OnsitePreferences()
    application_defaults: ApplicationDefaults = ApplicationDefaults()
