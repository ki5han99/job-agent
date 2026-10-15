import unittest


from app.config.loader import load_answers
from app.jobs import profile_facts as facts
from app.jobs.grounding import ungrounded_claims
from app.jobs.intent_llm import classify_with_llm
from tests.support import make_profile


class ReviewFixTests(unittest.TestCase):
    def test_malformed_answers_yaml_is_rejected_not_ignored(self):
        import tempfile, pathlib
        for content in ("false", "[]", "0"):
            with tempfile.TemporaryDirectory() as d:
                path = pathlib.Path(d) / "answers.yaml"
                path.write_text(content)
                with self.assertRaises(Exception):
                    load_answers(path)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "answers.yaml"
            path.write_text("")
            self.assertEqual(load_answers(path).consent.approved_categories, [])

    def test_mba_claim_allowed_only_with_an_mba_on_record(self):
        profile = make_profile()
        self.assertTrue(any("MBA" in p for p in ungrounded_claims("I earned my MBA.", profile)))
        profile.education[0].degree = "MBA"
        self.assertFalse(any("MBA" in p for p in ungrounded_claims("I earned my MBA.", profile)))

    def test_compound_experience_requirements_are_not_resolved_from_one_term(self):
        profile = make_profile()
        for domain in ("Python and Java", "data engineering and analytics", "Python/Java"):
            self.assertIsNone(facts.domain_years(profile, domain), domain)

    def test_compound_domain_and_technology_require_evidence_for_both(self):
        profile = make_profile()
        self.assertAlmostEqual(
            facts.domain_years(profile, "ETL and Python"),
            facts.domain_years(profile, "ETL"),
        )
        for job in profile.experience:
            job.technologies = [technology for technology in job.technologies if technology.casefold() != "python"]
        self.assertIsNone(facts.domain_years(profile, "ETL and Python"))

    def test_etl_job_technology_is_not_counted_as_an_additional_requirement(self):
        profile = make_profile()
        for job in profile.experience:
            job.technologies.append("ETL")
        self.assertAlmostEqual(
            facts.domain_years(profile, "ETL and Python"),
            facts.domain_years(profile, "ETL"),
        )

    def test_llm_classification_must_match_the_full_contract(self):
        def ask(reply):
            return lambda prompt, temperature=0.0: reply
        self.assertIsNone(classify_with_llm("q", ask('{"intent": "SPONSORSHIP", "negated": "false"}')))
        self.assertIsNone(classify_with_llm("q", ask('{"intent": "SPONSORSHIP", "company": []}')))
        ok = classify_with_llm("q", ask('{"intent": "SPONSORSHIP", "negated": false, "company": null}'))
        self.assertEqual(ok["intent"], "SPONSORSHIP")
