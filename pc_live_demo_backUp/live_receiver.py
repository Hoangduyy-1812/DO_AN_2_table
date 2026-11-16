#!/usr/bin/env python3
"""Live TCP collector with online Fall Detector FSM.
Usage:
  python live_receiver.py --port 9000 --activity demo_live
"""
from __future__ import annotations
import argparse, csv, json, os, socket, sys, time, datetime as dt
from pathlib import Path

from protocol import COUNTERS, decode_frame, validate_record
from live_fall_fsm import OnlineFallDetectorFSM
import receiver

class LiveDetectorRecorder(receiver.Recorder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.detector = OnlineFallDetectorFSM(h_mount_mm=1700.0, v_thresh=0.78, hold_s=8.0)
        self.alarms_history = []
        self.frame_count = 0
        self.prev_state = "MONITORING"
        self.last_print_t = 0.0

    def record(self, obj: object) -> tuple[str, bool]:
        ack, res = super().record(obj)
        if not res:
            return ack, res
        r = validate_record(obj)
        if r["type"] == "frame":
            self.frame_count += 1
            targets = decode_frame(r["raw_hex"])
            active_list = []
            for i, t in enumerate(targets, 1):
                if t["active"]:
                    active_list.append({
                        'slot': i,
                        'x_mm': t['x_mm'],
                        'y_mm': t['y_mm'],
                        'v_mps': t['speed_cms'] / 100.0
                    })
            backlog_ms = float(r.get("sent_us", r["t_us"]) - r["t_us"]) / 1000.0
            summary, alarm = self.detector.update(r["t_us"], active_list, backlog_ms=backlog_ms)

            # Check state change or periodic update (every 0.5s or 5 frames)
            cur_state = summary['state']
            cur_t = summary['t_s']
            state_changed = (cur_state != self.prev_state)

            if state_changed:
                print(f"\n⚡ [CHUYỂN TRẠNG THÁI FSM] -> {cur_state} (t={cur_t}s, Slot={summary['slot']}, Z_est={summary['z_est_m']}m, V={summary['v_mps']}m/s)")
                self.prev_state = cur_state

            if state_changed or (cur_t - self.last_print_t >= 0.5) or (cur_state == "SUSPECTED_FALL"):
                self.last_print_t = cur_t
                if summary['slot'] is not None:
                    status_str = f"[{cur_state}]"
                    if cur_state == "SUSPECTED_FALL":
                        status_str = f"[{cur_state} (chờ sàn {summary['hold_time_s']}s/8.0s)]"
                    sys.stdout.write(f"\r[T:{cur_t:6.1f}s | F#{self.frame_count:4d}] Slot:{summary['slot']} | (X:{summary['x_mm']:5.0f}mm, Y:{summary['y_mm']:5.0f}mm) | Z_est:{summary['z_est_m']:5.2f}m | V:{summary['v_mps']:4.2f}m/s | FSM: {status_str:35s}")
                    sys.stdout.flush()
                else:
                    sys.stdout.write(f"\r[T:{cur_t:6.1f}s | F#{self.frame_count:4d}] [KHÔNG CÓ MỤC TIÊU DUY NHẤT] Note: {summary['note']:20s} | FSM: [{cur_state:12s}]        ")
                    sys.stdout.flush()

            if alarm:
                self.alarms_history.append(alarm)
                print("\n" + "="*70)
                print(f"🚨 [CẢNH BÁO TÉ NGÃ!] ALARM TRIGGERED!")
                print(f"   Thời điểm rơi: {alarm['impact_time_s']}s | Thời điểm báo: {alarm['alarm_time_s']}s")
                print(f"   Độ trễ xác nhận nằm sàn: {alarm['latency_s']}s")
                print(f"   Vận tốc đỉnh lúc rơi: {alarm['v_peak_mps']} m/s | Cao độ sàn: {alarm['z_floor_m']} m")
                print("="*70 + "\n", flush=True)
                # Beep on terminal (cross-platform ASCII bell)
                sys.stdout.write('\a')
                sys.stdout.flush()
        return ack, res

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--out", type=Path, default=Path("data_live_demo"))
    parser.add_argument("--participant", default="P01")
    parser.add_argument("--trial", default="DEMO_01")
    parser.add_argument("--activity", default="live_trial")
    parser.add_argument("--notes", default="Live session with online FSM fall detector")
    parser.add_argument("--fsync", action="store_true")
    args = parser.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    rec = LiveDetectorRecorder(args.out / f"live_{stamp}", args.participant, args.trial,
                               args.activity, args.notes, args.fsync)
    print("\n" + "="*75)
    print(f"🚀 BẮT ĐẦU CHƯƠNG TRÌNH DEMO THỜI GIAN THỰC (ONLINE FALL DETECTOR)")
    print(f"   Lắng nghe tại: {args.host}:{args.port}")
    print(f"   Thư mục lưu phiên đo: {rec.directory.resolve()}")
    print(f"   Trạng thái FSM: [MONITORING] -> [SUSPECTED_FALL] -> [ALARM_TRIGGERED (8s)]")
    print("="*75 + "\n", flush=True)

    try:
        receiver.serve(args.host, args.port, rec)
    except KeyboardInterrupt:
        print("\n[DỪNG PHIÊN ĐO] Đóng kết nối và lưu dữ liệu.")
    finally:
        rec.close()
        print(f"\nTổng số khung thu: {rec.total} | Tổng số lần báo ngã: {len(rec.alarms_history)}")
        if rec.alarms_history:
            for i, a in enumerate(rec.alarms_history, 1):
                print(f"  Cú ngã #{i}: rơi lúc {a['impact_time_s']}s -> báo chuông lúc {a['alarm_time_s']}s (độ trễ {a['latency_s']}s, V_peak={a['v_peak_mps']}m/s)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

