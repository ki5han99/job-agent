import unittest
from datetime import date

from app.browser.interface import ChoiceRequest
from app.jobs import profile_facts as facts
from app.jobs.consent import classify_consent
from app.jobs.policy import (bool_answer, classify_intent, pick_authorized, pick_contains, pick_country_us,
                             pick_decline_semantic, pick_never_worked, us_location)
from test_policy import PolicyBase, TODAY, field


class EducationAndEmploymentFieldTests(PolicyBase):
    def test_school_degree_discipline_come_from_the_highest_completed_record(self):
        self.assertEqual(self.text("School*"), "University of Texas at Dallas")
        self.assertEqual(self.text("Degree"), "MS")
        self.assertEqual(self.text("Discipline"), "Computer Science")
        self.assertEqual(self.text("Field of study"), "Computer Science")

    def test_an_unfinished_degree_is_never_reported(self):
        self.profile.education[0].end_date = "2027-12"      # the MS is not finished yet
        self.assertEqual(self.text("School*"), "SRM University")
        self.assertEqual(self.text("Degree"), "BTech")

    def test_dropdown_school_degree_discipline(self):
        school = self.choice("School*")
        self.assertEqual(school.search, "University of Texas at Dallas")
        self.assertFalse(school.no_search)                    # a typeahead: it may type to search
        pick = school.pick
        self.assertEqual(pick(["University of Texas at Dallas"]), "University of Texas at Dallas")
        self.assertEqual(pick(["The University of Texas at Dallas", "University of Texas at Austin"]),
                         "The University of Texas at Dallas")
        self.assertEqual(pick(["University of Texas at Dallas (UT Dallas)", "University of Texas at Austin"]),
                         "University of Texas at Dallas (UT Dallas)")
        self.assertEqual(pick(["Dallas Baptist University", "Dallas Christian College", "University of Dallas",
                               "University of Texas - Dallas"]), "University of Texas - Dallas")   # AppLovin's real listing
        self.assertIsNone(pick(["Dallas Baptist University", "University of Dallas"]))                # never a lookalike
        self.assertIsNone(pick(["University of Texas at Austin", "University of Texas at Arlington"]))
        self.assertIsNone(pick(["University of Texas at Dallas - Online", "University of Texas at Dallas (UTD)"]))   # ambiguous
        self.assertIsNone(pick([]))
        degrees = ["Associate's Degree", "Bachelor's Degree", "Master's Degree", "Master of Business Administration (M.B.A.)",
                   "Doctor of Philosophy (Ph.D.)", "Juris Doctor (J.D.)", "Engineer's Degree", "Some College"]
        self.assertEqual(self.choice("Degree*").pick(degrees), "Master's Degree")
        self.assertIsNone(self.choice("Degree*").pick(["Master of Business Administration (M.B.A.)", "Master of Fine Arts"]))   # ambiguous
        pick = self.choice("Discipline").pick
        self.assertEqual(pick(["Biology", "Computer Science", "Computer Engineering"]), "Computer Science")
        self.assertEqual(pick(["Computer Science & Engineering", "Biology"]), "Computer Science & Engineering")
        self.assertIsNone(pick(["Computer Science and AI", "Computer Science & Engineering"]))     # ambiguous

    def test_education_level_still_maps_semantically(self):
        pick = self.choice("What is your highest level of completed education?*").pick
        self.assertEqual(pick(["High School", "Bachelor's degree", "Master's degree", "Doctorate"]), "Master's degree")

    def test_current_and_most_recent_employer(self):
        self.assertEqual(self.text("Current Company"), "Amazon")
        self.assertEqual(self.text("Please provide the name of your current (or most recent) company"), "Amazon")
        self.assertEqual(self.text("Current Title"), "Data Engineer")
        self.profile.experience[0].current, self.profile.experience[0].end_date = False, "2025-03"
        self.assertEqual(facts.most_recent_job(self.profile, TODAY).company, "Amazon")      # latest end date wins
        self.profile.experience[0].start_date, self.profile.experience[0].end_date = "2022-01", "2023-01"
        self.assertEqual(facts.most_recent_job(self.profile, TODAY).company, "Raven Software Solutions")

    def test_names(self):
        self.assertEqual(self.text("What is your preferred first name?"), "Kishan")
        self.assertEqual(self.text("Preferred Name"), "Kishan")
        self.assertEqual(self.text("Please provide your full name exactly as it appears on your government-issued identification."),
                         "Sai Nanda Kishan Edimadakala")
        self.assertIsNone(self.text("What is your preferred last name?"))

    def test_robinhood_style_prior_employment_uses_the_whole_record(self):
        label = ("Have you ever worked for Robinhood as an employee, intern or contractor? Note that providing false or "
                 "misleading information may result in disqualification from the hiring process.*")
        self.assertIs(self.answer(label), False)
        self.assertIs(self.answer(label.replace("Robinhood", "Amazon")), True)
        self.assertIs(self.answer("Have you worked at AppLovin or any of its affiliates before?"), False)

    def test_sponsorship_wording_is_never_read_as_employment(self):
        self.assertIsNone(classify_intent("Do you now or in the future require sponsorship to work at Google?", self.ctx))

    def test_relationships_and_outside_activities_are_not_inferred(self):
        for label in ("Do you have any Personal/Familial Relationships with current employees or vendors?",
                      "Do you have any Outside Business Activities that you wish to continue?"):
            self.assertIsNone(classify_intent(label, self.ctx), label)

    def test_employment_history_options(self):
        pick = self.choice("SpaceX & SpaceXAI Employment History*").pick
        self.assertEqual(pick(["I have never worked for SpaceX, SpaceXAI", "I am a former SpaceX, SpaceXAI, xAI, X employee",
                               "I am a current SpaceX employee"]), "I have never worked for SpaceX, SpaceXAI")
        self.assertIsNone(pick(["I am a current SpaceX employee"]))
        self.ctx.company = "Amazon"                                   # worked there: never answer "never"
        self.assertIsNone(self.choice("Amazon Employment History*"))


