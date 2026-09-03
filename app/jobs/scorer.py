import json

from pydantic import BaseModel, Field

from app.config.models import Profile
from app.jobs.models import Job
from app.llm.client import ask_llm
from app.profile_utils import calculate_total_experience_years


class JobScore(BaseModel):
    skill_match: int = Field(ge=0, le=100)
    experience_match: int = Field(ge=0, le=100)
    role_alignment: int = Field(ge=0, le=100)
    overall_score: int = Field(ge=0, le=100)
    explanation: str


def score_job(
    job: Job,
    profile: Profile,
) -> JobScore:
    total_experience_years = (
        calculate_total_experience_years(profile)
    )

    candidate_summary = {
        "total_experience_years": total_experience_years,
        "experience": [
            {
                "company": exp.company,
                "title": exp.title,
                "description": exp.description,
                "technologies": exp.technologies,
            }
            for exp in profile.experience
        ],
        "skills": profile.skills.model_dump(),
        "projects": [
            {
                "name": project.name,
                "description": project.description,
                "technologies": project.technologies,
            }
            for project in profile.projects
        ],
    }

    job_summary = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "required_experience_years": (
            job.required_experience_years
        ),
        "seniority": job.seniority,
        "work_arrangement": job.work_arrangement,
        "description": job.description[:7000],
    }

    prompt = f"""
Evaluate how well this candidate matches this job.

Return ONLY valid JSON:

{{
  "skill_match": 0,
  "experience_match": 0,
  "role_alignment": 0,
  "overall_score": 0,
  "explanation": ""
}}

SCORING RULES:

1. GENERAL SCORING

- Every score must be an integer from 0 to 100.
- Use only the information provided below.
- Do not invent candidate experience, skills, projects,
  achievements, employers, metrics, or technologies.
- Prioritize required skills and responsibilities more than
  preferred or nice-to-have skills.
- Penalize meaningful missing requirements.
- Keep the explanation concise.

2. EXPERIENCE

- Use the provided total_experience_years value.
- Do NOT independently calculate, estimate, or infer the
  candidate's total professional experience.
- Compare total_experience_years against the job's required
  experience when that requirement is available.
- Do not inflate experience because of job title, seniority,
  project scope, employer reputation, or perceived impact.
- If the candidate is below the stated experience requirement,
  reflect that fact accurately in experience_match.

3. DIRECT EXPERIENCE

A technology may be described as direct candidate experience
ONLY when it appears explicitly in the candidate profile.

For example:

If Redshift appears in the candidate profile:

CORRECT:
"The candidate has direct Redshift experience."

If BigQuery does not appear in the candidate profile:

INCORRECT:
"The candidate has BigQuery experience."

4. JOB DESCRIPTION VS CANDIDATE PROFILE

Never treat a technology appearing only in the JOB DESCRIPTION
as candidate experience.

Technologies listed in the job description are requirements,
preferences, or context for the role.

They are NOT evidence that the candidate has:

- used the technology
- evaluated the technology
- been exposed to the technology
- worked with the technology
- implemented the technology
- learned the technology

Do not invent phrases such as:

- "Debezium evaluation context"
- "exposure to Fivetran"
- "familiarity with Sigma"
- "experience with BigQuery"

unless that fact is explicitly supported by the candidate profile.

5. TRANSFERABLE EXPERIENCE

Related technologies may receive transferable credit.

Examples:

- Redshift may provide transferable cloud data warehouse
  knowledge relevant to BigQuery or Snowflake.
- AWS may provide transferable cloud knowledge relevant
  to Azure or GCP.
- Tableau or Power BI may provide transferable BI knowledge
  relevant to Looker or Sigma.
- Kafka may provide transferable streaming knowledge relevant
  to other streaming or CDC tools.

However, clearly distinguish transferable experience from
direct experience.

CORRECT:

"The candidate does not list BigQuery directly, but their
Redshift experience provides transferable cloud warehouse
knowledge."

INCORRECT:

"The candidate has BigQuery experience."

CORRECT:

"The candidate's Kafka background provides some transferable
streaming knowledge relevant to the role's CDC requirements."

INCORRECT:

"The candidate has Debezium experience."

6. MISSING TECHNOLOGIES

If a job requires or prefers a technology that is absent from
the candidate profile:

- explicitly identify it as missing when it is important
- optionally note closely related transferable experience
- never convert related experience into direct experience
- do not invent exposure, evaluation, familiarity, or usage

7. SKILL MATCH

When calculating skill_match:

- Give strongest credit to explicit direct matches.
- Give partial credit to genuinely related transferable skills.
- Give little or no credit when neither direct nor meaningfully
  transferable experience exists.
- Nice-to-have technologies should have less effect than core
  requirements.

8. ROLE ALIGNMENT

Consider whether the candidate's actual experience,
responsibilities, and projects align with the work described.

Do not raise role_alignment merely because:

- the employer is well known
- the candidate has a similar title
- the candidate seems capable of learning missing technologies

Base the score on actual supplied evidence.

9. EXPLANATION

The explanation must:

- accurately distinguish direct experience from transferable
  experience
- accurately state missing requirements
- use the supplied total_experience_years
- never introduce candidate facts that are absent from the
  candidate profile
- never use technologies from the job description as evidence
  of candidate experience
- avoid exaggerated language such as "perfect fit" unless the
  supplied facts genuinely support it

Return JSON only.
Do not use markdown.

CANDIDATE:
{json.dumps(candidate_summary)}

JOB:
{json.dumps(job_summary)}
"""

    response = ask_llm(
        prompt,
        temperature=0.1,
    ).strip()

    if not response:
        raise RuntimeError(
            "Qwen returned an empty response "
            "while scoring the job."
        )

    try:
        data = json.loads(response)

    except json.JSONDecodeError:
        print("Raw Qwen response:")
        print(response)
        raise

    return JobScore.model_validate(data)


def classify_score(
    overall_score: int,
    auto_apply_minimum: int,
    review_minimum: int,
) -> str:
    if overall_score >= auto_apply_minimum:
        return "AUTO_APPLY"

    if overall_score >= review_minimum:
        return "REVIEW"

    return "SKIP"