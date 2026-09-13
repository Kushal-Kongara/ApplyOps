"""Location alignment scoring tests."""

import unittest

from app.matching.location import LocationClass, MAX_LOCATION_SCORE, classify_location, score_location
from tests.support import make_profile

PRIMARY_LOCATIONS = make_profile().primary_locations


class ClassifyLocationTest(unittest.TestCase):
    def test_bay_area_city_is_primary(self):
        self.assertEqual(classify_location("San Jose, CA", PRIMARY_LOCATIONS), LocationClass.PRIMARY)
        self.assertEqual(
            classify_location("San Francisco Bay Area, Remote", PRIMARY_LOCATIONS), LocationClass.PRIMARY
        )

    def test_clearly_us_remote_is_remote_us(self):
        self.assertEqual(classify_location("US - Remote", PRIMARY_LOCATIONS), LocationClass.REMOTE_US)
        self.assertEqual(classify_location("Remote (United States)", PRIMARY_LOCATIONS), LocationClass.REMOTE_US)

    def test_bare_remote_with_no_country_is_unknown(self):
        self.assertEqual(classify_location("Remote", PRIMARY_LOCATIONS), LocationClass.UNKNOWN)

    def test_other_us_city_is_other_us(self):
        self.assertEqual(classify_location("New York City", PRIMARY_LOCATIONS), LocationClass.OTHER_US)
        self.assertEqual(classify_location("Seattle", PRIMARY_LOCATIONS), LocationClass.OTHER_US)
        self.assertEqual(classify_location("Washington, DC", PRIMARY_LOCATIONS), LocationClass.OTHER_US)

    def test_ambiguous_text_is_unknown(self):
        self.assertEqual(classify_location("Hybrid", PRIMARY_LOCATIONS), LocationClass.UNKNOWN)
        self.assertEqual(classify_location("", PRIMARY_LOCATIONS), LocationClass.UNKNOWN)

    def test_clearly_international_location(self):
        self.assertEqual(classify_location("London, UK", PRIMARY_LOCATIONS), LocationClass.INTERNATIONAL)
        self.assertEqual(classify_location("Singapore", PRIMARY_LOCATIONS), LocationClass.INTERNATIONAL)
        self.assertEqual(classify_location("India - Remote", PRIMARY_LOCATIONS), LocationClass.INTERNATIONAL)
        self.assertEqual(classify_location("Remote France", PRIMARY_LOCATIONS), LocationClass.INTERNATIONAL)


class ScoreLocationTest(unittest.TestCase):
    def test_primary_location_gets_full_credit(self):
        result = score_location("San Francisco, CA", PRIMARY_LOCATIONS, True, True)
        self.assertEqual(result.points, MAX_LOCATION_SCORE)

    def test_remote_us_gets_full_credit_when_allowed(self):
        result = score_location("US - Remote", PRIMARY_LOCATIONS, True, True)
        self.assertEqual(result.points, MAX_LOCATION_SCORE)

    def test_other_us_gets_partial_credit_when_relocation_allowed(self):
        result = score_location("Austin, TX", PRIMARY_LOCATIONS, True, True)
        self.assertGreater(result.points, 0)
        self.assertLess(result.points, MAX_LOCATION_SCORE)

    def test_other_us_gets_zero_when_relocation_not_allowed(self):
        result = score_location("Austin, TX", PRIMARY_LOCATIONS, True, False)
        self.assertEqual(result.points, 0)

    def test_unknown_location_gets_low_partial_credit_not_zero(self):
        result = score_location("Hybrid", PRIMARY_LOCATIONS, True, True)
        self.assertGreater(result.points, 0)
        self.assertLess(result.points, MAX_LOCATION_SCORE)

    def test_international_location_gets_zero(self):
        result = score_location("Tokyo, Japan", PRIMARY_LOCATIONS, True, True)
        self.assertEqual(result.points, 0)

    def test_unknown_location_is_never_hard_rejected(self):
        # score_location always returns a score, never raises or signals
        # rejection, for a blank/unrecognized location.
        result = score_location("", PRIMARY_LOCATIONS, True, True)
        self.assertGreaterEqual(result.points, 0)


if __name__ == "__main__":
    unittest.main()