class ThresholdAndDegreeHeldTests(PolicyBase):
    CLEAR_STREET = ("Do you have at least five (5) years of professional software design and development experience "
                    "including CI/CD, source code control, testing, and quality management? *")
    REDDIT = ("3+ years of experience working with large-scale ETL systems (implementation, strategy, and maintenance), "
              "building clean, maintainable code and systems (Python preferred) in a production environment.*")

    def test_five_years_is_no_when_experience_is_below_five(self):
        intent = classify_intent(self.CLEAR_STREET, self.ctx)
        self.assertEqual((intent.name, intent.number), ("THRESHOLD_YEARS", 5.0))
        self.assertIs(bool_answer(intent, self.ctx), False)
        self.assertEqual(self.choice(self.CLEAR_STREET).pick(["Yes", "No"]), "No")

    def test_thresholds_never_round_up_to_pass(self):
        # 47 months = 3.92 years: "at least 4" is No even though a numeric entry would say 4.
        self.assertEqual(self.text("Years of Work Experience"), "4")
        self.assertIs(self.answer("Do you have at least 4 years of professional experience?"), False)
        self.assertIs(self.answer("Do you have at least 3 years of professional experience?"), True)
        self.assertIs(facts.meets_experience_threshold(self.profile, 4, "", TODAY), False)

    def test_etl_threshold_uses_relevant_employment_evidence(self):
        self.assertIs(self.answer(self.REDDIT), True)
        self.assertAlmostEqual(facts.domain_years(self.profile, "large-scale ETL systems", TODAY), 47 / 12, places=3)
        # only the ETL-relevant jobs count: drop the evidence from two of the three jobs
        for job in self.profile.experience[:2]:
            job.technologies, job.description = ["Excel"], "Reporting."
        self.assertAlmostEqual(facts.domain_years(self.profile, "ETL", TODAY), 13 / 12, places=3)
        self.assertIs(self.answer(self.REDDIT), False)

    def test_unsupported_domains_are_review_unless_total_experience_already_fails(self):
        self.assertIsNone(self.answer("Do you have at least 3 years of experience in stakeholder management?"))
        self.assertIs(self.answer("Do you have at least 5 years of experience in stakeholder management?"), False)
        self.assertIsNone(self.answer("Do you have at least 1 year of experience with Snowflake?"))
        self.assertIs(self.answer("Do you have at least 3 years of experience with Python?"), True)

    def test_number_entry_questions_are_not_thresholds(self):
        self.assertEqual(classify_intent("Years of Work Experience", self.ctx).name, "YEARS_EXPERIENCE")
        self.assertEqual(classify_intent("How many years of experience do you have with Python?", self.ctx).name, "YEARS_EXPERIENCE")

    def test_bachelors_degree_in_cs_or_quant_field(self):
        label = "Do you have a Bachelor's degree in computer science or a quant educational field? *"
        self.assertEqual(classify_intent(label, self.ctx).name, "DEGREE_HELD")
        self.assertIs(self.answer(label), True)
        self.assertEqual(self.choice(label).pick(["Yes", "No"]), "Yes")

    def test_degree_held_edge_cases(self):
        self.assertIs(self.answer("Do you have a Master's degree?"), True)
        self.assertIs(self.answer("Do you have a Master's degree in computer science?"), True)
        self.assertIs(self.answer("Do you have a PhD?"), False)                      # records are complete: no doctorate
        self.assertIsNone(self.answer("Do you have a Bachelor's degree in physics?"))   # field cannot be matched
        self.profile.education[0].end_date = "2027-12"                                # MS not finished
        self.assertIs(self.answer("Do you have a Master's degree?"), False)


