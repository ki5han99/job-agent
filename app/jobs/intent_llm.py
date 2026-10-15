"""Optional LLM intent classification. The model names an intent; it never supplies an answer."""
import json
import re

from app.jobs.policy import INTENTS

PROMPT = """Classify this job-application form question into ONE intent, or "NONE".

Intents: {intents}

Return ONLY JSON: {{"intent": "<INTENT or NONE>", "company": <string or null>, "skill": <string or null>,
"negated": <true if the question asks the opposite polarity, e.g. "Can you work WITHOUT sponsorship?">,
"country": <country the question is about, or null>}}

Question: {label}"""


def classify_with_llm(label: str, ask=None) -> dict | None:
    if ask is None:
        from app.llm.client import ask_llm as ask
    raw = ask(PROMPT.format(intents=", ".join(sorted(INTENTS)), label=label), 0.0)
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("intent") in INTENTS else None
