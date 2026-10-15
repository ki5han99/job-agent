import unittest
from datetime import date
from types import SimpleNamespace

from app.browser.interface import ChoiceRequest
from app.config.loader import load_answers, load_preferences, load_profile
from app.jobs import profile_facts as facts
from tests.support import make_profile
from app.jobs.cover_letter import generate_cover_letter
from app.jobs.grounding import ungrounded_claims
from app.jobs.models import Job
from app.jobs.policy import Context, bool_answer, classify_intent, first_valid, resolve_choice, resolve_text

TODAY = date(2026, 10, 14)


def field(label, field_type="text", role=None):
    return SimpleNamespace(label=label, field_type=field_type, role=role, field_id="q")


class PolicyBase(unittest.TestCase):
    def setUp(self):
        self.profile = make_profile()
        self.ctx = Context(self.profile, load_preferences(), load_answers(), company="Gemini", today=TODAY,
                           ledger={"https://job-boards.greenhouse.io/garnerhealth/jobs/1": "CONFIRMED",
                                   "https://job-boards.greenhouse.io/bitgo/jobs/2": "ATTEMPTING",
                                   "https://job-boards.greenhouse.io/oscar/jobs/3": "NOT_CLICKED"})

    def answer(self, label):
        intent = classify_intent(label, self.ctx)
        return None if intent is None else bool_answer(intent, self.ctx)

    def choice(self, label):
        return resolve_choice(field(label, role="combobox"), self.ctx)

    def text(self, label, **kw):
        return resolve_text(field(label, **kw), self.ctx)


class EmploymentAndEducationTests(PolicyBase):
    def test_prior_employment_from_history(self):
        self.assertIs(self.answer("Have you been employed by Gemini in the past?*"), False)
        self.assertIs(self.answer("Have you ever worked for Figma before, as an employee or a contractor/consultant? *"), False)
        self.assertIs(self.answer("Have you ever worked for Amazon before?"), True)
        self.assertIs(self.answer("Have you worked for Raven Software Solutions?"), True)
        self.assertIs(self.answer("Are you a current or former employee of MPundit Solutions?"), True)

    def test_unnamed_company_means_the_company_applied_to(self):
        self.assertIs(self.answer("Have you ever worked here before?"), False)
        self.ctx.company = "Amazon"
        self.assertIs(self.answer("Have you ever worked here before?"), True)

    def test_skill_questions_are_not_employment_questions(self):
        self.assertIsNone(self.answer("Have you worked with Kubernetes?"))
        self.assertIsNone(classify_intent("Have you worked for a startup before?", self.ctx))

    def test_education_level_from_highest_completed_degree(self):
        self.assertEqual(facts.highest_education(self.profile, TODAY), "Master's")
        self.assertEqual(facts.highest_education(self.profile, date(2023, 6, 1)), "Bachelor's")  # MS not finished yet
        pick = self.choice("What is your highest level of completed education?*").pick
        options = ["High School", "Bachelor's Degree", "Master's Degree", "Doctorate", "Some college"]
        self.assertEqual(pick(options), "Master's Degree")
        self.assertIsNone(pick(["Bachelor's Degree", "Doctorate"]))

    def test_degree_wording_variants(self):
        for degree, level in (("MS", "Master's"), ("M.S.", "Master's"), ("BTech", "Bachelor's"), ("B.S.", "Bachelor's"),
                              ("PhD", "Doctorate"), ("MBA", "Master's")):
            self.assertEqual(facts.degree_level(degree), level)


