"""Train on repeats 01/02 and replay repeat 03 through the live detector."""
import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import json
import platform
from pathlib import Path
from statistics import mean, median

import joblib
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from fall_window import FEATURE_SETS, WINDOW_US
from live_fall_fsm import OnlineFallDetectorFSM

PHASE_DIR = "04_DA_CHIA_NHAN_GIAI_DOAN"
LABEL_FILE = "01_tong_hop_949_doan_nhan_71_file.csv"
THRESHOLDS = tuple(i / 20 for i in range(4, 19))
SVM_THRESHOLDS = tuple(i / 5 for i in range(-7, 8))
H_MOUNT_MM = 1700.0


@dataclass
class Trial:
    name: str
    repeat: int
    frames: list
    events: list
    windows: dict
    labels: dict
    feature_set: str


def read_frames(path):
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            targets = [
                dict(slot=slot, x_mm=int(row[f"t{slot}_x_mm"]),
                     y_mm=int(row[f"t{slot}_y_mm"]), v_mps=int(row[f"t{slot}_speed_cms"]) / 100)
                for slot in (1, 2, 3) if row[f"t{slot}_active"] == "1"
            ]
            yield int(row["t_us"]), targets, float(row["backlog_ms"] or 0)


def phases_by_trial(root):
    grouped = defaultdict(list)
    with (root / PHASE_DIR / LABEL_FILE).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            grouped[row["folder"]].append((
                row["activity_label"], int(row["start_t_us"]), int(row["end_t_us"]),
                row["verification_status"],
            ))
    return grouped


def label_window(t_us, phases):
    for kind, start, end, status in phases:
        uncertain = kind == "UNVERIFIED_LOW_DIP" or (
            kind in {"FALL", "LYING_POST_FALL"} and status.startswith("needs_review")
        )
        if uncertain and start - 250_000 <= t_us <= min(end, start + 2_000_000) + 500_000:
            return None
    for kind, start, end, _ in phases:
        if kind != "FALL":
            continue
        # Label the current descent and the early samples after it. A stale
        # fall anywhere in a 2 s window does not make the window positive.
        first_positive = start + (end - start) // 2
        if first_positive <= t_us <= end + 550_000:
            return 1
        if start <= t_us < first_positive:
            return None
    return 0


def collect_trial(name, phases, frames, feature_set="6"):
    windows = {}

    def capture(t_us, features):
        windows[t_us] = features
        return 0.0

    detector = OnlineFallDetectorFSM(h_mount_mm=H_MOUNT_MM, window_score=capture,
                                     feature_set=feature_set)
    for t_us, targets, backlog in frames:
        detector.update(t_us, targets, backlog)
    events = [(start, end, status) for kind, start, end, status in phases
              if kind == "LYING_POST_FALL"]
    repeat = int(name.rsplit("_", 1)[-1])
    labels = {t_us: label_window(t_us, phases) for t_us in windows} if repeat != 3 else {}
    return Trial(name, repeat, frames, events, windows, labels, feature_set)


def load_trials(root, feature_set="6"):
    phases = phases_by_trial(root)
    trials = []
    for position in ("A", "B", "C"):
        for file in sorted((root / f"{position}_direction").glob("*/samples.csv")):
            name = file.parent.name
            if name in phases:
                trials.append(collect_trial(name, phases[name], list(read_frames(file)), feature_set))
    if len(trials) != 71 or sum(trial.repeat == 3 for trial in trials) != 24:
        raise ValueError("Expected 71 labeled trials with 24 trials in repeat 03.")
    return trials


def fit(trials, classifier="rf"):
    x, y = [], []
    for trial in trials:
        for t_us, label in trial.labels.items():
            if label is not None:
                x.append(trial.windows[t_us])
                y.append(label)
    if classifier == "svm":
        model = make_pipeline(
            StandardScaler(),
            SVC(kernel="rbf", C=1.0, gamma="scale", class_weight="balanced"),
        )
    else:
        model = RandomForestClassifier(
            n_estimators=100, max_depth=7, min_samples_leaf=3,
            class_weight="balanced", random_state=24, n_jobs=1,
        )
    model.fit(x, y)
    return model, dict(Counter(y))


def scores_for(model, trial, classifier="rf"):
    if not trial.windows:
        return {}
    windows = list(trial.windows.values())
    scores = (model.decision_function(windows) if classifier == "svm"
              else model.predict_proba(windows)[:, 1])
    return dict(zip(trial.windows, map(float, scores)))


def replay(trial, scores=None, threshold=0.5):
    score_window = None if scores is None else lambda t_us, features: scores[t_us]
    detector = OnlineFallDetectorFSM(
        h_mount_mm=H_MOUNT_MM, window_score=score_window, ml_threshold=threshold,
        feature_set=trial.feature_set,
    )
    alarms = []
    for t_us, targets, backlog in trial.frames:
        _, alarm = detector.update(t_us, targets, backlog)
        if alarm:
            alarms.append((detector.fall_candidate["impact_t_s"], t_us / 1_000_000))
    return alarms