class AuthorizationVariantTests(PolicyBase):
    def test_current_authorization_is_independent_from_future_sponsorship(self):
        self.assertIs(self.answer("Are you currently authorized to work in the U.S.?*"), True)
        self.assertIsNone(self.answer("Do you currently require sponsorship?"))
        self.assertIsNone(self.answer("Do you have unrestricted authorization to work in the United States?"))
        self.assertIsNone(self.answer("Are you legally authorized to work in Canada?"))

    def test_sponsorship_wording_variants(self):
        self.ctx.company = "Reddit"
        for label in ("Do you now, or will you in the future, require immigration sponsorship to work at Reddit?*",
                      "Do you now or will you in the future need sponsorship for employment visa status?",
                      "Do you now or in the future require visa sponsorship to work in the United States?"):
            with self.subTest(label=label):
                self.assertIs(self.answer(label), False)
        self.assertIsNone(self.answer("Do you now or in the future require sponsorship to work at Google?"))
        self.assertIsNone(self.answer("Will you now or in the future require sponsorship and relocation?"))

    def test_country_of_the_job_needs_an_explicit_us_job(self):
        auth = "Are you currently authorized to work in the country outlined for this job (e.g. H-1B status)?*"
        sponsor = "Do you now or will you in the future need sponsorship for employment visa status in the country in which you are applying?"
        for location in ("", "Remote", "Toronto, Canada", "Bengaluru, India"):
            self.ctx.job_location = location
            self.ctx.cache.clear()
            self.assertIsNone(self.answer(auth), location)
            self.assertIsNone(self.answer(sponsor), location)
        for location in ("San Francisco, US (Hybrid)", "Remote - United States", "Menlo Park, CA"):
            self.ctx.job_location = location
            self.ctx.cache.clear()
            self.assertIs(self.answer(auth), True, location)
            self.assertIs(self.answer(sponsor), False, location)

    def test_us_location_detection(self):
        for location, expected in (("Remote - United States", True), ("San Francisco, US (Hybrid)", True), ("Menlo Park, CA", True),
                                   ("Remote", False), ("", False), ("Toronto, Canada", False), ("Bengaluru, India", False),
                                   ("Indiana, USA", True), ("London, UK", False)):
            self.assertIs(us_location(location), expected, location)

    def test_authorization_categories_are_never_guessed(self):
        pick = self.choice("Which work authorization best describes you?*").pick
        self.assertEqual(pick(["I am authorized to work in the US without sponsorship", "I require sponsorship", "Other"]),
                         "I am authorized to work in the US without sponsorship")
        self.assertIsNone(pick(["US Citizen", "Green Card holder", "H-1B visa holder", "Need sponsorship"]))   # visa categories
        self.assertIsNone(pick(["I am authorized to work without sponsorship (citizen)",
                                "I am authorized to work without sponsorship (green card)"]))

    def test_spacex_style_authorization_options(self):
        pick = pick_authorized(False, allow_category=False)
        options = ["I am authorized to work in the United States and do not require sponsorship",
                   "I am authorized to work in the United States but will require sponsorship in the future",
                   "I require sponsorship to work in the United States", "I am not authorized to work in the United States"]
        self.assertEqual(pick(options), options[0])
        # two equally-good "authorized" options (e.g. different citizenship classes) -> a person decides
        self.assertIsNone(pick(["I am authorized to work in the US as a citizen", "I am authorized to work in the US as a permanent resident"]))
        self.assertIsNone(pick(["Yes, authorized", "Yes, with conditions", "No"]))            # Yes/No lists are left alone
        pick_auth = self.choice("Are you legally authorized to work in the United States?*").pick
        self.assertEqual(pick_auth(options), options[0])
        self.assertEqual(pick_auth(["Yes", "No"]), "Yes")

    def test_citizenship_is_not_inferred(self):
        self.assertIsNone(self.choice("Citizenship Status*"))
        self.assertIsNone(self.text("Citizenship Status*"))
        for label in ("GPA (Undergraduate)*", "SAT Score*", "ACT Score*", "GRE Score*", "Active Security Clearance(s)*",
                      "Can you perform all of the essential functions of this role with or without reasonable accommodations?*"):
            self.assertIsNone(self.text(label), label)
            self.assertIsNone(self.choice(label), label)


