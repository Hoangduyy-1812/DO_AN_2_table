"""Real-time online FSM Fall Detector for LD2450.
Receives frames incrementally from TCP stream or file.
State Machine:
  MONITORING -> (rapid descent >= 0.78 m/s, dz >= 0.5m) -> SUSPECTED_FALL -> (stay on floor >= 8.0s) -> ALARM_TRIGGERED
Reset rules:
  - Any time gap > 0.35s
  - Any slot change (target report slot differs)
  - active_count != 1 (no target or multi-target)
  - backlog_ms > 500 ms
"""
import statistics

from fall_window import FEATURE_SETS, STEP_US, WINDOW_US, extract_features

MAX_BACKLOG_MS = 500.0

class OnlineFallDetectorFSM:
    def __init__(self, h_mount_mm=1700.0, v_thresh=0.78, hold_s=8.0,
                 window_score=None, ml_threshold=0.5, feature_set="6",
                 min_drop_m=0.50, trigger_floor_m=0.40,
                 low_hold_floor_m=0.48, rearm_height_m=0.55,
                 prior_upright_m=0.90, lookback_s=1.25):
        if feature_set not in FEATURE_SETS:
            raise ValueError("feature_set must be '6' or '9'")
        self.feature_set = feature_set
        self.h_mount = h_mount_mm
        self.v_thresh = v_thresh
        self.hold_s = hold_s
        self.window_score = window_score
        self.ml_threshold = ml_threshold
        self.min_drop_m = min_drop_m
        self.trigger_floor_m = trigger_floor_m
        self.low_hold_floor_m = low_hold_floor_m
        self.rearm_height_m = rearm_height_m
        self.prior_upright_m = prior_upright_m
        self.lookback_s = lookback_s
        self.reset_all()

    def reset_all(self):
        self.reset_stream()

    def reset_stream(self, reason=""):
        self.last_window_us = None
        self.last_ml_score = None
        self.current_slot = None
        self.last_t_us = None
        self.z_buf = []
        self.recent_points = []
        self.state = "MONITORING"
        self.fall_candidate = None

    def update(self, t_us: int, active_targets: list[dict], backlog_ms: float = 0.0) -> tuple[dict, dict | None]:
        """
        active_targets: list of active dicts: [{'slot': 1, 'x_mm': ..., 'y_mm': ..., 'v_mps': ...}]
        Returns:
            (status_summary: dict, alarm_info: dict | None)
        """
        alarm_info = None

        # Rule 1: Exclude frames with backlog > 500ms
        if backlog_ms > MAX_BACKLOG_MS:
            self.reset_stream(reason="backlog_exceeded")
            return self.get_summary(t_us, None, 0, 0, 0, 0, note="BACKLOG_EXCEEDED"), None

        # Rule 2: Single target only
        if len(active_targets) != 1:
            reason = "NO_TARGET" if len(active_targets) == 0 else f"MULTI_TARGET_{len(active_targets)}"
            self.reset_stream(reason=reason)
            return self.get_summary(t_us, None, 0, 0, 0, 0, note=reason), None

        tgt = active_targets[0]
        slot = tgt['slot']
        x_mm = float(tgt['x_mm'])
        y_mm = float(tgt['y_mm'])
        v_signed = float(tgt['v_mps'])
        v_mps = abs(v_signed)
        z_raw = (self.h_mount - x_mm) / 1000.0

        # Rule 3: Check time gap (> 0.35s) or slot change
        if self.last_t_us is not None:
            dt_s = (t_us - self.last_t_us) / 1e6
            if dt_s <= 0 or dt_s > 0.35 or slot != self.current_slot:
                self.reset_stream(reason="slot_change_or_gap")

        self.current_slot = slot
        self.last_t_us = t_us

        # Rolling 3-point median on Z
        self.z_buf.append(z_raw)
        if len(self.z_buf) > 3:
            self.z_buf.pop(0)
        zs = statistics.median(self.z_buf)

        t_s = t_us / 1e6
        self.recent_points.append({'t_s': t_s, 't_us': t_us, 'zs': zs, 'v': v_mps,
                                   'v_signed': v_signed, 'x_mm': x_mm,
                                   'slot': slot, 'y_mm': y_mm})
        # Keep buffer up to 15 seconds
        if len(self.recent_points) > 180:
            self.recent_points.pop(0)

        # Keep scoring at a consistent cadence through every FSM state.
        ml_score = self.score_window(t_us) if self.window_score is not None else None

        # FSM State Transitions
        if self.state == "MONITORING":
            if self.window_score is not None:
                if ml_score is not None and ml_score >= self.ml_threshold and zs < self.low_hold_floor_m:
                    self.state = "SUSPECTED_FALL"
                    self.fall_candidate = {
                        'impact_t_s': t_s,
                        'v_peak': max(point['v'] for point in self.recent_points
                                      if point['t_us'] >= t_us - WINDOW_US),
                        'drop_rate': None,
                        'slot': slot,
                        'ml_score': ml_score,
                    }
            elif zs < self.trigger_floor_m:
                # Look back up to 1.25s for upright posture zs >= 0.90m within same unbroken stream
                onset = None
                for p in reversed(self.recent_points[:-1]):
                    if t_s - p['t_s'] > self.lookback_s:
                        break
                    if p['zs'] >= self.prior_upright_m:
                        onset = p
                        break
                if onset is not None:
                    # Check descent parameters
                    pts_descent = [p for p in self.recent_points if onset['t_s'] - 0.25 <= p['t_s'] <= t_s + 0.40]
                    v_peak = max(p['v'] for p in pts_descent)
                    dz = onset['zs'] - zs
                    dt = max(0.09, t_s - onset['t_s'])
                    drop_rate = dz / dt
                    if v_peak >= self.v_thresh and dz >= self.min_drop_m:
                        self.state = "SUSPECTED_FALL"
                        self.fall_candidate = {
                            'onset_t_s': onset['t_s'],
                            'impact_t_s': t_s,
                            'impact_t_us': t_us,
                            'v_peak': v_peak,
                            'drop_rate': drop_rate,
                            'slot': slot
                        }

        elif self.state == "SUSPECTED_FALL":
            # Must stay on the floor (zs < 0.48m) without standing up
            if zs >= self.low_hold_floor_m:
                # Stood up or posture recovered before hold time -> Cancel candidate
                self.state = "MONITORING"
                self.fall_candidate = None
            else:
                immobility_dur = t_s - self.fall_candidate['impact_t_s']
                if immobility_dur >= self.hold_s:
                    self.state = "ALARM_TRIGGERED"
                    alarm_info = {
                        'status': 'ALARM_TRIGGERED',
                        'impact_time_s': round(self.fall_candidate['impact_t_s'], 2),
                        'alarm_time_s': round(t_s, 2),
                        'latency_s': round(immobility_dur, 2),
                        'v_peak_mps': round(self.fall_candidate['v_peak'], 2),
                        'drop_rate_mps': (round(self.fall_candidate['drop_rate'], 2)
                                          if self.fall_candidate['drop_rate'] is not None else None),
                        'z_floor_m': round(zs, 3),
                        'slot': self.fall_candidate['slot']
                    }
                    if 'ml_score' in self.fall_candidate:
                        alarm_info['ml_score'] = round(self.fall_candidate['ml_score'], 3)

        elif self.state == "ALARM_TRIGGERED":
            # Wait until person stands back up (zs >= 0.55m) to re-arm detector
            if zs >= self.rearm_height_m:
                self.state = "MONITORING"
                self.fall_candidate = None

        summary = self.get_summary(t_us, slot, x_mm, y_mm, zs, v_mps)
        return summary, alarm_info

    def score_window(self, t_us):
        if self.last_window_us is not None and t_us - self.last_window_us < STEP_US:
            return None
        features = extract_features(self.recent_points, t_us, self.feature_set)
        if features is None:
            return None
        self.last_window_us = t_us
        self.last_ml_score = float(self.window_score(t_us, features))
        return self.last_ml_score

    def get_summary(self, t_us: int, slot: int | None, x_mm: float, y_mm: float, z_est: float, v_mps: float, note: str = "") -> dict:
        t_s = t_us / 1e6
        hold_time = 0.0
        if self.state == "SUSPECTED_FALL" and self.fall_candidate:
            hold_time = max(0.0, t_s - self.fall_candidate['impact_t_s'])
        return {
            't_s': round(t_s, 2),
            'slot': slot,
            'x_mm': round(x_mm, 1),
            'y_mm': round(y_mm, 1),
            'z_est_m': round(z_est, 3),
            'v_mps': round(v_mps, 2),
            'state': self.state,
            'hold_time_s': round(hold_time, 1),
            'note': note,
            'detector_mode': 'ML_2S_FSM' if self.window_score is not None else 'FSM',
            'feature_count': len(FEATURE_SETS[self.feature_set]) if self.window_score is not None else 0,
            'ml_score': round(self.last_ml_score, 3) if self.last_ml_score is not None else None,
        }


