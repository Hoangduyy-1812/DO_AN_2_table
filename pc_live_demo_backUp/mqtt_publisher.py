"""Minimal MQTT 3.1.1 publisher (QoS 0) using only the Python standard library.

Runs in a background thread, reconnects automatically and never blocks the
radar/FSM pipeline: if the broker is unreachable, messages are simply dropped.

Topics (base = e.g. "doan2/hoangduy1812/ld2450"):
  <base>/state   live FSM state (throttled, JSON)
  <base>/alarm   one message per fall alarm (JSON)
  <base>/online  retained "1" while PC connected, "0" via Last Will when it drops
"""
from __future__ import annotations

import json
import queue
import random
import select
import socket
import struct
import threading
import time


def _varlen(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _packet(header: int, body: bytes) -> bytes:
    return bytes([header]) + _varlen(len(body)) + body


class MqttPublisher:
    def __init__(self, host: str = "broker.hivemq.com", port: int = 1883,
                 base_topic: str = "doan2/hoangduy1812/ld2450", keepalive: int = 30):
        self.host, self.port, self.base, self.keepalive = host, port, base_topic.rstrip("/"), keepalive
        self.client_id = f"ld2450-pc-{random.randint(0, 0xFFFFFF):06x}"
        self.q: queue.Queue = queue.Queue(maxsize=200)
        self.connected = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ---------- public API ----------
    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def publish(self, subtopic: str, payload, retain: bool = False):
        if not isinstance(payload, (bytes, str)):
            payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        item = (f"{self.base}/{subtopic}", payload, retain)
        try:
            self.q.put_nowait(item)
        except queue.Full:  # drop oldest, keep newest
            try:
                self.q.get_nowait()
                self.q.put_nowait(item)
            except queue.Empty:
                pass

    # ---------- internals ----------
    def _connect(self) -> socket.socket:
        s = socket.create_connection((self.host, self.port), timeout=5)
        will_topic = f"{self.base}/online"
        flags = 0x02 | 0x04 | 0x20  # clean session + will flag + will retain (QoS 0)
        body = (_str("MQTT") + bytes([4, flags]) + struct.pack("!H", self.keepalive)
                + _str(self.client_id) + _str(will_topic) + _str("0"))
        s.sendall(_packet(0x10, body))
        ack = s.recv(4)
        if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0:
            s.close()
            raise ConnectionError(f"CONNACK refused: {ack!r}")
        s.sendall(self._pub_bytes(will_topic, b"1", retain=True))
        return s

    @staticmethod
    def _pub_bytes(topic: str, payload: bytes, retain: bool) -> bytes:
        return _packet(0x30 | (0x01 if retain else 0), _str(topic) + payload)

    def _run(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                s = self._connect()
            except OSError as e:
                self.connected = False
                print(f"[MQTT] Khong ket noi duoc {self.host}:{self.port} ({e}); thu lai sau {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            self.connected, backoff = True, 1.0
            print(f"[MQTT] Da ket noi {self.host}:{self.port} | topic goc: {self.base}/#")
            last_tx = time.time()
            try:
                while not self._stop.is_set():
                    try:
                        topic, payload, retain = self.q.get(timeout=1.0)
                        s.sendall(self._pub_bytes(topic, payload, retain))
                        last_tx = time.time()
                    except queue.Empty:
                        pass
                    if time.time() - last_tx > self.keepalive / 2:
                        s.sendall(b"\xc0\x00")  # PINGREQ
                        last_tx = time.time()
                    r, _, _ = select.select([s], [], [], 0)
                    if r and not s.recv(64):  # drain PINGRESP; b"" means closed
                        raise ConnectionError("broker closed connection")
            except OSError as e:
                print(f"[MQTT] Mat ket noi ({e}), dang ket noi lai...")
            finally:
                self.connected = False
                try:
                    s.close()
                except OSError:
                    pass