class DropdownTests(PolicyBase):
    def test_country_dropdown(self):
        pick = self.choice("Country*").pick if self.choice("Country*") else None
        self.assertEqual(pick(["Canada", "United States", "United Kingdom"]), "United States")
        self.assertEqual(pick(["USA", "Canada"]), "USA")
        self.assertEqual(pick(["United States of America", "Canada"]), "United States of America")
        self.assertIsNone(pick(["United States Minor Outlying Islands", "Canada"]))
        self.assertIsNone(pick_country_us(["United States", "United States of America"]))      # ambiguous

    def test_the_phone_country_selector_keeps_its_flag_aware_path(self):
        phone = field("Country*", role="combobox")
        phone.field_id = "country"
        from app.jobs.policy import resolve_choice
        self.assertIsNone(resolve_choice(phone, self.ctx))

    def test_country_needs_an_approved_us_profile_country(self):
        self.profile.location.country = "Canada"
        self.assertIsNone(self.choice("Country*"))

    def test_decline_is_chosen_semantically_and_only_when_unambiguous(self):
        self.assertEqual(pick_decline_semantic(["Man", "Woman", "Prefer not to say"]), "Prefer not to say")
        self.assertEqual(pick_decline_semantic(["Yes", "No", "I don’t wish to answer"]), "I don’t wish to answer")
        self.assertEqual(pick_decline_semantic(["A", "Choose not to disclose"]), "Choose not to disclose")
        self.assertIsNone(pick_decline_semantic(["Man", "Woman"]))
        self.assertIsNone(pick_decline_semantic(["Prefer not to say", "Decline to answer"]))     # two: ambiguous

    def test_lgbtq_question_declines_only_if_an_option_exists(self):
        label = "Do you identify yourself as a member of the LGBTQIA+ community?*"
        self.assertEqual(classify_intent(label, self.ctx).name, "EEO")
        pick = self.choice(label).pick
        self.assertEqual(pick(["Yes", "No", "Prefer not to say"]), "Prefer not to say")
        self.assertIsNone(pick(["Yes", "No"]))                       # no decline option -> left unanswered

    def test_minimum_desired_salary_uses_the_approved_figure(self):
        self.assertEqual(self.text("What is the minimum annual salary desired (in USD)?*"), "120000")
        self.assertEqual(self.text("Minimum annual salary desired"), "$120,000")
        self.assertIsNone(self.text("Minimum acceptable salary"))            # a different concept: still review
        self.assertIsNone(self.text("What is your hourly rate?"))

    def test_visa_explanation_is_left_for_review(self):
        label = "If sponsorship is needed, please explain your current visa type and status."
        self.assertIsNone(self.text(label, field_type="textarea"))
        self.assertIsNone(self.choice(label))

    def test_pick_contains_and_never_worked_helpers(self):
        self.assertIsNone(pick_contains("Computer Science")(["Biology"]))
        self.assertIsNone(pick_never_worked(["I am a current employee"]))


