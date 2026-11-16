"""Compare frozen rule, SVM and OR on repeat 03; no fitting or threshold tuning."""
import argparse
import hashlib
import json
from pathlib import Path
import joblib

from fall_window import feature_set_from_bundle
from live_fall_fsm import OnlineFallDetectorFSM
from train_replay import load_trials, scores_for, match, summarize


def replay_mode(trial, scores, threshold, mode):
    scorer = None if mode == 'rule' else lambda t, f: scores[t]
    detector = OnlineFallDetectorFSM(window_score=scorer, ml_threshold=threshold,
                                    feature_set='6', candidate_mode='or' if mode == 'or' else 'ml')
    alarms, trace = [], []
    for t, targets, backlog in trial.frames:
        status, alarm = detector.update(t, targets, backlog)
        if alarm:
            alarms.append((detector.fall_candidate['impact_t_s'], t / 1e6))
            trace.append(alarm)
    return match(trial, alarms), trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path('results/or_comparison.json'))
    args = parser.parse_args()
    model_path = Path(__file__).parent/'models/fall_svm_6f_2s.joblib'
    bundle = joblib.load(model_path)
    assert feature_set_from_bundle(bundle) == '6' and bundle['classifier'] == 'svm'
    trials = [trial for trial in load_trials(args.data_root, '6') if trial.repeat == 3]
    rows = {mode: [] for mode in ('rule', 'ml', 'or')}
    traces = {mode: {} for mode in rows}
    for trial in trials:
        scores = scores_for(bundle['model'], trial, 'svm')
        for mode in rows:
            result, trace = replay_mode(trial, scores, bundle['threshold'], mode)
            rows[mode].append(result)
            traces[mode][trial.name] = trace
    result = dict(threshold=bundle['threshold'], hold_s=8, window_s=2,
                  model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
                  test_trials=len(trials), summary={m:summarize(r) for m,r in rows.items()},
                  details=rows, alarms=traces,
                  limitations=['Recorded-data replay, not a new live hardware test.',
                               'Same single-target quality filtering and semi-automatic references as the original replay.',
                               'Repeat 03 has been examined previously; not a new blind test.',
                               'Latency reference is the start of LYING_POST_FALL; not the physical start of a fall.'])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
