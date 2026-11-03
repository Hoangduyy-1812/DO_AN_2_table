"""Create strictly non-overlapping phase labels for LD2450 72 recordings.
Every row in samples.csv receives at most one label; contiguous runs form phase intervals.
Short/ambiguous dips (< 5s in fall/lying scenarios) are marked UNVERIFIED_LOW_DIP rather than FALL/LIE_DOWN.
"""
import os, csv, shutil, statistics

ROOT = r'C:\Users\ADMIN\Downloads\DO_AN_2'
OUT_DIR = os.path.join(ROOT, '04_DA_CHIA_NHAN_GIAI_DOAN')
PER_FILE_DIR = os.path.join(OUT_DIR, 'samples_da_gan_nhan_72_file')
os.makedirs(PER_FILE_DIR, exist_ok=True)

H_MM = 1700.0
MAX_BACKLOG_MS = 500.0
MIN_USABLE_ROWS = 100

def process_trial(folder_path, folder_name, pos, scenario, repeat):
    csv_path = os.path.join(folder_path, 'samples.csv')
    with open(csv_path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    n_total = len(rows)
    row_labels = [''] * n_total
    row_z = [''] * n_total
    row_slot = [0] * n_total

    # Step 1: Identify usable single-target fresh frames
    valid_indices = []
    for idx, r in enumerate(rows):
        b = float(r['backlog_ms'] or 0)
        ac = int(r['active_count'])
        if b > MAX_BACKLOG_MS:
            row_labels[idx] = 'IGNORE_BACKLOG'
        elif ac == 0:
            row_labels[idx] = 'NO_TARGET'
        elif ac > 1:
            row_labels[idx] = 'IGNORE_MULTI_TARGET'
        else:
            for s in (1, 2, 3):
                if r[f't{s}_active'] == '1':
                    x_mm = float(r[f't{s}_x_mm'])
                    z_m = (H_MM - x_mm) / 1000.0
                    row_z[idx] = round(z_m, 3)
                    row_slot[idx] = s
                    valid_indices.append(idx)
                    break

    usable_count = len(valid_indices)
    if usable_count < MIN_USABLE_ROWS:
        for idx in valid_indices:
            row_labels[idx] = 'EXCLUDED_INSUFFICIENT_USABLE_ROWS'
        return [], {
            'folder': folder_name, 'position': pos, 'trial_descriptor': scenario, 'repeat': repeat,
            'total_rows': n_total, 'usable_rows': usable_count,
            'reason': f'Fewer than {MIN_USABLE_ROWS} unambiguous fresh rows (usable={usable_count})'
        }, rows, row_z, row_labels

    t0_us = int(rows[valid_indices[0]]['t_us'])

    # Build valid frame sequence
    pts = []
    for idx in valid_indices:
        r = rows[idx]
        s = row_slot[idx]
        t_us = int(r['t_us'])
        pts.append({
            'row_idx': idx,
            'seq': int(r['seq']),
            't_us': t_us,
            't_s': (t_us - t0_us) / 1e6,
            'slot': s,
            'z': float(row_z[idx]),
            'v': abs(float(r[f't{s}_speed_cms'])) / 100.0,
            'label': 'STAND',
            'verif': 'auto_segmented_needs_visual_check'
        })

    # Split into contiguous valid segments (no time gap > 0.35s, same slot)
    segs = [[pts[0]]]
    for a, b in zip(pts, pts[1:]):
        if (b['t_us'] - a['t_us']) / 1e6 > 0.35 or b['slot'] != a['slot']:
            segs.append([])
        segs[-1].append(b)

    for seg in segs:
        m = len(seg)
        z_raw = [p['z'] for p in seg]
        z_sm = [statistics.median(z_raw[max(0, i-2):min(m, i+3)]) for i in range(m)]
        for p, zs in zip(seg, z_sm):
            p['zs'] = zs

        if scenario == 'dung_yen':
            for p in seg:
                p['label'] = 'STAND'
        elif scenario in ('di_lai', 'di_chuyen'):
            for p in seg:
                p['label'] = 'WALK'
        elif scenario == 'cui_nhat_do':
            for p in seg:
                p['label'] = 'STAND'
            # Find contiguous runs where zs < 0.90m
            i = 0
            while i < m:
                if seg[i]['zs'] < 0.90:
                    j = i
                    while j < m and seg[j]['zs'] < 0.90:
                        j += 1
                    # Expand slightly up to 0.35s on each side where zs < 1.05m for the bend transition
                    a = i
                    while a > 0 and (seg[i]['t_s'] - seg[a-1]['t_s']) <= 0.35 and seg[a-1]['zs'] < 1.05:
                        a -= 1
                    b = j - 1
                    while b < m - 1 and (seg[b+1]['t_s'] - seg[j-1]['t_s']) <= 0.35 and seg[b+1]['zs'] < 1.05:
                        b += 1
                    dur = seg[b]['t_s'] - seg[a]['t_s']
                    lbl = 'BEND' if dur <= 4.5 else 'UNVERIFIED_LOW_DIP'
                    ver = 'auto_candidate_bend' if lbl == 'BEND' else 'needs_review_long_low_in_bend_file'
                    for k in range(a, b + 1):
                        seg[k]['label'] = lbl
                        seg[k]['verif'] = ver
                    i = b + 1
                else:
                    i += 1
        elif scenario in ('dung_ngoi', 'dung_ngoi_nhanh'):
            TH = 0.92
            base = ['STAND' if p['zs'] >= TH else 'SIT' for p in seg]
            for i, p in enumerate(seg):
                p['label'] = base[i]
            # Mark transition frames within 0.45s of each state change
            changes = [i for i in range(1, m) if base[i] != base[i-1]]
            for c in changes:
                tr_lbl = 'SIT_DOWN' if base[c] == 'SIT' else 'STAND_UP'
                t_c = seg[c]['t_s']
                for k in range(max(0, c - 5), min(m, c + 5)):
                    if abs(seg[k]['t_s'] - t_c) <= 0.45:
                        seg[k]['label'] = tr_lbl
        elif scenario in ('ngoi_xom', 'nam_chu_dong', 'nga_mo_phong'):
            TH_LOW = 0.55 if scenario == 'ngoi_xom' else 0.45
            MIN_HOLD_S = 2.0 if scenario == 'ngoi_xom' else 5.0
            down_lbl = {'ngoi_xom': 'SQUAT_DOWN', 'nam_chu_dong': 'LIE_DOWN', 'nga_mo_phong': 'FALL'}[scenario]
            hold_lbl = {'ngoi_xom': 'SQUAT', 'nam_chu_dong': 'LYING', 'nga_mo_phong': 'LYING_POST_FALL'}[scenario]

            for p in seg:
                p['label'] = 'STAND'

            # Find low regions where zs < TH_LOW (bridging tiny 1-2 frame spikes <= 0.25s)
            low_mask = [p['zs'] < TH_LOW for p in seg]
            for k in range(1, m - 1):
                if not low_mask[k] and low_mask[k-1] and low_mask[k+1]:
                    low_mask[k] = True

            i = 0
            while i < m:
                if low_mask[i]:
                    j = i
                    while j < m and low_mask[j]:
                        j += 1
                    low_dur = seg[j-1]['t_s'] - seg[i]['t_s']
                    if low_dur < MIN_HOLD_S:
                        # Short dip or edge artifact (e.g., 32-33s and 38-39s in C_nga_mo_phong_03)
                        for k in range(i, j):
                            seg[k]['label'] = 'UNVERIFIED_LOW_DIP'
                            seg[k]['verif'] = f'needs_review_short_dip_{low_dur:.1f}s'
                    else:
                        # Valid low hold; find preceding descent window (up to 1.2s before i where zs < 1.0m)
                        d_start = i
                        while d_start > 0 and (seg[i]['t_s'] - seg[d_start-1]['t_s']) <= 1.2 and seg[d_start-1]['zs'] < 1.02 and seg[d_start-1]['label'] == 'STAND':
                            d_start -= 1
                        # Include first few frames of settling (up to 0.35s after i) in the descent phase
                        d_end = i
                        while d_end < j - 1 and (seg[d_end]['t_s'] - seg[i]['t_s']) <= 0.35 and seg[d_end]['v'] > 0.16:
                            d_end += 1

                        if d_start < i or d_end > i:
                            v_pk_desc = max(seg[k]['v'] for k in range(d_start, d_end + 1))
                            ver_desc = 'auto_candidate_verified_cycle'
                            if scenario == 'nga_mo_phong' and v_pk_desc < 0.50:
                                ver_desc = f'needs_review_low_vpeak_{v_pk_desc:.2f}mps'
                            for k in range(d_start, d_end + 1):
                                seg[k]['label'] = down_lbl
                                seg[k]['verif'] = ver_desc
                            hold_start = d_end + 1
                        else:
                            # Segment started already on the floor (after a gap or at t=0)
                            hold_start = i

                        for k in range(hold_start, j):
                            seg[k]['label'] = hold_lbl
                            seg[k]['verif'] = 'auto_candidate_verified_cycle' if d_start < i else 'needs_review_started_low_after_gap'

                        # Recovery STAND_UP phase after j-1 (up to 1.2s while zs < 1.0m)
                        if j < m:
                            r_end = j
                            while r_end < m - 1 and (seg[r_end]['t_s'] - seg[j]['t_s']) <= 1.2 and seg[r_end]['zs'] < 1.02:
                                r_end += 1
                            for k in range(j, r_end + 1):
                                seg[k]['label'] = 'STAND_UP'
                                seg[k]['verif'] = 'auto_candidate_verified_cycle'
                            i = r_end + 1
                            continue
                    i = j
                else:
                    i += 1

        # Copy frame labels back to row_labels
        for p in seg:
            row_labels[p['row_idx']] = p['label']

    # Step 2: Group strictly contiguous valid frames with identical label into non-overlapping phase intervals
    phases = []
    for seg in segs:
        if not seg:
            continue
        runs = [[seg[0]]]
        for a, b in zip(seg, seg[1:]):
            if b['label'] != a['label']:
                runs.append([])
            runs[-1].append(b)
        for run in runs:
            dur = (run[-1]['t_us'] - run[0]['t_us']) / 1e6
            zs = [p['z'] for p in run]
            vs = [p['v'] for p in run]
            phases.append({
                'folder': folder_name,
                'position': pos,
                'trial_descriptor': scenario,
                'repeat': repeat,
                'start_row': run[0]['row_idx'],
                'end_row': run[-1]['row_idx'],
                'frame_count': len(run),
                'start_t_us': run[0]['t_us'],
                'end_t_us': run[-1]['t_us'],
                'start_s': round(run[0]['t_s'], 2),
                'end_s': round(run[-1]['t_s'], 2),
                'duration_s': round(dur, 2),
                'activity_label': run[0]['label'],
                'z_start_m': round(zs[0], 3),
                'z_end_m': round(zs[-1], 3),
                'z_med_m': round(statistics.median(zs), 3),
                'v_peak_mps': round(max(vs), 2),
                'verification_status': run[0]['verif'],
                'ground_truth_source': 'signal_segmented_within_known_scenario',
                'target_assignment': f"slot_{run[0]['slot']}_single_active"
            })

    return phases, None, rows, row_z, row_labels

def main():
    all_phases = []
    excluded = []
    for pos in ('A', 'B', 'C'):
        dpath = os.path.join(ROOT, f'{pos}_direction')
        for fo in sorted(os.listdir(dpath)):
            fpath = os.path.join(dpath, fo)
            if not os.path.isdir(fpath):
                continue
            rep = int(fo[-2:])
            scen = fo[2:-3].replace('di_chuyen', 'di_lai')
            phs, exc, rows, row_z, row_labels = process_trial(fpath, fo, pos, scen, rep)
            if exc is not None:
                excluded.append(exc)
            else:
                all_phases.extend(phs)

            # Write per-row labeled CSV
            out_cols = list(rows[0].keys()) + ['z_hat_m', 'phase_label']
            for idx, r in enumerate(rows):
                r['z_hat_m'] = row_z[idx]
                r['phase_label'] = row_labels[idx]
            with open(os.path.join(PER_FILE_DIR, f'{fo}_labeled.csv'), 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=out_cols)
                w.writeheader()
                w.writerows(rows)

    # Verify ZERO overlaps
    by_fo = {}
    for p in all_phases:
        by_fo.setdefault(p['folder'], []).append(p)
    overlaps = 0
    for fo, ps in by_fo.items():
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                if int(ps[i]['start_t_us']) <= int(ps[j]['end_t_us']) and int(ps[j]['start_t_us']) <= int(ps[i]['end_t_us']):
                    overlaps += 1
    assert overlaps == 0, f"Found {overlaps} overlaps!"

    fieldnames = list(all_phases[0].keys())
    full_path = os.path.join(OUT_DIR, '01_tong_hop_949_doan_nhan_71_file.csv')
    with open(full_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_phases)
    shutil.copy2(full_path, os.path.join(ROOT, 'phase_labels_auto_segmented.csv'))

    with open(os.path.join(OUT_DIR, '02_nhan_giai_doan_TRAIN_01_02.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows([p for p in all_phases if int(p['repeat']) in (1, 2)])

    with open(os.path.join(OUT_DIR, '03_nhan_giai_doan_TEST_03.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows([p for p in all_phases if int(p['repeat']) == 3])

    with open(os.path.join(OUT_DIR, '04_file_bi_loai_thieu_khung.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['folder','position','trial_descriptor','repeat','total_rows','usable_rows','reason'])
        w.writeheader()
        w.writerows(excluded)

    print(f"Total phases: {len(all_phases)} | Overlapping pairs: {overlaps} | Excluded files: {len(excluded)}")
    counts = {}
    for p in all_phases:
        k = p['activity_label']
        counts[k] = counts.get(k, 0) + 1
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:22}: {v:4d}")

    print("\nC_nga_mo_phong_03 updated phases:")
    for p in by_fo['C_nga_mo_phong_03']:
        print(f"  {p['start_s']:>6}s..{p['end_s']:>6}s ({p['duration_s']:>5}s) | {p['activity_label']:20} | v_pk={p['v_peak_mps']:>4} | {p['verification_status']}")

if __name__ == '__main__':
    main()
