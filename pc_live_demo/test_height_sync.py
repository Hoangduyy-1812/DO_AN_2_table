import io
import json
from unittest import TestCase
from unittest.mock import patch

from height_sync import apply_height, read_height
from live_fall_fsm import MultiTargetFallDetector


class HeightSyncTests(TestCase):
    def test_reads_existing_esp32_height_api(self):
        with patch('height_sync.urllib.request.urlopen',return_value=io.BytesIO(b'{"h_mount_m":1.2}')) as request:
            self.assertEqual(read_height('http://radar.local/'),1.2)
            self.assertEqual(request.call_args.args[0],'http://radar.local/api/state')

    def test_height_change_resets_candidates_and_all_slot_windows(self):
        detector=MultiTargetFallDetector()
        for child in detector.detectors.values():
            child.state='SUSPECTED_FALL';child.fall_candidate={'impact_t_s':1}
            child.recent_points=[{'t_us':1}]
        self.assertTrue(apply_height(detector,1.2))
        for child in detector.detectors.values():
            self.assertEqual(child.h_mount,1200)
            self.assertEqual(child.state,'MONITORING')
            self.assertEqual(child.recent_points,[])
            self.assertIsNone(child.fall_candidate)
        self.assertFalse(apply_height(detector,1.2))

    def test_bad_height_is_rejected(self):
        for value in (True,'1.2',None,.9,3.0):
            with self.subTest(value=value):
                body=json.dumps({'h_mount_m':value}).encode()
                with patch('height_sync.urllib.request.urlopen',return_value=io.BytesIO(body)):
                    with self.assertRaises(ValueError):read_height('http://radar.local')
