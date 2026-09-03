import json

from pydantic import BaseModel

from app.config.models import Profile
from app.jobs.models import Job
from app.llm.client import ask_llm


class GeneratedAnswer(BaseModel):
    answer: str
    confidence: str


def generate_application_answer(
    question: str,
    profile: Profile,
    job: Job,
) -> GeneratedAnswer:
    candidate_context = {
        "experience": [
            {
                "company": exp.company,
                "title": exp.title,
                "description": exp.description,
                "technologies": exp.technologies,
            }
            for exp in profile.experience
        ],
        "projects": [
            {
                "name": project.name,
                "description": project.description,
                "technologies": project.technologies,
            }
            for project in profile.projects
        ],
        "skills": profile.skills.model_dump(),
    }

    job_context = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "description": job.description[:6000],
    }

    prompt = f"""
You are answering a job application question.

Return ONLY valid JSON:

{{
  "answer": "",
  "confidence": "HIGH"
}}

GROUNDING RULES:

1. DIRECT EXPERIENCE

You may say:
"I have experience with X"
"I used X"
"I built X"

ONLY if X is explicitly present in the candidate profile.

Never convert a related technology into direct experience.

Example:

If candidate has Redshift but not BigQuery:

CORRECT:
"My experience with Redshift gives me transferable
cloud data warehouse experience relevant to BigQuery."

INCORRECT:
"I have BigQuery experience."

2. TRANSFERABLE EXPERIENCE

You may connect related experience when appropriate.

Examples:

Redshift -> transferable warehouse knowledge for BigQuery/Snowflake
AWS -> transferable cloud knowledge for GCP/Azure
Tableau/Power BI -> transferable BI knowledge for Looker

Always describe these as transferable or related experience,
not direct experience.

3. MISSING REQUIREMENTS

The candidate does NOT need to meet every job requirement
to answer a motivation question.

Do not refuse to answer "Why this company?" or
"Why this role?" merely because the candidate is missing
some required technologies or years of experience.

Simply avoid claiming those missing qualifications.

4. MOTIVATION QUESTIONS

For questions such as:

"Why are you interested in working here?"
"Why this company?"
"Why this role?"

Construct a truthful motivation by connecting:

- the company's mission, product, or work
- responsibilities described in the job
- relevant parts of the candidate's actual background

Focus on genuine overlap.

You may say:

"This role aligns with my experience..."
"I am interested in the opportunity to..."
"My background in X aligns with..."

You must NOT invent:

- personal history with the company
- having used the company's product
- knowing employees there
- following the company for years
- a personal connection to the company's mission
- experience the candidate does not have

For a motivation question, confidence may be HIGH
when a truthful motivation can be constructed from
the supplied job and candidate information.

5. FACTUAL QUESTIONS

For factual questions such as:

"How many years have you used BigQuery?"
"Have you worked in healthcare?"
"Do you require sponsorship?"
"What is your notice period?"

ONLY answer when the candidate data explicitly supports
the answer.

If the required fact is unavailable, return:

{{
  "answer": "",
  "confidence": "LOW"
}}

6. GENERAL RULES

- Never invent experience.
- Never invent technologies.
- Never invent employers, projects, metrics, or achievements.
- Do not exaggerate.
- Keep the answer concise and natural.
- Prefer approximately 2-4 sentences unless the question
  clearly requires more detail.
- Do not use markdown.
- confidence must be exactly HIGH, MEDIUM, or LOW.
- Return JSON only.

QUESTION:
{question}

CANDIDATE:
{json.dumps(candidate_context)}

JOB:
{json.dumps(job_context)}
"""

    response = ask_llm(
        prompt,
        temperature=0.1,
    ).strip()

    if not response:
        return GeneratedAnswer(
            answer="",
            confidence="LOW",
        )

    try:
        data = json.loads(response)

    except json.JSONDecodeError:
        print("Raw Answer Engine response:")
        print(response)

        return GeneratedAnswer(
            answer="",
            confidence="LOW",
        )

    return GeneratedAnswer.model_validate(data)