class TypeaheadSearchTermTests(PolicyBase):
    def test_school_search_terms_shorten_progressively(self):
        from app.jobs.policy import school_search_terms
        self.assertEqual(school_search_terms("University of Texas at Dallas"),
                         ["University of Texas at Dallas", "Texas Dallas", "Dallas"])
        self.assertEqual(school_search_terms("MIT"), ["MIT"])
        self.assertEqual(school_search_terms("SRM University"), ["SRM University", "SRM"])

    def test_the_school_request_carries_the_fallbacks(self):
        request = self.choice("School*")
        self.assertEqual(request.search, "University of Texas at Dallas")
        self.assertEqual(request.search_fallbacks, ["Texas Dallas", "Dallas"])


class OrderingAndWordingTests(PolicyBase):
    def test_a_routine_consent_dropdown_is_not_reinterpreted_by_the_llm(self):
        label = ('By selecting "I agree," I understand that the information I have provided as part of this job application '
                 "will be processed in accordance with Reddit's Candidate Privacy Policy. *")
        self.ctx.llm_classify = lambda text: {"intent": "US_AUTHORIZATION", "negated": False}      # a wrong LLM guess
        intent = classify_intent(label, self.ctx)
        self.assertEqual(intent.name, "CONSENT")
        self.assertEqual(self.choice(label).pick(["I agree"]), "I agree")
        self.assertIsNone(self.choice(label).pick(["I do not agree"]))

    def test_an_unapproved_consent_is_recognized_and_never_sent_to_the_llm(self):
        label = "I consent to my interview being recorded via BrightHire, Inc. (United States) to assist in our recruiting efforts. *"
        calls = []
        self.ctx.llm_classify = lambda text: calls.append(text) or {"intent": "PRODUCT_FAMILIARITY", "negated": False}
        self.assertEqual(classify_intent(label, self.ctx).name, "UNAPPROVED_CONSENT")
        self.assertIsNone(self.choice(label))
        self.assertIsNone(self.text(label))
        self.assertEqual(calls, [])                          # the LLM was never consulted
        for other in ("I agree to receive marketing emails about future opportunities",
                      "I consent to my data being shared with third parties"):
            self.assertEqual(classify_intent(other, self.ctx).name, "UNAPPROVED_CONSENT", other)

    def test_llm_guesses_must_be_supported_by_the_questions_own_words(self):
        self.ctx.llm_classify = lambda text: {"intent": "US_AUTHORIZATION", "negated": False}
        self.assertIsNone(classify_intent("Please tell us something about your approach to documentation work", self.ctx))
        for label in ("Is your right to work in the United States unrestricted for all employers?",
                      "Are you authorized to work in the United States for any employer?",
                      "Are you a permanent resident or citizen with authorization to work in the US?"):
            self.ctx.cache.clear()
            self.assertIsNone(classify_intent(label, self.ctx), label)       # unrestricted/category wording is never mapped
        self.ctx.cache.clear()
        self.assertEqual(classify_intent("Do you have the right to work in the United States at this time?", self.ctx).name,
                         "US_AUTHORIZATION")        # plain current-authorization wording is accepted

    def test_veteran_options_with_no_military_service_wording(self):
        pick = self.choice("Are you a veteran/have you served in the military? *").pick
        options = ["Active Reserve", "Inactive Reserve", "Other Protected Veteran", "Retired", "Unspecified Veteran",
                   "Vietnam Era Veteran", "Vietnam Veteran and Other Protected Veteran", "No military service", "I don't wish to answer"]
        self.assertEqual(pick(options), "No military service")
        self.assertIsNone(pick(["Retired", "Unspecified Veteran", "I don't wish to answer"]))

    def test_ethnicity_lists_accept_south_asian_but_never_other_regions(self):
        pick = self.choice("Please select up to 2 ethnicities that you most closely identify with.*").pick
        self.assertEqual(pick(["American Indian or Alaska Native", "Black or African American", "East Asian", "South Asian",
                               "Hispanic or Latinx", "Middle Eastern or North African", "White", "I don't wish to answer"]),
                         "South Asian")
        self.assertIsNone(pick(["East Asian", "Southeast Asian", "White", "I don't wish to answer"]))

    def test_unrestricted_authorization_option_is_not_inferred(self):
        # "for any employer" asserts unrestricted authorization: not an approved fact -> a person decides.
        pick = self.choice("Are you legally authorized to work in the United States?*").pick
        self.assertIsNone(pick(["I am authorized to work in the United States for any employer",
                                "I am authorized to work in the United States for my present employer only",
                                "I require sponsorship to work in the United States",
                                "I am not authorized to work in the United States"]))


