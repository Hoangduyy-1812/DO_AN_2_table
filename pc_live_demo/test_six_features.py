import unittest
from copy import deepcopy
from types import SimpleNamespace

from fall_window import FEATURES_6, FEATURES_9, WINDOW_US, extract_features, feature_set_from_bundle
from live_fall_fsm import MultiTargetFallDetector, OnlineFallDetectorFSM


def points():
    return [dict(t_us=i*100_000, x_mm=i*100, y_mm=3000-i*50,
                 v_signed=-1.0 if i<10 else 1.0, v=1.0, zs=(1700-i*100)/1000)
            for i in range(21)]


class SixFeaturesTests(unittest.TestCase):
    def test_report_formulas_and_signed_velocity(self):
        actual = extract_features(points(), 2_000_000, '6')
        expected = (1.0, 20.0, 1.8, -0.9, 440/441, 0.0)
        self.assertEqual(len(actual), 6)
        for got, want in zip(actual, expected):
            self.assertAlmostEqual(got, want)

    def test_quiet_time_uses_timestamps_and_strict_threshold(self):
        p = points()
        p[1]['t_us'] = 50_000
        for item in p:
            item['v_signed'] = 0.0
        p[0]['v_signed'] = -0.15
        p[1]['v_signed'] = 0.149
        p[2]['v_signed'] = -0.149
        p[3]['v_signed'] = 0.15
        result = extract_features(p, 2_000_000, '6')
        self.assertAlmostEqual(result[5], 1.9)
        self.assertAlmostEqual(result[1], 0.299 / 0.05)

    def test_delta_y_is_endpoint_change_not_range(self):
        p = points()
        for i, item in enumerate(p):
            item['y_mm'] = 2000 if i<3 or i>=18 else 4500
        self.assertEqual(extract_features(p, 2_000_000, '6')[3], 0.0)
        self.assertEqual(extract_features(p, 2_000_000, '9')[7], 2.5)

    def test_causal_window_and_warmup(self):
        p = points()
        self.assertIsNone(extract_features([], 2_000_000))
        self.assertIsNone(extract_features(p[3:], 2_000_000))
        baseline = extract_features(p, 2_000_000)
        future = dict(p[-1], t_us=2_100_000, x_mm=90000, v_signed=900)
        self.assertEqual(extract_features(p+[future], 2_000_000), baseline)

    def test_live_detector_preserves_signed_raw_inputs(self):
        captured = []
        detector = OnlineFallDetectorFSM(window_score=lambda t, f: captured.append((t, f)) or -99.0)
        p = points()
        for item in p:
            detector.update(item['t_us'], [dict(slot=1, x_mm=item['x_mm'],
                            y_mm=item['y_mm'], v_mps=item['v_signed'])])
        self.assertTrue(captured)
        for t, features in captured:
            self.assertEqual(features, extract_features([x for x in p if x['t_us']<=t], t, '6'))

    def test_six_feature_windows_are_separate_for_three_slots(self):
        captured = []
        detector = MultiTargetFallDetector(window_score=lambda t, f: captured.append(f) or -99.0)
        for i in range(21):
            detector.update(i*100_000, [dict(slot=s, x_mm=100*s+i*10*s,
                y_mm=2000, v_mps=0.1*s) for s in (1,2,3)])
        self.assertEqual(len(captured), 3)
        for slot, features in enumerate(captured, 1):
            self.assertAlmostEqual(features[0], 0.1*slot)
            # First score is at 1.9 s (the unchanged 180 ms edge tolerance).
            self.assertAlmostEqual(features[2], 0.17*slot)

    def test_bundle_mismatch_is_rejected(self):
        bundle = dict(features=FEATURES_6, window_us=WINDOW_US, feature_set='6',
                      feature_definition='report6_signed_raw_v1',
                      model=SimpleNamespace(n_features_in_=6, classes_=[0,1]))
        self.assertEqual(feature_set_from_bundle(bundle), '6')
        wrong = deepcopy(bundle)
        wrong['model'].n_features_in_ = 9
        with self.assertRaises(ValueError):
            feature_set_from_bundle(wrong)
        legacy = dict(features=FEATURES_9, window_us=WINDOW_US,
                      model=SimpleNamespace(n_features_in_=9, classes_=[0,1]))
        self.assertEqual(feature_set_from_bundle(legacy), '9')


if __name__ == '__main__':
    unittest.main()