class ExperienceTests(PolicyBase):
    def test_total_years_exclude_gaps_and_always_round_up(self):
        years = facts.experience_years(self.profile, TODAY)
        # 2020-11..2021-11 (13) + 2024-01..2024-11 (11) + 2024-12..2026-10 (23) months
        self.assertAlmostEqual(years, 47 / 12, places=3)
        self.assertEqual(self.text("Years of Work Experience"), "4")      # 3.92 rounds up, never down
        self.assertEqual(facts.whole_years(3.0), 3)
        self.assertEqual(facts.whole_years(0.01), 1)
        self.assertEqual(facts.whole_years(11 / 12), 1)

    def test_overlapping_jobs_are_not_double_counted(self):
        job = lambda s, e: SimpleNamespace(start_date=s, end_date=e, technologies=["SQL"])
        profile = SimpleNamespace(experience=[job("2020-01", "2020-12"), job("2020-07", "2021-06")])
        self.assertAlmostEqual(facts.experience_years(profile, TODAY), 1.5)

    def test_skill_years_use_employment_evidence_only(self):
        self.assertAlmostEqual(facts.experience_years(self.profile, TODAY, "dbt"), 11 / 12, places=3)
        self.assertIsNone(facts.experience_years(self.profile, TODAY, "Snowflake"))
        self.assertIsNone(self.text("How many years of experience do you have with Snowflake?"))
        self.assertEqual(self.text("How many years of experience do you have with Python?"), "4")
        self.assertEqual(self.text("How many years of experience do you have with dbt?"), "1")

    def test_threshold_questions_are_yes_no_not_numeric_entries(self):
        intent = classify_intent("Do you have 3+ years of experience?", self.ctx)
        self.assertEqual((intent.name, intent.number), ("THRESHOLD_YEARS", 3.0))
        self.assertIsNone(self.text("Do you have 3+ years of experience?"))

    def test_range_options(self):
        years = facts.experience_years(self.profile, TODAY)
        self.assertEqual(facts.pick_year_range(["0-1 years", "1-3 years", "3-5 years", "5+ years"], years), "3-5 years")
        self.assertEqual(facts.pick_year_range(["Less than 1", "1 to 2", "3 to 4", "5 or more"], years), "3 to 4")
        self.assertIsNone(facts.pick_year_range(["Entry", "Senior"], years))
        pick = self.choice("Years of Work Experience").pick
        self.assertEqual(pick(["0-2", "3-5", "6+"]), "3-5")


class AuthorizationAndPreferenceTests(PolicyBase):
    def test_work_authorization_yes_and_sponsorship_no(self):
        self.assertIs(self.answer("Are you legally authorized to work in the United States?*"), True)
        self.assertIs(self.answer("Will you now or in the future require sponsorship for employment visa status (e.g. H-1B visa status)?*"), False)
        self.assertIs(self.answer("Will you now or at any point in the future require visa sponsorship to work in the United States?*"), False)
        yes = self.choice("Are you legally authorized to work in the United States?").pick
        no = self.choice("Will you now or in the future require sponsorship?").pick
        self.assertEqual(yes(["Yes", "No"]), "Yes")
        self.assertEqual(no(["Yes", "No"]), "No")
        self.assertEqual(yes(["Yes, I am authorized", "No, I am not"]), "Yes, I am authorized")   # unique 'Yes, ...'
        self.assertIsNone(yes(["Yes, authorized", "Yes, with conditions", "No"]))                  # ambiguous -> review
        self.assertIsNone(no(["Yes", "Maybe"]))

    def test_authorization_and_sponsorship_stay_independent(self):
        self.profile.work_authorization.authorized_to_work_us = None
        self.assertIsNone(self.answer("Are you legally authorized to work in the United States?"))
        self.assertIs(self.answer("Will you now or in the future require sponsorship?"), False)

    def test_relocation_yes_for_any_location(self):
        for label in ("Are you willing to relocate?", "Are you located in or willing to relocate to the United States?*",
                      "Are you willing to relocate to New York?", "Would you be open to relocating to Palo Alto?"):
            with self.subTest(label=label):
                self.assertIs(self.answer(label), True)

    def test_relocation_assistance_is_a_different_question(self):
        self.assertIsNone(self.answer("Do you require relocation assistance?"))

    def test_onsite_and_hybrid_yes(self):
        for label in ("This role is onsite (Monday - Friday) in our NY, NY office. Are you willing to work onsite from NYC full time?*",
                      "Are you willing to work in the office 3 days a week?", "Are you comfortable with a hybrid schedule?"):
            with self.subTest(label=label):
                self.assertIs(self.answer(label), True)

    def test_relocation_plus_onsite_needs_both_preferences(self):
        label = "Are you currently based in or planning to relocate to the NYC area and willing to work in our NYC office 3 days a week?"
        self.assertIs(self.answer(label), True)
        self.ctx.preferences.onsite.willing = None
        self.assertIsNone(self.answer(label))

    def test_nothing_is_answered_without_the_approved_preference(self):
        self.ctx.preferences.relocation.willing_anywhere = None
        self.ctx.preferences.onsite.willing = None
        self.assertIsNone(self.answer("Are you willing to relocate?"))
        self.assertIsNone(self.answer("Are you willing to work onsite full time?"))

    def test_product_familiarity_defaults_to_yes_without_invented_detail(self):
        self.assertIs(self.answer("We're always curious - have you used Tailscale before?*"), True)
        self.assertIs(self.answer("Are you familiar with Datadog?"), True)
        self.assertIsNone(self.answer("How many years have you used Tailscale?"))
        self.assertIsNone(self.answer("Have you used ChatGPT to write your answers?"))
        self.ctx.answers.product_familiarity_default = None
        self.assertIsNone(self.answer("Have you used Tailscale before?"))