class ConsentTriageTests(unittest.TestCase):
    from app.config.loader import load_answers as _answers
    APPROVED = set(_answers().consent.approved_categories)

    def test_routine_data_processing_consents_are_approved(self):
        for label in (
            "By checking this box, I consent to Mixpanel collecting, storing, and processing my responses to the demographic data surveys above.*",
            "By checking this box, I consent to Reddit collecting, storing, and processing my personal information for the purposes of my application.",
            "By selecting \"I agree,\" I understand that the information I have provided as part of this job application will be "
            "processed in accordance with Reddit's Candidate Privacy Policy. *",
        ):
            with self.subTest(label=label[:70]):
                decision = classify_consent(label, self.APPROVED)
                self.assertTrue(decision.eligible, decision.reason)

    def test_interview_recording_is_a_separate_unapproved_category(self):
        label = "I consent to my interview being recorded via BrightHire, Inc. (United States) to assist in our recruiting efforts. *"
        decision = classify_consent(label, self.APPROVED)
        self.assertFalse(decision.eligible)
        self.assertIn("RECORDING_CONSENT", decision.categories)
        self.assertIn("RECORDING_CONSENT", decision.reason)
        self.assertTrue(classify_consent(label, self.APPROVED | {"RECORDING_CONSENT"}).eligible)   # only with explicit approval

    def test_marketing_and_text_message_opt_ins_stay_separate_and_unticked(self):
        for label in (
            "Opt In to receive text message updates about your application. By Opting In, you will only receive general "
            "updates about your application and interview reminders. *",
            "I would like to receive marketing emails about future opportunities",
        ):
            with self.subTest(label=label[:60]):
                self.assertFalse(classify_consent(label, self.APPROVED | {"RECORDING_CONSENT"}).eligible)

    def test_a_non_compete_question_is_not_a_consent(self):
        label = ("Are you currently subject to any agreement with a former employer/third party (such as a non-solicitation or "
                 "non-compete agreement) that may potentially limit your ability to perform the duties of the position?*")
        self.assertIsNone(classify_intent(label))
        self.assertFalse(classify_consent(label, self.APPROVED).eligible)


class ChoiceRequestAcceptanceTests(unittest.TestCase):
    def test_pick_requests_resolve_at_selection_time(self):
        request = ChoiceRequest(search="x", labels=[], pick=lambda labels: labels[0] if labels else None, no_search=True)
        self.assertIsNone(request.chosen)
        self.assertEqual(request.pick(["A", "B"]), "A")


if __name__ == "__main__":
    unittest.main()
