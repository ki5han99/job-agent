import unittest

from app.config.loader import load_answers
from app.jobs.consent import classify_consent

APPROVED = set(load_answers().consent.approved_categories)


class ConsentClassificationTests(unittest.TestCase):
    ELIGIBLE = {
        'By clicking this box and submitting your application, you consent to our Applicant Privacy Statement.': {'PRIVACY_ACK'},
        'I have read and acknowledge the Candidate Privacy Notice.': {'PRIVACY_ACK'},
        'Privacy *': {'PRIVACY_ACK'},
        'I consent to the processing of my personal data in accordance with the Data Protection Policy': {'DATA_PROCESSING_ACK'},
        'I have read and accept the Terms of Use': {'TERMS_ACK'},
        'By clicking this box and submitting your application, you consent to Strider Technologies conducting '
        'third-party background checks and utilizing advanced tools to assess potential risks as part of your application process.': {'BACKGROUND_CHECK_AUTH'},
        'I certify that all information provided is true and complete': {'TRUTHFULNESS_CERT'},
        'I agree to resolve any disputes through binding arbitration': {'ARBITRATION'},
        'I have read and understand Tailscale\'s "Candidate Privacy Policy" and "AI Guidelines" regarding the collection '
        'and use of my personal information and use of AI tools in the hiring and interviewing process.': {'PRIVACY_ACK', 'AI_USE_ACK'},
    }
    NEVER = (
        'I agree to receive marketing emails and text messages',
        'Sign me up for the newsletter',
        'I consent to you keeping my data for future job opportunities',
        'Keep me in your talent community',
        'I consent to my data being shared with third parties',
        'I agree to waive any claims against the company',
        'I do not consent to the processing of my personal data',
        'ASA', 'CFA', '',
    )

    def test_approved_categories_are_eligible(self):
        for label, categories in self.ELIGIBLE.items():
            with self.subTest(label=label[:60]):
                got = classify_consent(label, APPROVED)
                self.assertTrue(got.eligible, got.reason)
                self.assertTrue(categories <= set(got.categories), got.categories)

    def test_marketing_sharing_waivers_and_opposite_polarity_are_never_ticked(self):
        for label in self.NEVER:
            with self.subTest(label=label[:60]):
                self.assertFalse(classify_consent(label, APPROVED).eligible)

    def test_nothing_is_eligible_unless_the_category_is_approved(self):
        for label in self.ELIGIBLE:
            self.assertFalse(classify_consent(label).eligible)
        only_privacy = {'PRIVACY_ACK'}
        self.assertTrue(classify_consent('I acknowledge the Privacy Policy', only_privacy).eligible)
        got = classify_consent('I certify that all information provided is true and complete', only_privacy)
        self.assertFalse(got.eligible)
        self.assertIn('TRUTHFULNESS_CERT', got.reason)

    def test_every_matched_category_must_be_approved(self):
        label = 'I acknowledge the Privacy Policy and consent to AI tools in hiring'
        self.assertFalse(classify_consent(label, {'PRIVACY_ACK'}).eligible)
        self.assertTrue(classify_consent(label, {'PRIVACY_ACK', 'AI_USE_ACK'}).eligible)

    def test_repository_answers_do_not_approve_marketing(self):
        self.assertNotIn('MARKETING', ' '.join(APPROVED).upper())