class LedgerAndDefaultsTests(PolicyBase):
    def test_prior_application_uses_the_ledger(self):
        self.assertIs(self.answer("Have you previously applied to work at Garner Health?"), True)
        self.assertIs(self.answer("Have you previously applied to work at Point72?"), False)
        self.assertIs(self.answer("Have you previously applied to work at Oscar?"), False)   # never actually submitted
        self.assertIsNone(self.answer("Have you previously applied to work at BitGo?"))      # ambiguous -> REVIEW

    def test_preferred_location_option_or_fallback_text(self):
        self.assertEqual(first_valid(["Select...", "", "Remote - US", "Seattle"]), "Remote - US")
        self.assertIsNotNone(self.choice("From where do you intend to work?").pick)
        self.assertEqual(self.text("What is your preferred work location?"), "Philadelphia, PA")

    def test_referral_prefers_company_website_equivalents(self):
        pick = self.choice("How did you learn about this position").pick
        self.assertEqual(pick(["LinkedIn", "Employee Referral", "Company Website", "Other"]), "Company Website")
        self.assertEqual(pick(["Indeed", "Careers Page"]), "Careers Page")
        self.assertIsNone(pick(["LinkedIn", "Employee Referral", "Indeed"]))
        self.assertEqual(self.text("How did you hear about this job?"), "Company website")

    def test_languages(self):
        self.assertEqual(self.text("In which language(s) are you fluent (written) other than English?*"), "Telugu")
        self.assertEqual(self.text("Which languages do you speak?"), "English, Telugu")

    def test_military_and_veteran_are_no_not_decline(self):
        self.assertIs(self.answer("Have you served in the military?*"), False)
        self.assertEqual(self.choice("Have you served in the military?").pick(["Yes", "No"]), "No")
        pick = self.choice("Veteran Status*").pick
        self.assertEqual(pick(["I am not a protected veteran", "I identify as one or more of the classifications of protected veteran",
                               "I don't wish to answer"]), "I am not a protected veteran")
        self.assertEqual(pick(["Yes", "No", "Decline to answer"]), "No")
        self.assertIsNone(pick(["I don't wish to answer"]))   # never decline when a fact exists

    def test_salary_is_120000_in_the_right_shape(self):
        self.assertEqual(self.text("What is your desired salary?"), "$120,000")
        self.assertEqual(self.text("Desired salary", field_type="number"), "120000")
        self.assertEqual(self.text("Expected salary (numbers only)"), "120000")

    def test_other_compensation_concepts_are_not_converted(self):
        for label in ("What is your hourly rate?", "What is your current salary?", "Total compensation expectations",
                      "Minimum acceptable salary", "Expected equity"):
            with self.subTest(label=label):
                self.assertIsNone(self.text(label))

    def test_salary_is_never_a_hard_filter(self):
        import inspect

        import app.jobs.filters as filters
        import app.jobs.scorer as scorer
        self.assertNotIn("salary", " ".join(Job.model_fields))
        self.assertNotIn("salary", inspect.getsource(filters).lower())
        self.assertNotIn("salary", inspect.getsource(scorer).lower())

    def test_address_fields_come_from_the_profile_only(self):
        self.assertEqual(self.text("City"), "Seattle")
        self.assertEqual(self.text("State/Province"), "WA")
        self.assertEqual(self.text("Country"), "United States")
        # Whatever the profile holds is used verbatim; blank means unknown and is never invented.
        self.profile.address.line1, self.profile.address.postal_code = "", ""
        self.assertIsNone(self.text("Address Line 1"))
        self.assertIsNone(self.text("Postal/Zip Code"))
        self.profile.address.line1, self.profile.address.postal_code = "1 Main St", "00000"
        self.assertEqual(self.text("Address Line 1"), "1 Main St")
        self.assertEqual(self.text("Postal/Zip Code"), "00000")


