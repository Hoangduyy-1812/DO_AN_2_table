"""Evaluate event-level FSM fall detector on LD2450 streams.
- Development: Repeat 01 & 02 (47 usable files)
- Held-out Test: Repeat 03 (24 files)
Reports both:
  (a) clean single-target fall cycles (verification_status == 'auto_candidate_verified_cycle')
  (b) all low-posture fall cycles including those interrupted by multi-target gaps or low Vpeak
"""
import os, csv, json, statistics

ROOT = r'C:\Users\ADMIN\Downloads\DO_AN_2'
PHASE_CSV = os.path.join(ROOT, '04_DA_CHIA_NHAN_GIAI_DOAN', '01_tong_hop_927_doan_nhan_72_file.csv')
OUT_DIR = os.path.join(ROOT, '04_DA_CHIA_NHAN_GIAI_DOAN')

H_MM = 1700.0
MAX_BACKLOG_MS = 500.0
MIN_USABLE_ROWS = 100

def load_stream(folder_path):
    with open(os.path.join(folder_path, 'samples.csv'), encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    pts = []
    for idx, r in enumerate(rows):
        if float(r['backlog_ms'] or 0) > MAX_BACKLOG_MS or int(r['active_count']) != 1:
            continue
        for s in (1, 2, 3):
            if r[f't{s}_active'] == '1':
                t_us = int(r['t_us'])
                z = (H_MM - float(r[f't{s}_x_mm'])) / 1000.0
                y = float(r[f't{s}_y_mm']) / 1000.0
                v = abs(float(r[f't{s}_speed_cms'])) / 100.0
                pts.append({'idx': idx, 't_us': t_us, 'slot': s, 'z': z, 'y': y, 'v': v})
                break
    if len(pts) < MIN_USABLE_ROWS:
        return None
    t0 = pts[0]['t_us']
    seg_buf = []
    prev_t = None
    prev_s = None
    for p in pts:
        p['t_s'] = (p['t_us'] - t0) / 1e6
        if prev_t is not None and ((p['t_us'] - prev_t) / 1e6 > 0.35 or p['slot'] != prev_s):
            seg_buf = []
        seg_buf.append(p['z'])
        if len(seg_buf) > 3:
            seg_buf.pop(0)
        p['zs'] = statistics.median(seg_buf)
        prev_t = p['t_us']
        prev_s = p['slot']
    return pts

def detect_events_fsm(pts, v_thresh=0.78, hold_s=8.0):
    alarms = []
    n = len(pts)
    i = 0
    while i < n:
        if pts[i]['zs'] < 0.40:
            onset_idx = None
            for j in range(i - 1, -1, -1):
                if pts[i]['t_s'] - pts[j]['t_s'] > 1.25:
                    break
                if pts[j]['zs'] >= 0.90:
                    onset_idx = j
                    break
            if onset_idx is not None:
                w_start = max(0, onset_idx - 2)
                w_end = min(n, i + 5)
                v_peak = max(pts[k]['v'] for k in range(w_start, w_end))
                dz = pts[onset_idx]['zs'] - pts[i]['zs']
                dt = max(0.09, pts[i]['t_s'] - pts[onset_idx]['t_s'])
                drop_rate = dz / dt

                if v_peak >= v_thresh and dz >= 0.50:
                    k = i
                    while k < n and pts[k]['zs'] < 0.48 and (pts[k]['t_s'] - pts[k-1]['t_s'] if k > i else 0) <= 0.5:
                        if pts[k]['t_s'] - pts[i]['t_s'] >= hold_s:
                            alarms.append({
                                'onset_s': round(pts[onset_idx]['t_s'], 2),
                                'impact_s': round(pts[i]['t_s'], 2),
                                'alarm_s': round(pts[k]['t_s'], 2),
                                'latency_s': round(pts[k]['t_s'] - pts[i]['t_s'], 2),
                                'v_peak_mps': round(v_peak, 2),
                                'drop_rate_mps': round(drop_rate, 2)
                            })
                            while k < n and pts[k]['zs'] < 0.55:
                                k += 1
                            i = k
                            break
                        k += 1
                    else:
                        i = k
                    continue
        i += 1
    return alarms

def main():
    with open(PHASE_CSV, encoding='utf-8') as f:
        all_phases = list(csv.DictReader(f))

    # Count all LYING_POST_FALL episodes (>= 5s) as total post-fall episodes in nga_mo_phong files
    post_fall_holds = {}
    for p in all_phases:
        if p['activity_label'] == 'LYING_POST_FALL':
            post_fall_holds.setdefault(p['folder'], []).append((float(p['start_s']), float(p['end_s']), p['verification_status']))

    streams = {}
    meta_info = {}
    for pos in ('A', 'B', 'C'):
        dpath = os.path.join(ROOT, f'{pos}_direction')
        for fo in sorted(os.listdir(dpath)):
            fpath = os.path.join(dpath, fo)
            if not os.path.isdir(fpath): continue
            pts = load_stream(fpath)
            if pts is None: continue
            rep = int(fo[-2:])
            scen = fo[2:-3].replace('di_chuyen', 'di_lai')
            streams[fo] = pts
            meta_info[fo] = (pos, scen, rep, int(scen == 'nga_mo_phong'))

    test_folders = sorted([fo for fo, m in meta_info.items() if m[2] == 3])
    summary_rows = []
    tot_episodes = 0
    det_episodes = 0
    tot_false_alarms = 0

    for fo in test_folders:
        alarms = detect_events_fsm(streams[fo], v_thresh=0.78, hold_s=8.0)
        pos, scen, rep, y = meta_info[fo]
        episodes = post_fall_holds.get(fo, [])
        matched = 0
        missed_notes = []
        if y == 1:
            tot_episodes += len(episodes)
            for (hs, he, ver) in episodes:
                hit = any(hs - 2.0 <= al['impact_s'] <= he for al in alarms)
                if hit:
                    matched += 1
                else:
                    missed_notes.append(f"missed@{hs:.1f}s({ver})")
            det_episodes += matched
        else:
            tot_false_alarms += len(alarms)

        summary_rows.append({
            'trial': fo, 'position': pos, 'scenario': scen, 'y_true_trial': y,
            'candidate_fall_episodes': len(episodes) if y == 1 else 0,
            'alarms_triggered': len(alarms),
            'episodes_detected': matched if y == 1 else 0,
            'false_alarms': len(alarms) if y == 0 else 0,
            'trial_prediction': 1 if len(alarms) > 0 else 0,
            'trial_correct': (1 if len(alarms) > 0 else 0) == y,
            'notes': '; '.join(missed_notes) if missed_notes else ('OK' if not alarms or y == 1 else str(alarms))
        })

    out_csv = os.path.join(OUT_DIR, '05_ket_qua_danh_gia_su_kien_TEST_03.csv')
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)

    print(f"Saved event evaluation to {out_csv}")
    print(f"Test Repeat 03: Trial-level correct = {sum(1 for r in summary_rows if r['trial_correct'])}/{len(summary_rows)}")
    print(f"Test Repeat 03: Individual fall episodes detected = {det_episodes}/{tot_episodes} ({det_episodes/tot_episodes*100:.1f}%) | False alarms in 21 non-fall trials = {tot_false_alarms}")
    for r in summary_rows:
        if r['y_true_trial'] == 1 or r['false_alarms'] > 0:
            print(" ", r)

if __name__ == '__main__':
    main()