def match(trial, alarms):
    unmatched = list(trial.events)
    delays, suspicion_delays = [], []
    for suspect_s, alarm_s in alarms:
        for event in unmatched:
            start, end, _ = event
            start_s, end_s = start / 1_000_000, end / 1_000_000
            if start_s - 1.5 <= suspect_s <= start_s + 2.5 and alarm_s <= end_s:
                unmatched.remove(event)
                delays.append(round(alarm_s - start_s, 3))
                suspicion_delays.append(round(suspect_s - start_s, 3))
                break
    return {
        "trial": trial.name,
        "events": len(trial.events),
        "detected": len(delays),
        "false_or_extra_alarms": len(alarms) - len(delays),
        "alarm_latency_s": delays,
        "suspect_latency_s": suspicion_delays,
        "missed_status": [status for _, _, status in unmatched],
    }


def summarize(results):
    total = sum(row["events"] for row in results)
    detected = sum(row["detected"] for row in results)
    false = sum(row["false_or_extra_alarms"] for row in results)
    alarm = [s for row in results for s in row["alarm_latency_s"]]
    suspect = [s for row in results for s in row["suspect_latency_s"]]
    return {
        "events": total, "detected": detected, "false_or_extra_alarms": false,
        "false_alarms_nonfall_trials": sum(row["false_or_extra_alarms"] for row in results
                                         if not row["events"]),
        "nonfall_trials": sum(not row["events"] for row in results),
        "f1_events": 2 * detected / (total + detected + false),
        "mean_alarm_latency_s": round(mean(alarm), 3) if alarm else None,
        "median_suspect_latency_s": round(median(suspect), 3) if suspect else None,
    }


def train_evaluate(trials, classifier, out):
    feature_set = trials[0].feature_set
    if any(trial.feature_set != feature_set for trial in trials):
        raise ValueError("A training run cannot mix feature schemas.")
    features = FEATURE_SETS[feature_set]
    dev = [trial for trial in trials if trial.repeat in (1, 2)]
    test = [trial for trial in trials if trial.repeat == 3]
    cv_scores = {}
    for repeat in (1, 2):
        model, _ = fit([trial for trial in dev if trial.repeat != repeat], classifier)
        for trial in dev:
            if trial.repeat == repeat:
                cv_scores[trial.name] = scores_for(model, trial, classifier)
    cv = {}
    for threshold in (SVM_THRESHOLDS if classifier == "svm" else THRESHOLDS):
        cv[threshold] = summarize([
            match(trial, replay(trial, cv_scores[trial.name], threshold)) for trial in dev
        ])
    threshold = max(cv, key=lambda x: (cv[x]["f1_events"], -cv[x]["false_or_extra_alarms"], x))

    model, training_counts = fit(dev, classifier)
    rule_results = [match(trial, replay(trial)) for trial in test]
    ml_results = [
        match(trial, replay(trial, scores_for(model, trial, classifier), threshold))
        for trial in test
    ]
    metrics = {
        "classifier": classifier,
        "window_s": WINDOW_US / 1_000_000, "training_trials": len(dev), "test_trials": len(test),
        "training_windows_by_label": training_counts, "features": features,
        "feature_set": feature_set,
        "feature_definition": "report6_signed_raw_v1" if feature_set == "6" else "legacy9_v1",
        "python_version": platform.python_version(), "sklearn_version": sklearn.__version__,
        "threshold": threshold, "dev_cv_at_threshold": cv[threshold],
        "test_online_rule_fsm": summarize(rule_results),
        "test_ml_2s_plus_fsm": summarize(ml_results),
        "test_details": {"rule_fsm": rule_results, "ml_2s_fsm": ml_results},
    }
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model, "classifier": classifier, "threshold": threshold, "features": features,
        "feature_set": feature_set, "feature_definition": metrics["feature_definition"],
        "window_us": WINDOW_US, "h_mount_mm": H_MOUNT_MM,
        "sklearn_version": sklearn.__version__,
    }, out / f"fall_{classifier}_{feature_set}f_2s.joblib", compress=3)
    metrics_file = f"metrics_{classifier}_{feature_set}f.json"
    (out / metrics_file).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("models"))
    parser.add_argument("--classifier", choices=("rf", "svm"), default="svm")
    parser.add_argument("--features", choices=("6", "9"), default="6")
    args = parser.parse_args()
    trials = load_trials(args.data_root, args.features)
    metrics = train_evaluate(trials, args.classifier, args.out)
    print(json.dumps({key: value for key, value in metrics.items() if key != "test_details"},
                     indent=2))


if __name__ == "__main__":
    main()
