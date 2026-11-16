#!/usr/bin/env python3
"""TCP collector. Python 3.10+, standard library only. Ctrl+C to finish."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import socket
import sys
import time

from protocol import COUNTERS, MAX_LINE_BYTES, decode_frame, validate_record

BASE_COLUMNS = [
    "pc_time_utc", "pc_monotonic_ns", "device_id", "boot_id", "seq", "t_us", "sent_us",
    "participant", "trial_id", "trial_activity", "active_count", "seq_gap_before",
    "device_dt_ms", "pc_dt_ms", "backlog_ms", *COUNTERS, "last_frame_age_ms", "rssi_dbm",
]
TARGET_COLUMNS = [f"t{i}_{field}" for i in range(1, 4) for field in
                  ("active", "x_mm", "y_mm", "speed_cms", "resolution_mm")]
CSV_COLUMNS = BASE_COLUMNS + TARGET_COLUMNS + ["raw_hex"]


class Recorder:
    """Single writer; dedupe high-water marks per device/boot during this run.

    Firmware uses ordered stop-and-wait, so older/equal seq is a replay. A replay
    with the same last seq but different raw bytes is rejected. Restarting the
    receiver creates a NEW session; dedupe is not persisted across sessions.
    """
    def __init__(self, directory: Path, participant="P01", trial_id="T001",
                 activity="unlabelled", notes="", fsync=False):
        directory.mkdir(parents=True, exist_ok=False)
        self.directory = directory
        self.participant, self.trial_id, self.activity = participant, trial_id, activity
        self.fsync = fsync
        self.raw = (directory / "raw.ndjson").open("x", encoding="utf-8", newline="\n")
        self.csv_file = (directory / "samples.csv").open("x", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.csv_file, fieldnames=CSV_COLUMNS)
        self.writer.writeheader()
        self.csv_file.flush()
        self.last: dict[tuple[str, str], dict] = {}
        self.total = 0
        self.duplicates = 0
        self.gaps = 0
        self.last_frame_monotonic: float | None = None
        self.started = time.monotonic()
        self.latest_status = None
        self.latest_targets = None
        meta = {
            "schema": 1, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "participant": participant, "trial_id": trial_id, "trial_activity": activity,
            "notes": notes, "fsync_each_record": fsync,
            "timestamp_note": "t_us = ESP32 frame reception uptime, not sensor measurement time",
            "label_note": "trial_activity is a trial descriptor, not per-window ground truth",
            "target_note": "t1/t2/t3 are report slots, not guaranteed persistent person identities",
            "format": "LD2450 protocol V1.03, UART 256000 8N1, raw report 30 bytes",
        }
        (directory / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _flush(self):
        self.raw.flush()
        self.csv_file.flush()
        if self.fsync:
            os.fsync(self.raw.fileno())
            os.fsync(self.csv_file.fileno())

    def record(self, obj: object) -> tuple[str, bool]:
        r = validate_record(obj)
        ack = f"ACK {r['boot_id']} {r['seq']}\n"
        key = (r["device_id"], r["boot_id"])
        prev = self.last.get(key)
        if r["type"] == "frame" and prev and r["seq"] <= prev["seq"]:
            if r["seq"] == prev["seq"] and r["raw_hex"].upper() != prev["raw_hex"].upper():
                raise ValueError("same sequence with different raw data")
            self.duplicates += 1
            return ack, False
        if r["type"] == "frame" and prev and r["t_us"] < prev["t_us"]:
            raise ValueError("decreasing device timestamp within boot")
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        mono_ns = time.monotonic_ns()
        envelope = {"pc_time_utc": now, "pc_monotonic_ns": mono_ns, "record": r}
        self.raw.write(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False) + "\n")
        if r["type"] == "status":
            self.latest_status = r
            self._flush()
            return ack, False
        targets = decode_frame(r["raw_hex"])
        gap = r["seq"] - prev["seq"] - 1 if prev else 0
        row = {
            "pc_time_utc": now, "pc_monotonic_ns": mono_ns,
            "participant": self.participant, "trial_id": self.trial_id,
            "trial_activity": self.activity,
            "active_count": sum(t["active"] for t in targets),
            "seq_gap_before": gap,
            "device_dt_ms": (r["t_us"] - prev["t_us"]) / 1000 if prev else "",
            "pc_dt_ms": (mono_ns - prev["pc_monotonic_ns"]) / 1e6 if prev else "",
            "backlog_ms": (r["sent_us"] - r["t_us"]) / 1000,
        }
        for col in ("device_id", "boot_id", "seq", "t_us", "sent_us", *COUNTERS,
                    "last_frame_age_ms", "rssi_dbm", "raw_hex"):
            row[col] = r[col]
        for i, target in enumerate(targets, 1):
            row.update({f"t{i}_{field}": value for field, value in target.items()})
        self.writer.writerow(row)
        self._flush()  # ACK only after both files have been flushed.
        self.last[key] = {**r, "pc_monotonic_ns": mono_ns}
        self.total += 1
        self.gaps += gap
        self.latest_targets = targets
        self.last_frame_monotonic = time.monotonic()
        return ack, True

    def close(self):
        self.raw.close()
        self.csv_file.close()
        summary = {"frames_saved": self.total, "duplicates_ignored": self.duplicates,
                   "sequence_gaps_observed": self.gaps,
                   "elapsed_s": round(time.monotonic() - self.started, 3)}
        (self.directory / "receiver_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")


class LineSession:
    """TCP is a byte stream: preserve partial lines and split coalesced lines."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes, recorder: Recorder) -> list[bytes]:
        self.buffer.extend(data)
        replies = []
        while b"\n" in self.buffer:
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer[:] = remainder
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("line exceeds protocol limit")
            if not line.strip():
                continue
            obj = json.loads(line.decode("utf-8"))
            ack, _ = recorder.record(obj)
            replies.append(ack.encode("ascii"))
        if len(self.buffer) > MAX_LINE_BYTES:
            raise ValueError("unterminated line exceeds protocol limit")
        return replies


