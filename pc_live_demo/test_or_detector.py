import sys
import unittest
from unittest.mock import patch

from live_fall_fsm import OnlineFallDetectorFSM, MultiTargetFallDetector


def target(x, speed=0.0, slot=1):
    return dict(slot=slot, x_mm=x, y_mm=2000, v_mps=speed)


def drop(detector, start=0, slot=1):
    for i in range(start + 1):
        detector.update(i * 100_000, [target(500, slot=slot)])
    for j in range(1, 4):
        result = detector.update((start+j)*100_000, [target(1400, 1.2 if j == 1 else 0, slot)])
    return result


class OrDetectorTests(unittest.TestCase):
    def test_rule_can_trigger_before_ml_warmup(self):
        d = OnlineFallDetectorFSM(candidate_mode='or', window_score=lambda t,f: -10, ml_threshold=.2)
        summary, alarm = drop(d, start=3)
        self.assertEqual(summary['state'], 'SUSPECTED_FALL')
        self.assertEqual(summary['trigger_source'], 'RULE')
        self.assertIsNone(summary['ml_score'])
        self.assertIsNone(alarm)

    def test_rule_can_trigger_when_ready_svm_rejects(self):
        d = OnlineFallDetectorFSM(candidate_mode='or', window_score=lambda t,f: -10, ml_threshold=.2)
        summary, _ = drop(d, start=20)
        self.assertEqual(summary['trigger_source'], 'RULE')
        self.assertEqual(summary['ml_score'], -10)

    def test_ml_can_trigger_without_rule_and_hold_is_latched(self):
        d = OnlineFallDetectorFSM(candidate_mode='or', window_score=lambda t,f: 1 if t < 2_000_000 else -5, ml_threshold=.2)
        alarms = []
        for i in range(101):
            summary, alarm = d.update(i*100_000, [target(1400)])
            if i == 19:
                self.assertEqual(summary['trigger_source'], 'ML')
                self.assertEqual(summary['state'], 'SUSPECTED_FALL')
            if i < 99:
                self.assertIsNone(alarm)
            if alarm:
                alarms.append(alarm)
        self.assertEqual(len(alarms), 1)
        self.assertEqual(alarms[0]['trigger_source'], 'ML')
        self.assertGreaterEqual(alarms[0]['latency_s'], 8)

    def test_both_conditions_record_both_sources(self):
        d = OnlineFallDetectorFSM(candidate_mode='or', window_score=lambda t,f: 1, ml_threshold=.2)
        # Align the first low median with a fresh inference at 2.3 s.
        drop(d, start=21)
        self.assertEqual(d.fall_candidate['trigger_source'], 'RULE+ML')

    def test_old_mode_does_not_use_rule_when_ml_rejects(self):
        d = OnlineFallDetectorFSM(window_score=lambda t,f: -10, ml_threshold=.2)
        summary, _ = drop(d, start=20)
        self.assertEqual(summary['state'], 'MONITORING')

    def test_stale_positive_score_does_not_trigger_at_new_height(self):
        d = OnlineFallDetectorFSM(candidate_mode='or', window_score=lambda t,f: 1, ml_threshold=.2)
        for i in range(20):
            d.update(i*100_000, [target(1200)])
        d.update(2_000_000, [target(1400)])
        summary, _ = d.update(2_050_000, [target(1400)])
        self.assertLess(summary['z_est_m'], .48)
        self.assertEqual(summary['ml_score'], 1)
        self.assertEqual(summary['state'], 'MONITORING')

    def test_recovery_and_gap_cancel_candidate(self):
        for reason in ('height', 'gap', 'missing', 'backlog'):
            with self.subTest(reason=reason):
                d = OnlineFallDetectorFSM(candidate_mode='or', window_score=lambda t,f: -10)
                drop(d, start=3)
                if reason == 'height':
                    d.update(700_000, [target(500)])
                    summary, alarm = d.update(800_000, [target(500)])
                elif reason == 'gap':
                    summary, alarm = d.update(10_000_000, [target(1400)])
                elif reason == 'missing':
                    summary, alarm = d.update(700_000, [])
                else:
                    summary, alarm = d.update(700_000, [target(1400)], backlog_ms=501)
                self.assertEqual(summary['state'], 'MONITORING')
                self.assertIsNone(alarm)
                self.assertIsNone(summary['trigger_source'])

    def test_independent_slot_alarm_and_primary_selection(self):
        d = MultiTargetFallDetector(candidate_mode='or', window_score=lambda t,f: -10)
        alarms = []
        for i in range(95):
            second = target(500 if i < 5 else 1400, 1.2 if i == 5 else 0, slot=2)
            s, batch = d.update(i*100_000, [target(500, slot=1), second, target(500, slot=3)])
            if i == 6:
                self.assertEqual(s['slot'], 2)
                self.assertEqual(s['state'], 'SUSPECTED_FALL')
            alarms.extend(batch)
        self.assertEqual([a['slot'] for a in alarms], [2])
        self.assertEqual(d.detectors[1].state, 'MONITORING')
        self.assertEqual(d.detectors[3].state, 'MONITORING')

    def test_or_requires_model(self):
        with self.assertRaises(ValueError):
            OnlineFallDetectorFSM(candidate_mode='or')

    def test_entrypoint_enforces_or_with_real_svm(self):
        import run_fsm_or_svm, web_dashboard
        with patch.object(sys, 'argv', ['run_fsm_or_svm.py', '--height', '1.7', '--no-browser']), patch.object(web_dashboard, 'main') as main:
            run_fsm_or_svm.main()
            self.assertEqual(sys.argv[sys.argv.index('--candidate-mode')+1], 'or')
            self.assertIn('fall_svm_6f_2s.joblib', sys.argv[sys.argv.index('--model')+1])
            main.assert_called_once()


if __name__ == '__main__':
    unittest.main()
