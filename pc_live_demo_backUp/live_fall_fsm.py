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
import time, statistics

class OnlineFallDetectorFSM:
    def __init__(self, h_mount_mm=1700.0, v_thresh=0.78, hold_s=8.0):
        self.h_mount = h_mount_mm
        self.v_thresh = v_thresh
        self.hold_s = hold_s
        self.reset_all()

    def reset_all(self):
        self.current_slot = None
        self.last_t_us = None
        self.z_buf = [] # rolling 3-pt median
        self.recent_points = [] # list of (t_s, zs, v, slot)
        self.state = "MONITORING" # "MONITORING", "SUSPECTED_FALL", "ALARM_TRIGGERED"
        self.fall_candidate = None # dict of candidate descent

    def reset_stream(self, reason=""):
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
        if backlog_ms > 500.0:
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
        v_mps = abs(float(tgt['v_mps']))
        z_raw = (self.h_mount - x_mm) / 1000.0

        # Rule 3: Check time gap (> 0.35s) or slot change
        if self.last_t_us is not None:
            dt_s = (t_us - self.last_t_us) / 1e6
            if dt_s > 0.35 or slot != self.current_slot:
                self.reset_stream(reason="slot_change_or_gap")

        self.current_slot = slot
        self.last_t_us = t_us

        # Rolling 3-point median on Z
        self.z_buf.append(z_raw)
        if len(self.z_buf) > 3:
            self.z_buf.pop(0)
        zs = statistics.median(self.z_buf)

        t_s = t_us / 1e6
        self.recent_points.append({'t_s': t_s, 't_us': t_us, 'zs': zs, 'v': v_mps, 'slot': slot})
        # Keep buffer up to 15 seconds
        if len(self.recent_points) > 180:
            self.recent_points.pop(0)

        # FSM State Transitions
        if self.state == "MONITORING":
            if zs < 0.40:
                # Look back up to 1.25s for upright posture zs >= 0.90m within same unbroken stream
                onset = None
                for p in reversed(self.recent_points[:-1]):
                    if t_s - p['t_s'] > 1.25:
                        break
                    if p['zs'] >= 0.90:
                        onset = p
                        break
                if onset is not None:
                    # Check descent parameters
                    pts_descent = [p for p in self.recent_points if onset['t_s'] - 0.25 <= p['t_s'] <= t_s + 0.40]
                    v_peak = max(p['v'] for p in pts_descent)
                    dz = onset['zs'] - zs
                    dt = max(0.09, t_s - onset['t_s'])
                    drop_rate = dz / dt
                    if v_peak >= self.v_thresh and dz >= 0.50:
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
            if zs >= 0.48:
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
                        'drop_rate_mps': round(self.fall_candidate['drop_rate'], 2),
                        'z_floor_m': round(zs, 3),
                        'slot': self.fall_candidate['slot']
                    }

        elif self.state == "ALARM_TRIGGERED":
            # Wait until person stands back up (zs >= 0.55m) to re-arm detector
            if zs >= 0.55:
                self.state = "MONITORING"
                self.fall_candidate = None

        summary = self.get_summary(t_us, slot, x_mm, y_mm, zs, v_mps)
        return summary, alarm_info

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
            'note': note
        }

