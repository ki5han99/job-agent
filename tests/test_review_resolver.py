import unittest
from types import SimpleNamespace

from app.config.models import ApprovedAnswers, WorkAuthorization
from app.jobs.form_parser import FormField
from app.jobs.review_field_resolver import resolve_review_field
from app.jobs.browserskill_greenhouse import approved_choice


class ReviewResolverTests(unittest.TestCase):
    def setUp(self):
        self.auth = WorkAuthorization(authorized_to_work_us=True, requires_sponsorship=None,
                                     requires_sponsorship_now_or_in_future=False, authorization_type='')
        self.profile = SimpleNamespace(work_authorization=self.auth, approved_answers=ApprovedAnswers(),
            location=SimpleNamespace(city='Palo Alto',state='CA',country='United States'))
        self.preferences = SimpleNamespace(work_arrangements=SimpleNamespace(onsite=True))

    def field(self, label):
        return FormField(label=label,field_id='arbitrary-question-id',name=None,
                         field_type='text',role='combobox',required=True)

    def resolve(self, label):
        return resolve_review_field(self.field(label), self.profile, self.preferences)

    def test_authorization_exact_garner_question(self):
        self.assertEqual(self.resolve('Are you legally authorized to work in the United States of America? *').value,'Yes')

    def test_sponsorship_exact_garner_question(self):
        self.assertEqual(self.resolve('Will you now or in the future require sponsorship for employment visa status (e.g., H-1B visa status)?*').value,'No')

    def test_materially_changed_sensitive_wording_stays_review(self):
        for label in (
            'Do you currently require sponsorship?', 'Will you require sponsorship in the future?',
            'Can you work without sponsorship?', 'Do you have unrestricted authorization?',
            'Are you legally authorized to work in Canada?',
            'Are you legally authorized to work in the United States without sponsorship?',
            'Are you currently based in or planning to relocate to the NYC area and willing to work in our NYC office 3 days a week?',
            'What is your desired salary?',
        ):
            with self.subTest(label=label):
                self.assertEqual(self.resolve(label).status,'REVIEW')
                self.assertIsNone(approved_choice(self.field(label),self.profile))

    def test_facts_are_independent_and_legacy_fact_is_not_used(self):
        self.auth.authorized_to_work_us = None
        self.auth.requires_sponsorship = True
        self.assertEqual(self.resolve('Are you legally authorized to work in the United States?').status,'REVIEW')
        self.assertEqual(self.resolve('Will you now or in the future require sponsorship?').value,'No')
        self.auth.requires_sponsorship_now_or_in_future = None
        self.assertEqual(self.resolve('Will you now or in the future require sponsorship?').status,'REVIEW')

    def test_city_requires_complete_explicit_location(self):
        request = approved_choice(self.field('Location (City)*'),self.profile)
        self.assertIn('Palo Alto, California, United States',request.labels)
        self.profile.location.state = ''
        self.assertIsNone(approved_choice(self.field('Location (City)*'),self.profile))

    def test_state_uses_explicit_value_and_spelling_alias(self):
        request = approved_choice(self.field('Which state do you currently reside in?*'),self.profile)
        self.assertEqual(request.labels,['CA','California'])
        self.profile.location.state = ''
        self.assertIsNone(approved_choice(self.field('Which state do you currently reside in?*'),self.profile))


class ApprovedAnswerTests(ReviewResolverTests):
    NYC = 'Are you currently based in or planning to relocate to the NYC area and willing to work in our NYC office 3 days a week?*'

    def approve(self, **facts):
        base = dict(desired_salary='$150,000', nyc_based_or_willing_to_relocate=True, onsite_days_per_week_willing=3)
        self.profile.approved_answers = ApprovedAnswers(**{**base, **facts})

    def test_salary_resolves_only_from_approved_value(self):
        self.assertEqual(self.resolve('What is your desired salary?').status, 'REVIEW')
        self.approve()
        got = self.resolve('What is your desired salary?')
        self.assertEqual((got.status, got.value), ('READY', '$150,000'))

    def test_other_compensation_wording_is_not_the_approved_salary(self):
        self.approve()
        for label in ('What is your current salary?', 'What is your hourly rate?', 'Salary history'):
            with self.subTest(label=label):
                self.assertEqual(self.resolve(label).status, 'REVIEW')

    def test_nyc_needs_both_facts(self):
        self.assertEqual(self.resolve(self.NYC).status, 'REVIEW')
        self.approve()
        got = self.resolve(self.NYC)
        self.assertEqual((got.status, got.value), ('READY', 'Yes'))
        for missing in (dict(nyc_based_or_willing_to_relocate=None), dict(nyc_based_or_willing_to_relocate=False),
                        dict(onsite_days_per_week_willing=None)):
            with self.subTest(missing=missing):
                self.approve(**missing)
                self.assertEqual(self.resolve(self.NYC).status, 'REVIEW')

    def test_generic_onsite_preference_never_answers_nyc(self):
        self.assertTrue(self.preferences.work_arrangements.onsite)
        self.assertEqual(self.resolve(self.NYC).status, 'REVIEW')

    def test_more_days_than_approved_or_other_city_stays_review(self):
        self.approve()
        for label in (self.NYC.replace('3 days', '5 days'),
                      self.NYC.replace('NYC', 'Boston'),
                      'Are you willing to work onsite 3 days a week?'):
            with self.subTest(label=label):
                self.assertEqual(self.resolve(label).status, 'REVIEW')

    def test_browserskill_choice_and_text_permission(self):
        from app.jobs.browserskill_greenhouse import permitted_text
        self.approve()
        self.assertEqual(approved_choice(self.field(self.NYC), self.profile).labels, ['Yes'])
        salary = FormField(label='What is your desired salary?', field_id='q', name=None,
                           field_type='text', role=None, required=True)
        self.assertTrue(permitted_text(salary))
        self.assertIsNone(approved_choice(self.field('What is your desired salary?'), self.profile))
        self.profile.approved_answers = ApprovedAnswers()
        self.assertIsNone(approved_choice(self.field(self.NYC), self.profile))


class StateNameTests(ReviewResolverTests):
    def test_state_abbreviations_expand_to_full_names(self):
        for abbreviation, name in (('WA', 'Washington'), ('CA', 'California'), ('NY', 'New York')):
            with self.subTest(state=abbreviation):
                self.profile.location.state = abbreviation
                choice = approved_choice(self.field('Which state do you currently reside in?*'), self.profile)
                self.assertEqual(choice.search, name)
                city = approved_choice(self.field('Location (City)*'), self.profile)
                self.assertIn(f'Palo Alto, {name}, United States', city.labels)
