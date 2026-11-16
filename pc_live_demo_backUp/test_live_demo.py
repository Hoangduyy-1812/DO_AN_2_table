"""Regression checks for excluded frames and receiver replay handling.

Run with python -m unittest discover -s pc_live_demo -p test_live_demo.py.
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live_fall_fsm import OnlineFallDetectorFSM
from live_receiver import LiveDetectorRecorder
from protocol import COUNTERS
from receiver import LineSession


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