class DropdownConsentAndLanguageTests(PolicyBase):
    def test_consent_presented_as_a_dropdown_picks_the_unique_affirmative_option(self):
        label = 'I have read and understand the Candidate Privacy Policy and AI Guidelines regarding my personal information.'
        pick = self.choice(label).pick
        self.assertEqual(pick(["I acknowledge", "I do not acknowledge"]), "I acknowledge")
        self.assertEqual(pick(["Yes", "No"]), "Yes")
        self.assertIsNone(pick(["Yes", "Yes, with conditions"]))
        self.assertIsNone(pick(["No", "Decline"]))
        self.assertEqual(self.choice("Privacy *").pick(["I agree", "I disagree"]), "I agree")

    def test_unapproved_consent_dropdown_is_left_alone(self):
        self.assertIsNone(self.choice("I agree to receive marketing emails"))
        self.ctx.answers.consent.approved_categories = []
        self.assertIsNone(self.choice("Privacy *"))

    def test_single_language_dropdown(self):
        pick = self.choice("In which language(s) are you fluent (written) other than English?*").pick
        self.assertEqual(pick(["French", "Telugu", "Hindi"]), "Telugu")
        self.assertIsNone(pick(["French", "Hindi"]))     # never substitute another language
        self.assertIsNone(self.choice("Which languages are you fluent in?"))   # English + Telugu: needs multi-select


class ProductUsageDetailTests(PolicyBase):
    TAILSCALE = ["Yes, on my personal devices.", "Yes, at work.", "Yes, both personally and at work.",
                 "I haven\u2019t used it, but I\u2019m excited to learn more."]

    def pick(self):
        return self.choice("We're always curious - have you used Tailscale before?*").pick

    def test_takes_the_approved_personal_option_when_only_detailed_yes_options_exist(self):
        self.assertEqual(self.pick()(self.TAILSCALE), "Yes, on my personal devices.")

    def test_plain_yes_wins_and_other_shapes_stay_review(self):
        self.assertEqual(self.pick()(["Yes", "No"]), "Yes")
        self.assertIsNone(self.pick()(["Yes, at work.", "Yes, both personally and at work.", "No"]))
        self.assertIsNone(self.pick()(["Yes, personally on my phone", "Yes, personally on my laptop", "No"]))   # ambiguous
        self.assertIsNone(self.pick()(["I haven\u2019t used it"]))                                                 # never picks 'no use'

    def test_without_the_approved_detail_detailed_options_stay_review(self):
        self.ctx.answers.product_usage_detail = None
        self.assertIsNone(self.pick()(self.TAILSCALE))
        self.assertEqual(self.pick()(["Yes", "No"]), "Yes")


