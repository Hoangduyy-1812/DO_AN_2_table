"""Regression checks for excluded frames and receiver replay handling.

Run with python -m unittest discover -s pc_live_demo -p test_live_demo.py.
"""
import contextlib
import io
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from live_fall_fsm import MultiTargetFallDetector, OnlineFallDetectorFSM
from live_receiver import LiveDetectorRecorder
from protocol import COUNTERS
from receiver import LineSession
from web_dashboard import LiveWebRecorder, WebHandler, broadcast, process_frame, subscribers


TARGET = {'slot': 1, 'x_mm': 500, 'y_mm': 1500, 'v_mps': 0.0}


def frame_record():
    return {
        **dict.fromkeys(COUNTERS, 0),
        'schema': 1, 'type': 'frame',
        'device_id': '001122334455', 'boot_id': '12345678',
        'seq': 1, 't_us': 1000000, 'sent_us': 1000000,
        'last_frame_age_ms': 0, 'rssi_dbm': -50,
        'raw_hex': 'AAFF0300F481DC8500006801' + '00' * 16 + '55CC',
    }


class LiveDemoTests(unittest.TestCase):
    def test_slow_dashboard_client_receives_latest_snapshot(self):
        client = queue.Queue(maxsize=1)
        with patch('web_dashboard.subscribers', [client]):
            broadcast({'t_s': 1, 'alarms': []})
            broadcast({'t_s': 2, 'alarms': [{'slot': 3}]})
            broadcast({'t_s': 3, 'alarms': [{'slot': 3}]})
            self.assertEqual(client.get_nowait(), {'t_s': 3, 'alarms': [{'slot': 3}]})
            self.assertTrue(client.empty())

    def test_tcp_ack_and_recording_continue_while_analysis_waits(self):
        started, release, completed = threading.Event(), threading.Event(), threading.Event()
        analyzed = []

        def slow_analysis(t_us, targets, **kwargs):
            analyzed.append((t_us, kwargs['skipped_frame']))
            if len(analyzed) == 1:
                started.set()
                release.wait(3)
            if t_us == 1_600_000:
                completed.set()

        with tempfile.TemporaryDirectory() as tmp, patch('web_dashboard.process_frame', slow_analysis):
            recorder = LiveWebRecorder(Path(tmp) / 'session')
            try:
                self.assertEqual(recorder.record(frame_record()), ('ACK 12345678 1\n', True))
                self.assertTrue(started.wait(1))
                for offset in range(1, 7):
                    record = frame_record()
                    stamp = 1_000_000 + offset * 100_000
                    record.update(seq=offset + 1, t_us=stamp, sent_us=stamp)
                    self.assertEqual(recorder.record(record),
                                     (f'ACK 12345678 {offset + 1}\n', True))
                self.assertEqual(len(analyzed), 1)
                self.assertEqual(recorder.total, 7)
                self.assertEqual(len((recorder.directory / 'samples.csv').read_text().splitlines()), 8)
                release.set()
                self.assertTrue(completed.wait(1))
                self.assertEqual(analyzed[:2], [(1_000_000, False), (1_300_000, True)])
            finally:
                release.set()
                recorder.close()

    def test_windows_abort_during_dashboard_keepalive_cleans_up(self):
        handler = WebHandler.__new__(WebHandler)
        handler.path = '/events'
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = [None, ConnectionAbortedError(10053, 'disconnected')]
        initial_subscribers = list(subscribers)

        with patch.object(queue.Queue, 'get', side_effect=queue.Empty):
            handler.do_GET()

        handler.wfile.write.assert_called_with(b': keepalive\n\n')
        self.assertEqual(subscribers, initial_subscribers)

    def test_dashboard_reports_targets_separately_from_detector(self):
        multi_targets = [TARGET, {**TARGET, 'slot': 2, 'y_mm': 4493}]
        cases = [
            (multi_targets, 770, 0, 'BACKLOG_EXCEEDED', None),
            (multi_targets, 400, 120, 'PC_ANALYSIS_DELAY', None),
            (multi_targets, 10, 0, '', 1),
            ([TARGET], 10, 0, '', 1),
            ([], 10, 0, 'NO_TARGET', None),
        ]
        for index, (targets, backlog, pc_wait, note, slot) in enumerate(cases):
            with (self.subTest(note=note),
                  patch('web_dashboard.broadcast') as broadcast,
                  patch('web_dashboard.global_detector', MultiTargetFallDetector())):
                process_frame(index * 100_000, targets, backlog_ms=backlog, pc_wait_ms=pc_wait)
                summary = broadcast.call_args.args[0]
                self.assertEqual(summary['raw_targets'], targets)
                self.assertEqual(summary['backlog_ms'], backlog)
                self.assertEqual(summary['pc_wait_ms'], pc_wait)
                self.assertEqual(summary['note'], note)
                self.assertEqual(summary['slot'], slot)
                self.assertEqual([t['slot'] for t in summary['target_states']],
                                 [t['slot'] for t in targets] if slot else [])
                self.assertEqual(summary['alarms'], [])

    def test_three_slots_keep_separate_fall_windows_and_alarms(self):
        def score(t_us, features):
            return 0.9 if features[0] < 0.5 else 0.1

        detector = MultiTargetFallDetector(window_score=score, feature_set="9")
        alarms = []
        for i in range(110):
            targets = [
                {**TARGET, 'y_mm': 1500 + i * 4, 'v_mps': 0.4},
                {**TARGET, 'slot': 2, 'x_mm': 1400 if i >= 20 else 400, 'y_mm': 2000},
                {**TARGET, 'slot': 3, 'x_mm': 1450 if i >= 20 else 450, 'y_mm': 2800},
            ]
            summary, new_alarms = detector.update(i * 100_000, targets)
            alarms.extend(new_alarms)
        self.assertEqual([alarm['slot'] for alarm in alarms], [2, 3])
        self.assertEqual(summary['slot'], 2)
        self.assertEqual([t['state'] for t in summary['target_states']],
                         ['MONITORING', 'ALARM_TRIGGERED', 'ALARM_TRIGGERED'])

    def test_losing_one_slot_does_not_reset_other_slots(self):
        detector = MultiTargetFallDetector(window_score=lambda t_us, features: 0.9)
        second = {**TARGET, 'slot': 2, 'y_mm': 2000}
        for i in range(22):
            detector.update(i * 100_000, [TARGET, second])
        detector.update(2_200_000, [TARGET])
        summary, alarms = detector.update(2_300_000, [TARGET, second])
        self.assertEqual([t['ml_score'] for t in summary['target_states']], [0.9, None])
        self.assertEqual(alarms, [])

    def test_excluded_frames_return_status_and_reset_candidate(self):
        cases = [
            ([], 0, 'NO_TARGET'),
            ([TARGET, {**TARGET, 'slot': 2}], 0, 'MULTI_TARGET_2'),
            ([TARGET], 501, 'BACKLOG_EXCEEDED'),
        ]
        for targets, backlog, note in cases:
            with self.subTest(note=note):
                detector = OnlineFallDetectorFSM()
                for i in range(4):
                    target = {**TARGET, 'x_mm': 500 if i < 2 else 1500,
                              'v_mps': 1.0}
                    detector.update(1000000 + i * 100000, [target])
                self.assertEqual(detector.state, 'SUSPECTED_FALL')
                summary, alarm = detector.update(1400000, targets, backlog)
                self.assertEqual(summary['note'], note)
                self.assertEqual(summary['state'], 'MONITORING')
                self.assertEqual(summary['v_mps'], 0)
                self.assertIsNone(alarm)
                self.assertIsNone(detector.fall_candidate)

    def test_continuous_fall_triggers_once_and_rearms(self):
        detector = OnlineFallDetectorFSM()
        alarms = []
        for i in range(100):
            target = {**TARGET, 'x_mm': 500 if i < 2 else 1500,
                      'v_mps': 1.0 if i < 5 else 0.0}
            _, alarm = detector.update(1000000 + i * 100000, [target])
            if alarm:
                alarms.append(alarm)
        self.assertEqual(len(alarms), 1)
        self.assertGreaterEqual(alarms[0]['latency_s'], 8.0)
        self.assertLessEqual(alarms[0]['latency_s'], 8.1)
        for i in range(100, 103):
            detector.update(1000000 + i * 100000, [TARGET])
        self.assertEqual(detector.state, 'MONITORING')

    def test_ml_uses_window_score_and_resets_on_gap(self):
        observed = []

        def score(t_us, features):
            observed.append((t_us, features))
            return 0.9

        detector = OnlineFallDetectorFSM(window_score=score, ml_threshold=0.8)
        low_target = {**TARGET, 'x_mm': 1500}
        for i in range(19):
            _, alarm = detector.update(i * 100_000, [low_target])
            self.assertIsNone(alarm)
        self.assertEqual(observed, [])
        summary, alarm = detector.update(1_900_000, [low_target])
        self.assertEqual(summary['state'], 'SUSPECTED_FALL')
        self.assertEqual(summary['ml_score'], 0.9)
        self.assertIsNone(alarm)
        summary, alarm = detector.update(2_400_000, [low_target])
        self.assertEqual(summary['state'], 'MONITORING')
        self.assertIsNone(summary['ml_score'])
        self.assertIsNone(alarm)

    def test_tcp_replay_is_acknowledged_without_updating_detector(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = LiveDetectorRecorder(Path(tmp) / 'session')
            try:
                wire = (json.dumps(frame_record()) + '\n').encode()
                session = LineSession()
                with patch.object(recorder.detector, 'update',
                                  wraps=recorder.detector.update) as update:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(session.feed(wire[:30], recorder), [])
                        replies = session.feed(wire[30:] + wire, recorder)
                    self.assertEqual(replies, [b'ACK 12345678 1\n'] * 2)
                    self.assertEqual(update.call_count, 1)
                self.assertEqual(recorder.total, 1)
                self.assertEqual(recorder.duplicates, 1)
                self.assertEqual(recorder.frame_count, 1)
            finally:
                recorder.close()

    def test_status_is_recorded_without_updating_detector(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = LiveDetectorRecorder(Path(tmp) / 'session')
            try:
                status = frame_record()
                status.update(type='status', seq=0)
                status.pop('raw_hex')
                with patch.object(recorder.detector, 'update') as update:
                    ack, saved = recorder.record(status)
                    update.assert_not_called()
                self.assertEqual(ack, 'ACK 12345678 0\n')
                self.assertFalse(saved)
                self.assertEqual(recorder.latest_status, status)
            finally:
                recorder.close()


if __name__ == '__main__':
    unittest.main()
