"""Claim validation for generated prose: every factual claim must trace to candidate or job evidence."""
import re

from app.jobs import profile_facts as facts

# Personal-affinity claims the candidate profile can never support.
UNSUPPORTED_PERSONAL_CLAIMS = re.compile(
    r"\bI(?:'m| am) (?:a |an )?(?:big |huge |avid |die-?hard |lifelong )?(?:fan|athlete|player|user|customer|member)\b"
    r"|\bI(?:'ve| have)? (?:always )?(?:played|follow(?:ed)?|watch(?:ed)?|use[ds]?|bet|wagered)\b"
    r"|\bI (?:play|follow|watch|use|love|enjoy)\b|\bmy (?:favorite|favourite)\b|\bgrowing up\b"
    r"|\bsince I was\b|\bmy (?:friends|family|colleagues)\b", re.IGNORECASE)

# Technologies that would be a checkable skill claim if named without evidence.
TECH_VOCAB = {
    "snowflake", "databricks", "bigquery", "redshift", "spark", "pyspark", "kafka", "flink", "airflow", "dbt", "dagster",
    "prefect", "fivetran", "airbyte", "hadoop", "hive", "presto", "trino", "clickhouse", "mongodb", "cassandra",
    "dynamodb", "elasticsearch", "postgresql", "postgres", "mysql", "oracle", "kubernetes", "docker", "terraform",
    "jenkins", "aws", "azure", "gcp", "python", "java", "scala", "rust", "golang", "go", "typescript", "javascript",
    "react", "tableau", "looker", "power bi", "pytorch", "tensorflow", "langchain", "langgraph", "pinecone", "faiss",
    "ansible", "datadog", "splunk", "informatica", "datastage", "ssis", "delta lake", "iceberg", "hudi", "snowpark",
}


def candidate_evidence(profile) -> set[str]:
    terms: set[str] = set()
    for group in profile.skills.model_dump().values():
        terms.update(t.casefold() for t in group)
    for job in profile.experience:
        terms.update(t.casefold() for t in job.technologies)
    for project in profile.projects:
        terms.update(t.casefold() for t in project.technologies)
    return terms


def ungrounded_claims(text: str, profile, job=None) -> list[str]:
    """Reasons `text` asserts something the evidence does not support (empty list = grounded)."""
    problems: list[str] = []
    if UNSUPPORTED_PERSONAL_CLAIMS.search(text):
        problems.append("unsupported personal-affinity claim")
    total = float(facts.whole_years(facts.experience_years(profile) or 0.0))   # years round up, so claims may too
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", text, re.IGNORECASE):
        if float(match.group(1)) > total + 0.05:
            problems.append(f"claims {match.group(1)} years but dates support at most {total:.0f}")
    level = facts.highest_education(profile)
    if re.search(r"\bph\.?d\b|doctorate", text, re.IGNORECASE) and level != "Doctorate":
        problems.append("claims a doctorate")
    holds_mba = any(re.search(r"\bmba\b|business administration", f"{e.degree} {e.field_of_study}", re.IGNORECASE)
                    for e in facts.completed_education(profile))
    if re.search(r"\bmba\b", text, re.IGNORECASE) and not holds_mba:
        problems.append("claims an MBA")
    allowed = candidate_evidence(profile)
    job_text = ((getattr(job, "description", "") or "") + " " + (getattr(job, "title", "") or "")).casefold()
    lowered = text.casefold()
    for tech in sorted(TECH_VOCAB):
        word = r"(?<![a-z0-9+#])" + re.escape(tech) + r"(?![a-z0-9+#])"
        if re.search(word, lowered):
            supported = tech in allowed or any(tech in a.split() for a in allowed) or re.search(word, job_text)
            if not supported:
                problems.append(f"names {tech} without candidate evidence")
    known = [e.company for e in profile.experience] + [getattr(job, "company", "") or ""]
    known += [i.institution for i in profile.education]
    for match in re.finditer(r"\b(?:worked|working|employed|interned|role|position|experience)\s+(?:at|with|for)\s+"
                             r"([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})", text):
        name = facts.normalize_company(match.group(1))
        if name and not any(name.startswith(facts.normalize_company(k)) or facts.normalize_company(k).startswith(name)
                            for k in known if k):
            problems.append(f"names an employer not in the profile: {match.group(1)}")
    return problems
