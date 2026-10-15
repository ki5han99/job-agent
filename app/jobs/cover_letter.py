"""LLM cover letters; filled only when every factual claim validates against the profile."""
import re
from pathlib import Path

from app.jobs.grounding import ungrounded_claims
from app.jobs import profile_facts as facts

GENERATED_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"


def _evidence(profile) -> dict:
    return {
        "name": f"{profile.candidate.first_name} {profile.candidate.last_name}".strip(),
        "total_experience_years": round(facts.experience_years(profile) or 0, 1),
        "highest_education": facts.highest_education(profile),
        "education": [{"degree": e.degree, "field": e.field_of_study, "institution": e.institution} for e in profile.education],
        "experience": [{"company": e.company, "title": e.title, "description": e.description,
                        "technologies": e.technologies} for e in profile.experience],
        "projects": [{"name": p.name, "description": p.description, "technologies": p.technologies} for p in profile.projects],
    }


def generate_cover_letter(profile, job, ask=None) -> str | None:
    """A grounded cover letter, or None if the model's draft makes any unsupported claim."""
    if ask is None:
        from app.llm.client import ask_llm as ask
    import json
    prompt = f"""Write a concise, professional cover letter (170-230 words, three short paragraphs, no placeholders).

STRICT RULES:
- Use ONLY the candidate evidence below. Do not invent employers, projects, technologies, metrics, years, degrees or achievements.
- Do not claim to use, follow or be a fan of the company's products.
- Tailor it to the job, referring only to facts in the job description.
- Sign off with the candidate's name.

CANDIDATE EVIDENCE (JSON):
{json.dumps(_evidence(profile), indent=2)}

JOB:
Title: {job.title}
Company: {job.company}
Description: {(getattr(job, 'description', '') or '')[:5000]}

Return ONLY the letter text."""
    text = (ask(prompt, 0.3) or "").strip()
    text = re.sub(r"^```\w*\n|\n```$", "", text).strip()
    if len(text) < 200 or re.search(r"\[[^\]]{2,40}\]|\{\{", text):   # too short, or leftover placeholders
        return None
    return text if not ungrounded_claims(text, profile, job) else None


def write_cover_letter_file(text: str, company: str) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", company).strip("_") or "company"
    path = GENERATED_DIR / f"Cover_Letter_{slug}.txt"
    path.write_text(text + "\n", encoding="utf-8")
    return path
