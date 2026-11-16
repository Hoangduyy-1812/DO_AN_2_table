"""Read the existing ESP32 /api/state height setting; no firmware writes."""
import json
import math
import threading
import urllib.request


def read_height(base_url):
    with urllib.request.urlopen(base_url.rstrip('/')+'/api/state',timeout=1.5) as response:
        data=json.load(response)
    value=data.get('h_mount_m')
    if isinstance(value,bool) or not isinstance(value,(float,int)):
        raise ValueError('ESP32 did not report a numeric h_mount_m')
    if not math.isfinite(value) or not 1.0<=value<=2.5:
        raise ValueError('ESP32 height must be between 1.00 and 2.50 m')
    return float(value)


def apply_height(detector, height_m):
    """Caller holds the same lock used for processing frames."""
    changed=any(abs(d.h_mount-height_m*1000)>1e-6 for d in detector.detectors.values())
    if changed:
        detector.reset_stream()
        for child in detector.detectors.values():child.h_mount=height_m*1000
    return changed


class HeightSync:
    def __init__(self,url,on_height,on_error,interval=2.0):
        self.url=url;self.on_height=on_height;self.on_error=on_error;self.interval=interval
        self.stop_event=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)

    def start(self):self.thread.start();return self

    def run(self):
        while not self.stop_event.is_set():
            try:self.on_height(read_height(self.url))
            except (OSError,ValueError,TypeError) as exc:self.on_error(str(exc))
            self.stop_event.wait(self.interval)

    def close(self):self.stop_event.set();self.thread.join(timeout=2)
