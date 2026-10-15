"""Test-only personal facts, so the suite does not depend on private values in data/profile.yaml."""
from app.config.loader import load_profile


def make_profile():
    profile = load_profile()
    profile.demographics.race_ethnicity = "Asian"
    profile.demographics.race_ethnicity_also = ["South Asian"]
    profile.demographics.hispanic_latino = False
    profile.military.served = False
    profile.military.is_veteran = False
    profile.address.line1 = "1 Test St"
    profile.address.postal_code = "00000"
    return profile