def serve(host: str, port: int, recorder: Recorder):
    """One ESP32 connection at a time. New connections preserve dedupe state."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(2)
        server.settimeout(1.0)
        print(f"Listening {host}:{port} | output: {recorder.directory.resolve()}", flush=True)
        print("Ctrl+C to finish. No frames yet: waiting for ESP32 / UART.", flush=True)
        while True:
            try:
                conn, address = server.accept()
            except socket.timeout:
                continue
            print(f"ESP32 connected from {address[0]}:{address[1]}", flush=True)
            with conn:
                conn.settimeout(1.0)
                session = LineSession()
                last_print = 0.0
                last_network = time.monotonic()
                while True:
                    try:
                        chunk = conn.recv(4096)
                    except socket.timeout:
                        chunk = None
                        if time.monotonic() - last_network > 12:
                            print("Network idle >12s; reconnect required.", flush=True)
                            break
                    except (ConnectionError, OSError) as exc:
                        print(f"Connection ended: {exc}", flush=True)
                        break
                    if chunk == b"":
                        break
                    if chunk:
                        last_network = time.monotonic()
                        try:
                            replies = session.feed(chunk, recorder)
                        except (ValueError, UnicodeError) as exc:
                            print(f"Rejected input; closing connection: {exc}", flush=True)
                            break
                        # Filesystem errors from feed are fatal; do not mistake
                        # them for a network disconnect and continue collecting.
                        try:
                            for ack in replies:
                                conn.sendall(ack)
                        except (ConnectionError, OSError) as exc:
                            print(f"ACK send failed; frame retained on PC: {exc}", flush=True)
                            break
                    if time.monotonic() - last_print >= 2:
                        status = recorder.latest_status or {}
                        age = status.get("last_frame_age_ms", "?")
                        since = (round(time.monotonic() - recorder.last_frame_monotonic, 1)
                                 if recorder.last_frame_monotonic is not None else "never")
                        targets = recorder.latest_targets or []
                        preview = " ".join(
                            f"S{i}:X={t['x_mm']} Y={t['y_mm']} V={t['speed_cms']}cm/s"
                            for i, t in enumerate(targets, 1) if t["active"])
                        print(f"saved={recorder.total} gaps={recorder.gaps} "
                              f"replays={recorder.duplicates} UART_age_ms={age} "
                              f"PC_seconds_since_frame={since} "
                              f"queue_drops={status.get('queue_drops', '?')} "
                              f"active={sum(t['active'] for t in targets)} {preview}", flush=True)
                        last_print = time.monotonic()
            print("Disconnected; waiting for reconnect...", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="listen address; default all IPv4 interfaces")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--participant", default="P01")
    parser.add_argument("--trial", default="T001")
    parser.add_argument("--activity", default="unlabelled")
    parser.add_argument("--notes", default="")
    parser.add_argument("--fsync", action="store_true", help="fsync both files before ACK (slower)")
    args = parser.parse_args()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    recorder = Recorder(args.out / f"session_{stamp}", args.participant, args.trial,
                        args.activity, args.notes, args.fsync)
    try:
        serve(args.host, args.port, recorder)
    except KeyboardInterrupt:
        print("\nStopping; closing data files.")
    except OSError as exc:
        print(f"I/O error: {exc}", file=sys.stderr)
        return 1
    finally:
        recorder.close()
    print(f"Saved {recorder.total} frames to {recorder.directory.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

