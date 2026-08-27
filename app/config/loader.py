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