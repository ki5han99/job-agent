import json
from pydantic import BaseModel, Field

from app.config.models import Profile
from app.jobs.models import Job
from app.llm.client import ask_llm


class JobScore(BaseModel):
    skill_match: int = Field(ge=0, le=100)
    experience_match: int = Field(ge=0, le=100)
    role_alignment: int = Field(ge=0, le=100)
    overall_score: int = Field(ge=0, le=100)
    explanation: str

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


def score_job(job: Job, profile: Profile) -> JobScore:
    candidate_summary = {
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
        "required_experience_years": job.required_experience_years,
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

Rules:
- Scores must be integers from 0 to 100.
- Use only the provided information.
- Do not invent candidate experience.
- Prioritize required job skills.
- Penalize important missing requirements.
- Keep explanation under 3 sentences.
- Return JSON only. No markdown.

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
        raise RuntimeError("Qwen returned an empty response while scoring the job.")

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        print("Raw Qwen response:")
        print(response)
        raise

    return JobScore.model_validate(data)