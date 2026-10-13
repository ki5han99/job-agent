from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from app.config.models import (
    Preferences,
    Profile,
    TestJobsConfig,
)


ConfigT = TypeVar("ConfigT", bound=BaseModel)


def load_yaml(
    file_path: str | Path,
    model: type[ConfigT],
) -> ConfigT:
    path = Path(file_path)

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return model.model_validate(data)


def load_profile() -> Profile:
    return load_yaml("data/profile.yaml", Profile)


def load_preferences() -> Preferences:
    return load_yaml("data/preferences.yaml", Preferences)


def load_default_test_job_url() -> str:
    path = Path(__file__).resolve().parents[2] / "data" / "test_jobs.yaml"
    config = load_yaml(path, TestJobsConfig)
    job = config.jobs.get(config.default_job)
    if job is None or not job.url.strip():
        raise ValueError(
            f"Default test job {config.default_job!r} has no URL in data/test_jobs.yaml."
        )
    return job.url.strip()


def load_test_job_urls() -> list[str]:
    path = Path(__file__).resolve().parents[2] / "data" / "test_jobs.yaml"
    config = load_yaml(path, TestJobsConfig)
    return [job.url.strip() for job in config.jobs.values() if job.url.strip()]
