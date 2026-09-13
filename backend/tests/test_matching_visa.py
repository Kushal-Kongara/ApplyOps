"""Visa / eligibility signal detection tests.

Visa status is reported, never scored — these tests only exercise
`detect_visa_signal` in isolation; scorer tests separately confirm it never
touches the total score.
"""

import unittest

from app.matching.visa import (
    CITIZENSHIP_OR_CLEARANCE_REQUIRED,
    SPONSORSHIP_AVAILABLE,
    SPONSORSHIP_RISK,
    UNKNOWN,
    detect_visa_signal,
)


class DetectVisaSignalTest(unittest.TestCase):
    def test_we_do_not_provide_sponsorship_is_risk(self):
        signal = detect_visa_signal("Engineer", "We do not provide sponsorship for this role.")
        self.assertEqual(signal.status, SPONSORSHIP_RISK)
        self.assertIn("sponsorship", signal.evidence.lower())

    def test_no_sponsorship_available_is_risk(self):
        signal = detect_visa_signal("Engineer", "No sponsorship available at this time.")
        self.assertEqual(signal.status, SPONSORSHIP_RISK)

    def test_must_not_require_sponsorship_is_risk(self):
        signal = detect_visa_signal("Engineer", "Candidates must not require sponsorship.")
        self.assertEqual(signal.status, SPONSORSHIP_RISK)

    def test_us_citizen_only_is_citizenship_required(self):
        signal = detect_visa_signal("Engineer", "US citizen only.")
        self.assertEqual(signal.status, CITIZENSHIP_OR_CLEARANCE_REQUIRED)

    def test_us_citizenship_required_is_citizenship_required(self):
        signal = detect_visa_signal("Engineer", "US citizenship required for this position.")
        self.assertEqual(signal.status, CITIZENSHIP_OR_CLEARANCE_REQUIRED)

    def test_active_security_clearance_required_is_citizenship_required(self):
        signal = detect_visa_signal("Engineer", "Active security clearance required.")
        self.assertEqual(signal.status, CITIZENSHIP_OR_CLEARANCE_REQUIRED)
        self.assertIn("clearance", signal.evidence.lower())

    def test_explicit_sponsorship_available_is_detected(self):
        signal = detect_visa_signal("Engineer", "Visa sponsorship is available for this role.")
        self.assertEqual(signal.status, SPONSORSHIP_AVAILABLE)

    def test_generic_authorized_to_work_stays_unknown(self):
        signal = detect_visa_signal(
            "Engineer", "You must be authorized to work in the United States."
        )
        self.assertEqual(signal.status, UNKNOWN)
        self.assertIsNone(signal.evidence)

    def test_no_visa_language_at_all_stays_unknown(self):
        signal = detect_visa_signal("Engineer", "Build great products with us.")
        self.assertEqual(signal.status, UNKNOWN)
        self.assertIsNone(signal.evidence)

    def test_evidence_preserves_original_wording(self):
        signal = detect_visa_signal("Engineer", "Note: we do not provide sponsorship for this role.")
        self.assertIn("do not provide", signal.evidence.lower())


if __name__ == "__main__":
    unittest.main()