class MultiTargetFallDetector:
    """Run the same detector independently for each of the three LD2450 slots."""

    STATE_PRIORITY = {'MONITORING': 0, 'SUSPECTED_FALL': 1, 'ALARM_TRIGGERED': 2}

    def __init__(self, **settings):
        self.detectors = {slot: OnlineFallDetectorFSM(**settings) for slot in (1, 2, 3)}

    def reset_stream(self):
        for detector in self.detectors.values():
            detector.reset_stream()

    def get_summary(self, t_us, note):
        summary = self.detectors[1].get_summary(t_us, None, 0, 0, 0, 0, note=note)
        return {**summary, 'target_states': []}

    def update(self, t_us, active_targets, backlog_ms=0.0):
        if backlog_ms > MAX_BACKLOG_MS:
            self.reset_stream()
            return self.get_summary(t_us, 'BACKLOG_EXCEEDED'), []

        targets_by_slot = {target['slot']: target for target in active_targets}
        states, alarms = [], []
        for slot, detector in self.detectors.items():
            target = targets_by_slot.get(slot)
            if target is None:
                if detector.current_slot is not None:
                    detector.reset_stream()
                continue
            summary, alarm = detector.update(t_us, [target], backlog_ms)
            states.append(summary)
            if alarm is not None:
                alarms.append(alarm)

        if not states:
            return self.get_summary(t_us, 'NO_TARGET'), alarms

        primary = max(states, key=lambda summary: self.STATE_PRIORITY[summary['state']])
        return {**primary, 'target_states': states}, alarms

