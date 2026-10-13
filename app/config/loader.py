from pathlib import Path

import yaml

from app.config.models import Profile, Preferences

def load_yaml(file_path: str) -> dict:
    path = Path(file_path)

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data


def load_profile() -> Profile:
    raw_profile = load_yaml("data/profile.yaml")

    profile = Profile.model_validate(raw_profile)

    return profile

def load_preferences() -> Preferences:
    raw_preferences = load_yaml("data/preferences.yaml")

    preferences = Preferences.model_validate(raw_preferences)

    return preferences


def load_default_test_job_url() -> str:
    path = Path(__file__).resolve().parents[2] / "data" / "test_jobs.yaml"
    config = load_yaml(str(path))
    if not isinstance(config, dict):
        raise ValueError("data/test_jobs.yaml must contain default_job and jobs.")
    default_job = config.get("default_job")
    jobs = config.get("jobs")
    if not isinstance(default_job, str) or not isinstance(jobs, dict):
        raise ValueError("data/test_jobs.yaml must contain default_job and jobs.")
    job = jobs.get(default_job)
    url = job.get("url") if isinstance(job, dict) else None
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"Default test job {default_job!r} has no URL in data/test_jobs.yaml.")
    return url.strip()
