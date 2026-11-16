"""Instantiate the rule FSM with the exact parameters saved by calibration."""
import json
from pathlib import Path

from live_fall_fsm import MultiTargetFallDetector, OnlineFallDetectorFSM


def load_settings(path):
    settings=json.loads(Path(path).read_text(encoding='utf-8'))
    expected={'h_mount_mm','hold_s','v_thresh','min_drop_m','trigger_floor_m',
              'low_hold_floor_m','rearm_height_m','prior_upright_m','lookback_s'}
    if set(settings)!=expected:
        raise ValueError('Config keys do not match this calibrated rule FSM.')
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) for v in settings.values()):
        raise ValueError('All settings must be numeric.')
    if settings['h_mount_mm']!=1700 or settings['hold_s']!=8:
        raise ValueError('This calibration is for 1.7m and an 8s alarm hold.')
    if not (0<settings['trigger_floor_m']<=settings['low_hold_floor_m']
            <settings['rearm_height_m']<settings['prior_upright_m']):
        raise ValueError('Height thresholds violate the required ordering.')
    if min(settings['v_thresh'],settings['min_drop_m'],settings['lookback_s'])<=0:
        raise ValueError('Speed/drop/lookback must be positive.')
    return settings


def build_detector(path, multiple_slots=True):
    settings=load_settings(path)
    return (MultiTargetFallDetector if multiple_slots else OnlineFallDetectorFSM)(**settings)
