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
    authorization_type: str


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
    education: list[Education]
    experience: list[Experience]
    projects: list[Project]
    skills: Skills

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


class Preferences(BaseModel):
    target_roles: list[str]
    work_arrangements: WorkArrangements
    locations: LocationPreferences
    experience: ExperiencePreferences
    seniority: SeniorityPreferences
    employment_types: list[str]
    hard_filters: HardFilters
    scoring: ScoringPreferences    