class EeoTests(PolicyBase):
    def test_eeo_uses_decline_labels_only(self):
        for label in ("Gender*", "Disability Status", "Sexual Orientation", "Are you transgender?"):
            with self.subTest(label=label):
                request = self.choice(label)
                self.assertIn("decline to self identify", request.labels)
                self.assertTrue(request.no_search)

    def test_race_ethnicity_picks_asian_equivalents(self):
        for label in ("Race/Ethnicity", "Ethnicity/Race", "What is your race?", "Please select your ethnicity"):
            with self.subTest(label=label):
                request = self.choice(label)
                self.assertIsNotNone(request.pick)
                self.assertNotIn("decline", " ".join(request.labels).lower())
        pick = self.choice("Race/Ethnicity").pick
        self.assertEqual(pick(["White", "Asian", "Black or African American", "Decline to self identify"]), "Asian")
        self.assertEqual(pick(["Asian (Not Hispanic or Latino)", "White (Not Hispanic or Latino)",
                               "Hispanic or Latino", "I don't wish to answer"]), "Asian (Not Hispanic or Latino)")
        self.assertEqual(pick(["Asian or Asian American", "White", "Prefer not to say"]), "Asian or Asian American")
        self.assertEqual(pick(["Asian", "Asian American"]), "Asian")         # exact beats near-match
        self.assertEqual(pick(["Asian or Pacific Islander", "White"]), "Asian or Pacific Islander")

    def test_south_asian_is_an_approved_equivalent(self):
        pick = self.choice("Please select up to 2 ethnicities that you most closely identify with.*").pick
        reddit = ["American Indian or Alaska Native", "Black or African American", "East Asian", "South Asian", "Hispanic or Latinx",
                  "Middle Eastern or North African", "Native Hawaiian or Other Pacific Islander", "White", "I don't wish to answer"]
        self.assertEqual(pick(reddit), "South Asian")                    # one option only, never East Asian
        self.assertEqual(pick(["South Asian", "Asian", "White"]), "Asian")        # the plain category wins
        self.assertEqual(pick(["South Asian (Not Hispanic or Latino)", "White"]), "South Asian (Not Hispanic or Latino)")
        self.assertIsNone(pick(["East Asian", "Southeast Asian", "I don't wish to answer"]))
        self.assertIsNone(pick(["South Asian", "South Asian"]))          # duplicates are ambiguous
        self.profile.demographics.race_ethnicity_also = []               # without the approved equivalent: review again
        self.assertIsNone(self.choice("Race/Ethnicity").pick(reddit))

    def test_race_never_guesses_when_categories_do_not_map(self):
        pick = self.choice("Race/Ethnicity").pick
        self.assertIsNone(pick(["East Asian", "Southeast Asian", "White", "Decline to answer"]))   # other regions: not guessed
        self.assertIsNone(pick(["Two or more races", "White", "Black", "Decline to answer"]))
        self.assertIsNone(pick(["Decline to answer"]))        # an explicit fact exists: never fall back to decline
        self.assertIsNone(pick([]))
        self.assertIsNone(pick(["Asian (Japanese)", "Asian (Indian)"]))        # ambiguous sub-options

    def test_without_an_approved_race_fact_race_falls_back_to_decline(self):
        self.profile.demographics.race_ethnicity = None
        request = self.choice("Race/Ethnicity")
        self.assertIn("decline to self identify", request.labels)
        self.assertEqual(request.pick(["White", "Asian", "Decline to self identify"]), "Decline to self identify")
        self.assertIsNone(request.pick(["White", "Asian"]))      # never invents an answer

    def test_hispanic_question_is_not_a_race_question(self):
        self.assertEqual(classify_intent("Are you Hispanic/Latino?", self.ctx).name, "HISPANIC")
        self.assertEqual(classify_intent("Are you Hispanic/Latinx?", self.ctx).name, "HISPANIC")
        self.assertEqual(classify_intent("Ethnicity/Race", self.ctx).name, "RACE")

    def test_not_hispanic_latino_is_answered_no_not_declined(self):
        for label in ("Are you Hispanic/Latino?*", "Are you Hispanic/Latinx?", "Hispanic or Latino"):
            with self.subTest(label=label):
                pick = self.choice(label).pick
                self.assertEqual(pick(["Yes", "No", "I don't wish to answer"]), "No")
                self.assertEqual(pick(["Hispanic or Latino", "Not Hispanic or Latino", "Decline to self identify"]),
                                 "Not Hispanic or Latino")
                self.assertEqual(pick(["Yes", "No, I am not Hispanic or Latino", "Prefer not to say"]),
                                 "No, I am not Hispanic or Latino")
                self.assertIsNone(pick(["Yes", "Decline to answer"]))       # never falls back to decline
                self.assertIsNone(pick(["Hispanic", "Latino"]))

    def test_hispanic_without_a_fact_still_declines_and_true_answers_yes(self):
        self.profile.demographics.hispanic_latino = None
        self.assertIn("prefer not to say", self.choice("Are you Hispanic/Latino?").labels)
        self.profile.demographics.hispanic_latino = True
        pick = self.choice("Are you Hispanic/Latino?").pick
        self.assertEqual(pick(["Yes", "No"]), "Yes")
        self.assertEqual(pick(["Hispanic or Latino", "Not Hispanic or Latino"]), "Hispanic or Latino")

    def test_other_eeo_fields_and_veteran_unchanged(self):
        for label in ("Gender identity", "Sexual Orientation", "Are you transgender?", "Disability Status"):
            self.assertIn("decline to answer", self.choice(label).labels, label)
        self.assertEqual(self.choice("Veteran Status").pick(["I am not a protected veteran", "I don't wish to answer"]),
                         "I am not a protected veteran")

    def test_eeo_default_must_be_approved(self):
        self.ctx.answers.eeo_default = None
        self.assertIsNone(self.choice("Gender"))


