import json

from pydantic import ValidationError

from app.jobs.models import ExtractedJobData, Job
from app.llm.client import ask_llm


def extract_job(
    title: str,
    company: str,
    location: str,
    description: str,
    source: str,
    url: str,
) -> Job:
    prompt = f"""
Extract structured job information from the job description below.

Return ONLY valid JSON.

Use exactly this structure:

{{
  "required_experience_years": null,
  "seniority": null,
  "employment_type": null,
  "work_arrangement": null,
  "sponsorship_available": null,
  "security_clearance_required": null
}}

Rules:
- required_experience_years must be an integer or null.
- seniority must be one of:
  Entry Level, Associate, Mid Level, Senior, Staff,
  Principal, Director, VP, or null.
- employment_type must be one of:
  Full Time, Part Time, Contract, Internship, Temporary, or null.
- work_arrangement must be one of:
  Remote, Hybrid, Onsite, or null.
- Do not guess.
- Use null when the description does not clearly support a value.
- Do not include markdown.
- Do not include explanations.
- sponsorship_available must be true, false, or null.
- Set sponsorship_available to false only when the description
  explicitly says sponsorship is not available, cannot be provided,
  or candidates must not require sponsorship.
- Set sponsorship_available to true only when sponsorship is
  explicitly offered or supported.
- Otherwise use null.
- security_clearance_required must be true, false, or null.
- Set it to true only when the position explicitly requires an
  active security clearance or requires obtaining/maintaining one.
- Set it to false only when the description explicitly indicates
  that clearance is not required.
- Otherwise use null.
- Return JSON only.

Job title:
{title}

Job description:
{description}
"""

    response = ask_llm(prompt)

    extracted = parse_extracted_job_data(response)

    return Job(
        title=title,
        company=company,
        location=location,
        description=description,
        required_experience_years=extracted.required_experience_years,
        seniority=extracted.seniority,
        employment_type=extracted.employment_type,
        work_arrangement=extracted.work_arrangement,
        sponsorship_available=extracted.sponsorship_available,
        security_clearance_required=extracted.security_clearance_required,
        source=source,
        url=url,
    )


def parse_extracted_job_data(response: str) -> ExtractedJobData:
    try:
        raw_data = json.loads(response)

        return ExtractedJobData.model_validate(raw_data)

    except json.JSONDecodeError:
        print("Warning: Qwen returned invalid JSON.")

    except ValidationError:
        print("Warning: Qwen returned JSON that failed validation.")

    return ExtractedJobData(
        required_experience_years=None,
        seniority=None,
        employment_type=None,
        work_arrangement=None,
        sponsorship_available=None,
        security_clearance_required=None
    )