class SemanticIntentTests(PolicyBase):
    def test_equivalent_wording_resolves_the_same_intent(self):
        for label in ("What is the highest level of education you have completed?", "Highest degree earned", "Education level"):
            self.assertEqual(classify_intent(label, self.ctx).name, "EDUCATION")
        for label in ("How did you hear about us?", "Where did you hear about this opening?", "How did you find this role?"):
            self.assertEqual(classify_intent(label, self.ctx).name, "REFERRAL_SOURCE")

    def test_llm_names_the_intent_but_code_supplies_the_answer(self):
        self.ctx.llm_classify = lambda label: {"intent": "RELOCATION", "negated": False}
        self.assertIs(self.answer("Would moving to another city for this position be a problem for you at all?"), True)

    def test_llm_cannot_invent_intents_or_flip_polarity(self):
        for reply in ({"intent": "PAYS_BILLS"}, {"intent": "SPONSORSHIP", "negated": True},
                      {"intent": "US_AUTHORIZATION", "country": "Canada"}, "garbage", None):
            with self.subTest(reply=reply):
                self.ctx.cache.clear()
                self.ctx.llm_classify = lambda label, r=reply: r
                self.assertIsNone(classify_intent("Is there anything about the visa situation we should know about?", self.ctx))

    def test_llm_failure_is_review_not_a_crash(self):
        def boom(label):
            raise RuntimeError("ollama down")
        self.ctx.llm_classify = boom
        self.assertIsNone(classify_intent("Is there anything about the visa situation we should know about?", self.ctx))

    def test_short_labels_never_reach_the_llm(self):
        self.ctx.llm_classify = lambda label: (_ for _ in ()).throw(AssertionError("LLM must not be called"))
        self.assertIsNone(classify_intent("First Name", self.ctx))


class GroundingAndCoverLetterTests(PolicyBase):
    def setUp(self):
        super().setUp()
        self.job = SimpleNamespace(title="Data Engineer", company="Gemini", description="Build pipelines with Python and Airflow.")

    GOOD = ("Dear Hiring Team, I am applying for the Data Engineer role at Gemini. At Amazon I build and operate AWS data "
            "pipelines in Python and Airflow, and at Raven Software Solutions I built Azure pipelines with dbt and SQL. "
            "My MS in Computer Science from the University of Texas at Dallas and nearly four years of data engineering "
            "work prepare me to contribute quickly to your platform. I would welcome the chance to discuss how my experience "
            "building reliable, well-tested data systems can support your team. Thank you for your time and consideration. "
            "Sincerely, Sai Edimadakala")

    def test_grounded_text_passes(self):
        self.assertEqual(ungrounded_claims(self.GOOD, self.profile, self.job), [])

    def test_years_claims_follow_the_round_up_rule(self):
        self.assertEqual(ungrounded_claims("I have 4 years of data engineering experience.", self.profile, self.job), [])
        self.assertTrue(ungrounded_claims("I have 5 years of data engineering experience.", self.profile, self.job))

    def test_invented_facts_are_caught(self):
        cases = {
            "I have 9 years of data engineering experience.": "years",
            "I hold a PhD in computer science.": "doctorate",
            "I built our Dagster orchestration layer.": "dagster",
            "I worked at Google on search ranking.": "Google",
            "I am a huge fan of Tailscale and have used it for years.": "personal-affinity",
        }
        for text, needle in cases.items():
            with self.subTest(text=text):
                self.assertTrue(any(needle.lower() in p.lower() for p in ungrounded_claims(text, self.profile, self.job)), text)

    def test_cover_letter_generated_only_when_grounded(self):
        self.assertEqual(generate_cover_letter(self.profile, self.job, ask=lambda prompt, t=0.3: self.GOOD), self.GOOD)
        invented = self.GOOD.replace("dbt and SQL", "Dagster and SQL")
        self.assertIsNone(generate_cover_letter(self.profile, self.job, ask=lambda prompt, t=0.3: invented))
        self.assertIsNone(generate_cover_letter(self.profile, self.job, ask=lambda prompt, t=0.3: "Too short."))
        self.assertIsNone(generate_cover_letter(self.profile, self.job, ask=lambda prompt, t=0.3: self.GOOD + " [Your Address]"))

    def test_cover_letter_prompt_carries_only_profile_evidence(self):
        seen = []
        generate_cover_letter(self.profile, self.job, ask=lambda prompt, t=0.3: seen.append(prompt) or self.GOOD)
        self.assertIn("Amazon", seen[0])
        self.assertIn("Do not invent", seen[0])
        self.assertNotIn("sainandakishan@gmail.com", seen[0])   # contact details are not needed
