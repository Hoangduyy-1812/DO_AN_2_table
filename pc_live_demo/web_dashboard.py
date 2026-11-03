#!/usr/bin/env python3
"""Web Dashboard for 24GHz mmWave Fall Detection & FSM Monitoring.
Zero-dependency: Python standard library only (http.server + socket + threading).
Serves real-time Web GUI on http://localhost:8080 and receives ESP32 TCP stream on port 9000.
"""
from __future__ import annotations

import argparse, csv, datetime as dt, http.server, json, os, queue, socket, socketserver, sys, threading, time, webbrowser
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from protocol import COUNTERS, decode_frame, validate_record
from live_fall_fsm import OnlineFallDetectorFSM
import receiver

# Global broadcast queue for connected SSE clients
subscribers: list[queue.Queue] = []
subscribers_lock = threading.Lock()
detector_lock = threading.Lock()
global_detector = OnlineFallDetectorFSM(h_mount_mm=1700.0, v_thresh=0.78, hold_s=8.0)
alarm_history: list[dict] = []
tcp_connected = False
last_frame_info = {
    't_s': 0.0, 'slot': None, 'x_mm': 0.0, 'y_mm': 0.0, 'z_est_m': 1.7,
    'v_mps': 0.0, 'state': 'MONITORING', 'hold_time_s': 0.0, 'note': 'Chờ kết nối ESP32...'
}

HTML_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>mmWave 24GHz Radar Fall Detection Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(18, 25, 42, 0.85);
      --card-border: rgba(255, 255, 255, 0.08);
      --card-border-hover: rgba(0, 229, 255, 0.3);
      --primary: #00f0ff;
      --primary-glow: rgba(0, 240, 255, 0.35);
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.35);
      --warning: #f59e0b;
      --warning-glow: rgba(245, 158, 11, 0.4);
      --danger: #ef4444;
      --danger-glow: rgba(239, 68, 68, 0.5);
      --text: #f3f4f6;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: radial-gradient(circle at 50% 0%, #151d33 0%, var(--bg) 70%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow-x: hidden;
    }
    .mono { font-family: 'JetBrains Mono', monospace; }
    
    /* Header */
    header {
      background: rgba(10, 15, 28, 0.85);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--card-border);
      padding: 14px 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .logo-group { display: flex; align-items: center; gap: 14px; }
    .radar-icon {
      width: 40px; height: 40px; border-radius: 10px;
      background: linear-gradient(135deg, #0284c7, #00f0ff);
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 0 20px var(--primary-glow);
    }
    .radar-icon svg { width: 24px; height: 24px; fill: #000; }
    h1 { font-size: 1.15rem; font-weight: 800; letter-spacing: -0.02em; }
    .subtitle { font-size: 0.78rem; color: var(--text-muted); font-weight: 500; }
    
    .header-badges { display: flex; align-items: center; gap: 12px; }
    .badge {
      display: flex; align-items: center; gap: 6px;
      padding: 6px 14px; border-radius: 9999px;
      font-size: 0.75rem; font-weight: 600;
      border: 1px solid transparent;
    }
    .badge-offline { background: rgba(239, 68, 68, 0.15); color: #fca5a5; border-color: rgba(239, 68, 68, 0.3); }
    .badge-online { background: rgba(16, 185, 129, 0.15); color: #6ee7b7; border-color: rgba(16, 185, 129, 0.3); }
    .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; animation: pulse 1.8s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.3); } }

    /* Button Styles */
    .btn {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 7px 16px; border-radius: 8px;
      font-size: 0.8rem; font-weight: 600;
      cursor: pointer; transition: all 0.2s ease;
      display: inline-flex; align-items: center; gap: 6px;
    }
    .btn:hover { background: rgba(255, 255, 255, 0.1); border-color: var(--primary); }
    .btn-primary { background: linear-gradient(135deg, #0284c7, #00f0ff); color: #000; border: none; font-weight: 700; }
    .btn-primary:hover { box-shadow: 0 0 16px var(--primary-glow); transform: translateY(-1px); }

    /* Main Container */
    main { padding: 24px 28px; max-width: 1540px; margin: 0 auto; width: 100%; display: flex; flex-direction: column; gap: 20px; flex: 1; }

    /* Alert Banner */
    #status-banner {
      border-radius: 14px;
      padding: 18px 24px;
      display: flex; justify-content: space-between; align-items: center;
      transition: all 0.3s ease;
      border: 1px solid;
    }
    .banner-monitoring {
      background: linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(16, 185, 129, 0.03));
      border-color: rgba(16, 185, 129, 0.4);
      color: #34d399;
    }
    .banner-suspected {
      background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(245, 158, 11, 0.05));
      border-color: var(--warning);
      color: #fbbf24;
      animation: alertPulse 1.2s infinite alternate;
    }
    .banner-alarm {
      background: linear-gradient(135deg, rgba(239, 68, 68, 0.3), rgba(239, 68, 68, 0.1));
      border-color: var(--danger);
      color: #f87171;
      animation: alarmFlash 0.6s infinite alternate;
      box-shadow: 0 0 30px var(--danger-glow);
    }
    @keyframes alertPulse { from { box-shadow: 0 0 10px rgba(245, 158, 11, 0.2); } to { box-shadow: 0 0 25px rgba(245, 158, 11, 0.5); } }
    @keyframes alarmFlash { from { background: rgba(239, 68, 68, 0.4); } to { background: rgba(239, 68, 68, 0.15); } }

    .banner-title { font-size: 1.3rem; font-weight: 900; letter-spacing: -0.01em; display: flex; align-items: center; gap: 10px; }
    .banner-desc { font-size: 0.85rem; opacity: 0.9; margin-top: 4px; }
    .progress-bar-container { width: 240px; height: 10px; background: rgba(255, 255, 255, 0.1); border-radius: 5px; overflow: hidden; margin-top: 8px; }
    .progress-bar { height: 100%; width: 0%; background: var(--warning); transition: width 0.1s linear; }

    /* KPI Grid */
    .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 18px 20px;
      position: relative;
      overflow: hidden;
      transition: all 0.2s ease;
    }
    .card:hover { border-color: var(--card-border-hover); transform: translateY(-2px); }
    .card-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); font-weight: 700; margin-bottom: 6px; }
    .card-val { font-size: 2.2rem; font-weight: 900; line-height: 1.1; margin-bottom: 4px; }
    .card-sub { font-size: 0.78rem; color: var(--text-muted); display: flex; align-items: center; gap: 6px; }

    /* Visualizers Row */
    .visual-grid { display: grid; grid-template-columns: 1.1fr 1.4fr; gap: 20px; }
    .canvas-card { display: flex; flex-direction: column; }
    .canvas-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .canvas-title { font-size: 0.92rem; font-weight: 700; }
    canvas { width: 100%; height: 320px; border-radius: 10px; background: rgba(8, 12, 22, 0.7); border: 1px solid rgba(255, 255, 255, 0.04); }

    /* Alarm History Table */
    .table-container { overflow-x: auto; max-height: 220px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.8rem; text-align: left; }
    th { padding: 10px 14px; background: rgba(255, 255, 255, 0.03); color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 0.7rem; border-bottom: 1px solid var(--card-border); }
    td { padding: 10px 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
    tr:hover { background: rgba(255, 255, 255, 0.02); }

    /* Responsive Mobile Layout */
    @media (max-width: 900px) {
      header { flex-direction: column; align-items: flex-start; gap: 12px; padding: 12px 16px; }
      .header-badges { width: 100%; flex-wrap: wrap; gap: 8px; }
      main { padding: 14px 16px; }
      #status-banner { flex-direction: column; align-items: flex-start; gap: 12px; }
      .kpi-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
      .visual-grid { grid-template-columns: 1fr; gap: 16px; }
      canvas { height: 260px; }
    }
    @media (max-width: 480px) {
      .kpi-grid { grid-template-columns: 1fr; }
      h1 { font-size: 1.0rem; }
    }

    /* Footer */
    footer { padding: 14px 28px; text-align: center; font-size: 0.75rem; color: var(--text-muted); border-top: 1px solid var(--card-border); }
  </style>
</head>
<body>

  <header>
    <div class="logo-group">
      <div class="radar-icon">
        <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"/></svg>
      </div>
      <div>
        <h1>HỆ THỐNG PHÁT HIỆN TÉ NGÃ mmWAVE RADAR 24GHz</h1>
        <div class="subtitle">Đồ án Chuyên ngành 2 & Luận văn Tốt nghiệp - Cảm biến HLK-LD2450 & ESP32-S3</div>
      </div>
    </div>
    <div class="header-badges">
      <div id="conn-badge" class="badge badge-offline">
        <div class="pulse-dot"></div>
        <span id="conn-text">ESP32: Đang chờ TCP...</span>
      </div>
      <button id="sound-btn" class="btn" onclick="toggleSound()">
        <span id="sound-icon">🔊</span> <span id="sound-text">Chuông: BẬT</span>
      </button>
      <button class="btn btn-primary" onclick="simulateFall()">🧪 Giả lập Ngã Demo</button>
      <button class="btn" onclick="resetFSM()">🔄 Đặt lại FSM</button>
    </div>
  </header>

  <main>
    <!-- State Banner -->
    <div id="status-banner" class="banner-monitoring">
      <div>
        <div class="banner-title" id="banner-title">🟢 HỆ THỐNG ĐANG GIÁM SÁT AN TOÀN (MONITORING)</div>
        <div class="banner-desc" id="banner-desc">Radar quét chùm sóng góc 120°, tư thế người dùng ở trạng thái bình thường.</div>
        <div id="countdown-wrap" style="display: none;">
          <div class="progress-bar-container">
            <div id="progress-bar" class="progress-bar"></div>
          </div>
        </div>
      </div>
      <div style="text-align: right;">
        <div class="mono" style="font-size: 0.85rem; color: var(--text-muted);">Mốc thời gian phiên</div>
        <div class="mono" id="current-time-text" style="font-size: 1.5rem; font-weight: 700; color: #fff;">00.0s</div>
      </div>
    </div>

    <!-- KPI Grid -->
    <div class="kpi-grid">
      <div class="card">
        <div class="card-label">Chiều cao ước lượng Z_est</div>
        <div class="card-val mono" id="val-z" style="color: #38bdf8;">1.70<span style="font-size: 1.2rem; font-weight: 500;"> m</span></div>
        <div class="card-sub" id="posture-tag"><span class="badge badge-online">ĐỨNG THẲNG (>1.0m)</span></div>
      </div>

      <div class="card">
        <div class="card-label">Vận tốc tức thời (Doppler)</div>
        <div class="card-val mono" id="val-v" style="color: #fbbf24;">0.00<span style="font-size: 1.2rem; font-weight: 500;"> m/s</span></div>
        <div class="card-sub mono" id="peak-v-sub">Đỉnh rơi lớn nhất: 0.00 m/s</div>
      </div>

      <div class="card">
        <div class="card-label">Tọa độ Radar 2D (X, Y)</div>
        <div class="card-val mono" id="val-xy" style="font-size: 1.6rem; margin-top: 4px;">X: 0 | Y: 0</div>
        <div class="card-sub mono" id="sub-dist">Cự ly cách radar: 0.00 m</div>
      </div>

      <div class="card">
        <div class="card-label">Mục tiêu Radar bám</div>
        <div class="card-val mono" id="val-slot" style="color: #a78bfa;">SLOT 1</div>
        <div class="card-sub mono" id="val-frame-info">Frame: #0 | Backlog: 0ms</div>
      </div>
    </div>

    <!-- Visualizer Canvas Row -->
    <div class="visual-grid">
      <!-- 2D Room Radar Map -->
      <div class="card canvas-card">
        <div class="canvas-header">
          <div class="canvas-title">📍 Bản đồ Quét Không Gian Phòng 2D (Top-down Radar)</div>
          <div class="mono" style="font-size: 0.75rem; color: var(--text-muted);">Vùng quan tâm (ROI): Y ≤ 3.2m</div>
        </div>
        <canvas id="radarCanvas" width="600" height="340"></canvas>
      </div>

      <!-- Real-time Height & Velocity Charts -->
      <div class="card canvas-card">
        <div class="canvas-header">
          <div class="canvas-title">📈 Quỹ đạo Cao độ Z(t) & Vận tốc V(t) Thời Gian Thực</div>
          <div style="display: flex; gap: 12px; font-size: 0.75rem;">
            <span style="color: #38bdf8;">● Cao độ Z</span>
            <span style="color: #fbbf24;">● Vận tốc V</span>
            <span style="color: #ef4444;">-- Ngưỡng ngã (0.4m)</span>
          </div>
        </div>
        <canvas id="timelineCanvas" width="700" height="340"></canvas>
      </div>
    </div>

    <!-- Alarm History Table -->
    <div class="card">
      <div class="canvas-header" style="margin-bottom: 8px;">
        <div class="canvas-title">🚨 Nhật ký Các Cú Ngã Đã Nhận Diện Trong Phiên (Alarm Incident History)</div>
        <div id="alarm-count-badge" class="badge badge-offline">0 Cảnh báo</div>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Thời điểm rơi</th>
              <th>Thời điểm phát còi</th>
              <th>Độ trễ xác nhận</th>
              <th>V_peak lúc rơi</th>
              <th>Tốc độ tụt (dz/dt)</th>
              <th>Cao độ sàn</th>
              <th>Target Slot</th>
              <th>Trạng thái</th>
            </tr>
          </thead>
          <tbody id="alarm-tbody">
            <tr>
              <td colspan="9" style="text-align: center; color: var(--text-muted); padding: 18px;">Chưa ghi nhận cú ngã nào. Hệ thống sẵn sàng giám sát.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <footer>
    Đồ án Chuyên ngành 2 & Luận văn Tốt nghiệp - Cảm biến mmWave Radar 24GHz HLK-LD2450 & ESP32-S3 FreeRTOS TCP Receiver
  </footer>

  <script>
    // Audio synthesizer for alarm
    let soundEnabled = true;
    let audioCtx = null;
    function initAudio() {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    function toggleSound() {
      soundEnabled = !soundEnabled;
      document.getElementById('sound-text').innerText = soundEnabled ? 'Chuông: BẬT' : 'Chuông: TẮT';
      document.getElementById('sound-icon').innerText = soundEnabled ? '🔊' : '🔇';
      if (soundEnabled) initAudio();
    }
    function playBeep(freq = 880, duration = 0.25) {
      if (!soundEnabled) return;
      initAudio();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    }

    // Historical Points Buffer for Timeline
    const historyData = [];
    const maxHistoryPoints = 180; // 18 seconds at 10Hz
    let currentTrail = [];

    // Radar Canvas
    const radarCanvas = document.getElementById('radarCanvas');
    const rCtx = radarCanvas.getContext('2d');

    // Timeline Canvas
    const timelineCanvas = document.getElementById('timelineCanvas');
    const tCtx = timelineCanvas.getContext('2d');

    function renderRadar(curX, curY, curZ, state) {
      const w = radarCanvas.width;
      const h = radarCanvas.height;
      rCtx.clearRect(0, 0, w, h);

      const originX = w / 2;
      const originY = 30;
      const scale = (h - 60) / 3.8; // scale meters to pixels

      // Draw sector arcs (1m, 2m, 3m)
      rCtx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
      rCtx.lineWidth = 1;
      for (let r = 1; r <= 3; r++) {
        rCtx.beginPath();
        rCtx.arc(originX, originY, r * scale, Math.PI * 0.15, Math.PI * 0.85, false);
        rCtx.stroke();
        rCtx.fillStyle = 'rgba(255, 255, 255, 0.3)';
        rCtx.font = '10px JetBrains Mono';
        rCtx.fillText(`${r}m`, originX + 5, originY + r * scale - 4);
      }

      // Draw 120-degree cone
      rCtx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
      rCtx.beginPath();
      rCtx.moveTo(originX, originY);
      rCtx.lineTo(originX - Math.sin(Math.PI / 3) * 3.4 * scale, originY + Math.cos(Math.PI / 3) * 3.4 * scale);
      rCtx.moveTo(originX, originY);
      rCtx.lineTo(originX + Math.sin(Math.PI / 3) * 3.4 * scale, originY + Math.cos(Math.PI / 3) * 3.4 * scale);
      rCtx.stroke();

      // Draw ROI Boundary (Y = 3.2m)
      const roiY = originY + 3.2 * scale;
      rCtx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
      rCtx.setLineDash([4, 4]);
      rCtx.beginPath();
      rCtx.moveTo(20, roiY);
      rCtx.lineTo(w - 20, roiY);
      rCtx.stroke();
      rCtx.setLineDash([]);
      rCtx.fillStyle = 'rgba(239, 68, 68, 0.6)';
      rCtx.fillText('Giới hạn ROI (3.2m)', 25, roiY - 6);

      // Draw Radar Sensor Origin
      rCtx.fillStyle = '#00f0ff';
      rCtx.beginPath();
      rCtx.arc(originX, originY, 6, 0, Math.PI * 2);
      rCtx.fill();
      rCtx.font = '11px Inter';
      rCtx.fillStyle = '#94a3b8';
      rCtx.fillText('LD2450 (1.7m)', originX - 35, originY - 12);

      // Draw Person Position if valid
      if (curY > 0) {
        // Lateral offset in vertical mounting: note LD2450 X is vertical, but we project 2D range
        // For visual plotting in room: map X (-500 to +500) and Y (distance)
        const personPx = originX; // central lane projection
        const personPy = originY + (curY / 1000.0) * scale;

        // Trail
        currentTrail.push({x: personPx, y: personPy});
        if (currentTrail.length > 25) currentTrail.shift();
        rCtx.strokeStyle = 'rgba(0, 240, 255, 0.15)';
        rCtx.lineWidth = 3;
        rCtx.beginPath();
        for (let i = 0; i < currentTrail.length; i++) {
          if (i === 0) rCtx.moveTo(currentTrail[i].x, currentTrail[i].y);
          else rCtx.lineTo(currentTrail[i].x, currentTrail[i].y);
        }
        rCtx.stroke();

        // Person Marker
        let markerColor = '#10b981';
        let glowColor = 'rgba(16, 185, 129, 0.6)';
        if (state === 'SUSPECTED_FALL') {
          markerColor = '#f59e0b';
          glowColor = 'rgba(245, 158, 11, 0.8)';
        } else if (state === 'ALARM_TRIGGERED') {
          markerColor = '#ef4444';
          glowColor = 'rgba(239, 68, 68, 0.9)';
        }

        // Glow ring
        rCtx.fillStyle = glowColor;
        rCtx.beginPath();
        rCtx.arc(personPx, personPy, 14, 0, Math.PI * 2);
        rCtx.fill();

        // Core dot
        rCtx.fillStyle = markerColor;
        rCtx.beginPath();
        rCtx.arc(personPx, personPy, 7, 0, Math.PI * 2);
        rCtx.fill();

        // Label
        rCtx.font = 'bold 11px JetBrains Mono';
        rCtx.fillStyle = '#ffffff';
        rCtx.fillText(`Z: ${curZ.toFixed(2)}m`, personPx + 16, personPy + 4);
      }
    }

    function renderTimeline() {
      const w = timelineCanvas.width;
      const h = timelineCanvas.height;
      tCtx.clearRect(0, 0, w, h);

      if (historyData.length < 2) return;

      const paddingLeft = 40;
      const paddingBottom = 30;
      const graphW = w - paddingLeft - 20;
      const graphH = h - paddingBottom - 20;

      // Draw Grid & Axes
      tCtx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
      tCtx.lineWidth = 1;

      // Height lines (0m, 0.4m, 1.0m, 1.8m)
      const maxZ = 2.0;
      for (let z = 0; z <= 2.0; z += 0.5) {
        const y = h - paddingBottom - (z / maxZ) * graphH;
        tCtx.beginPath();
        tCtx.moveTo(paddingLeft, y);
        tCtx.lineTo(w - 20, y);
        tCtx.stroke();
        tCtx.fillStyle = 'rgba(255, 255, 255, 0.3)';
        tCtx.font = '10px JetBrains Mono';
        tCtx.fillText(`${z.toFixed(1)}m`, 6, y + 3);
      }

      // Draw Critical Fall Floor Threshold (0.4m)
      const floorY = h - paddingBottom - (0.40 / maxZ) * graphH;
      tCtx.strokeStyle = 'rgba(239, 68, 68, 0.5)';
      tCtx.setLineDash([4, 4]);
      tCtx.beginPath();
      tCtx.moveTo(paddingLeft, floorY);
      tCtx.lineTo(w - 20, floorY);
      tCtx.stroke();
      tCtx.setLineDash([]);
      tCtx.fillStyle = 'rgba(239, 68, 68, 0.7)';
      tCtx.fillText('Ngưỡng sàn (0.40m)', w - 125, floorY - 6);

      // Plot Z(t) - Blue Line
      tCtx.strokeStyle = '#38bdf8';
      tCtx.lineWidth = 2.5;
      tCtx.beginPath();
      for (let i = 0; i < historyData.length; i++) {
        const pt = historyData[i];
        const x = paddingLeft + (i / (maxHistoryPoints - 1)) * graphW;
        const zClamped = Math.max(0, Math.min(maxZ, pt.z));
        const y = h - paddingBottom - (zClamped / maxZ) * graphH;
        if (i === 0) tCtx.moveTo(x, y);
        else tCtx.lineTo(x, y);
      }
      tCtx.stroke();

      // Plot V(t) - Yellow Line
      tCtx.strokeStyle = '#fbbf24';
      tCtx.lineWidth = 1.8;
      tCtx.beginPath();
      for (let i = 0; i < historyData.length; i++) {
        const pt = historyData[i];
        const x = paddingLeft + (i / (maxHistoryPoints - 1)) * graphW;
        const vClamped = Math.max(0, Math.min(maxZ, pt.v));
        const y = h - paddingBottom - (vClamped / maxZ) * graphH;
        if (i === 0) tCtx.moveTo(x, y);
        else tCtx.lineTo(x, y);
      }
      tCtx.stroke();
    }

    // Connect to Server-Sent Events (SSE)
    const evtSource = new EventSource('/events');

    evtSource.onmessage = function(e) {
      const data = JSON.parse(e.data);
      updateUI(data);
    };

    let prevAlarmCount = 0;

    function updateUI(data) {
      // Connection badge
      const badge = document.getElementById('conn-badge');
      const connText = document.getElementById('conn-text');
      if (data.tcp_connected) {
        badge.className = 'badge badge-online';
        connText.innerText = 'ESP32: ĐANG KẾT NỐI (Port 9000)';
      } else {
        badge.className = 'badge badge-offline';
        connText.innerText = 'ESP32: ĐANG CHỜ KẾT NỐI...';
      }

      // Time
      document.getElementById('current-time-text').innerText = `${data.t_s.toFixed(1)}s`;

      // Cards
      document.getElementById('val-z').innerHTML = `${data.z_est_m.toFixed(2)}<span style="font-size: 1.2rem; font-weight: 500;"> m</span>`;
      document.getElementById('val-v').innerHTML = `${data.v_mps.toFixed(2)}<span style="font-size: 1.2rem; font-weight: 500;"> m/s</span>`;
      document.getElementById('val-xy').innerText = `X: ${Math.round(data.x_mm)} | Y: ${Math.round(data.y_mm)}`;

      const dist = Math.sqrt(data.x_mm**2 + data.y_mm**2) / 1000.0;
      document.getElementById('sub-dist').innerText = `Cự ly cách radar: ${dist.toFixed(2)} m`;
      document.getElementById('val-slot').innerText = data.slot ? `SLOT ${data.slot}` : 'KHÔNG CÓ';
      document.getElementById('val-frame-info').innerText = `Note: ${data.note || 'OK'}`;

      // Posture Badge
      const posture = document.getElementById('posture-tag');
      if (data.z_est_m >= 1.0) {
        posture.innerHTML = '<span class="badge badge-online">ĐỨNG THẲNG (>1.0m)</span>';
      } else if (data.z_est_m >= 0.50) {
        posture.innerHTML = '<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border-color: rgba(245, 158, 11, 0.3);">NGỒI / CÚI (~0.6-0.9m)</span>';
      } else {
        posture.innerHTML = '<span class="badge badge-offline">SÁT SÀN NHÀ (<0.48m)</span>';
      }

      // FSM Banner
      const banner = document.getElementById('status-banner');
      const bTitle = document.getElementById('banner-title');
      const bDesc = document.getElementById('banner-desc');
      const cWrap = document.getElementById('countdown-wrap');
      const pBar = document.getElementById('progress-bar');

      if (data.state === 'MONITORING') {
        banner.className = 'banner-monitoring';
        bTitle.innerText = '🟢 HỆ THỐNG ĐANG GIÁM SÁT AN TOÀN (MONITORING)';
        bDesc.innerText = 'Radar quét chùm sóng góc 120°, tư thế người dùng ở trạng thái bình thường.';
        cWrap.style.display = 'none';
      } else if (data.state === 'SUSPECTED_FALL') {
        banner.className = 'banner-suspected';
        bTitle.innerText = `🟡 NGHI VẤN TÉ NGÃ - ĐANG XÁC MINH NẰM SÀN (${data.hold_time_s.toFixed(1)}s / 8.0s)`;
        bDesc.innerText = 'Phát hiện rơi nhanh đột ngột! FSM đang đếm thời gian bất động sát sàn...';
        cWrap.style.display = 'block';
        const pct = Math.min(100, (data.hold_time_s / 8.0) * 100);
        pBar.style.width = `${pct}%`;
        playBeep(440, 0.08); // warning ping
      } else if (data.state === 'ALARM_TRIGGERED') {
        banner.className = 'banner-alarm';
        bTitle.innerText = '🚨 CẢNH BÁO: PHÁT HIỆN TÉ NGÃ KHẨN CẤP! (ALARM TRIGGERED)';
        bDesc.innerText = 'Người dùng đã sập sàn với tốc độ lớn và bất động trên sàn quá 8 giây!';
        cWrap.style.display = 'none';
        playBeep(980, 0.3); // loud emergency siren
      }

      // Push history
      historyData.push({ z: data.z_est_m, v: data.v_mps, t: data.t_s });
      if (historyData.length > maxHistoryPoints) historyData.shift();

      // Render Canvases
      renderRadar(data.x_mm, data.y_mm, data.z_est_m, data.state);
      renderTimeline();

      // Alarms History Update
      if (data.alarms && data.alarms.length !== prevAlarmCount) {
        prevAlarmCount = data.alarms.length;
        document.getElementById('alarm-count-badge').innerText = `${prevAlarmCount} Cảnh báo`;
        const tbody = document.getElementById('alarm-tbody');
        tbody.innerHTML = '';
        data.alarms.slice().reverse().forEach((a, idx) => {
          const row = document.createElement('tr');
          row.innerHTML = `
            <td class="mono" style="font-weight: 700; color: #ef4444;">#${data.alarms.length - idx}</td>
            <td class="mono">${a.impact_time_s}s</td>
            <td class="mono" style="color: #ef4444; font-weight: 700;">${a.alarm_time_s}s</td>
            <td class="mono">${a.latency_s}s</td>
            <td class="mono" style="color: #fbbf24;">${a.v_peak_mps} m/s</td>
            <td class="mono">${a.drop_rate_mps} m/s</td>
            <td class="mono">${a.z_floor_m} m</td>
            <td class="mono">Slot ${a.slot}</td>
            <td><span class="badge badge-offline">ALARM TRIGGERED</span></td>
          `;
          tbody.appendChild(row);
        });
      }
    }

    function simulateFall() {
      fetch('/api/simulate', { method: 'POST' });
    }

    function resetFSM() {
      fetch('/api/reset', { method: 'POST' });
    }
  </script>
</body>
</html>
"""

def broadcast(payload: dict):
    with subscribers_lock:
        dead = []
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for d in dead:
            subscribers.remove(d)

class WebHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
        elif self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            q = queue.Queue(maxsize=100)
            with subscribers_lock:
                subscribers.append(q)

            # Send initial state
            with detector_lock:
                init_data = dict(last_frame_info)
                init_data['tcp_connected'] = tcp_connected
                init_data['alarms'] = list(alarm_history)
            try:
                self.wfile.write(f"data: {json.dumps(init_data)}\n\n".encode('utf-8'))
                self.wfile.flush()
                while True:
                    try:
                        data = q.get(timeout=1.0)
                        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode('utf-8'))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with subscribers_lock:
                    if q in subscribers:
                        subscribers.remove(q)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global alarm_history
        if self.path == '/api/reset':
            with detector_lock:
                global_detector.reset_all()
                alarm_history.clear()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        elif self.path == '/api/simulate':
            # Launch simulated fall thread
            threading.Thread(target=run_simulation, daemon=True).start()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "simulation_started"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence standard HTTP access logging to keep console clean
        return

def run_simulation():
    """Simulate a realistic fall sequence in background and feed to FSM."""
    print("\n[SIMULATION] Bắt đầu chuỗi giả lập té ngã...")
    with detector_lock:
        global_detector.reset_all()

    # Phase 1: Standing upright for 2 seconds (Z = 1.50m)
    t_start = time.time()
    for t_step in range(0, 20):
        t_us = int((time.time() - t_start + t_step * 0.1) * 1e6)
        active_list = [{'slot': 1, 'x_mm': 200, 'y_mm': 1800, 'v_mps': 0.10}]
        process_frame(t_us, active_list, backlog_ms=10.0, simulated=True)
        time.sleep(0.09)

    # Phase 2: Rapid Descent (Fall) in 0.5s (Z drops from 1.5m -> 0.3m, V_peak = 1.45 m/s)
    drop_points = [
        (450, 0.45), (800, 0.95), (1150, 1.45), (1350, 1.20), (1400, 0.60)
    ]
    for x_val, v_val in drop_points:
        t_us = int((time.time() - t_start) * 1e6)
        active_list = [{'slot': 1, 'x_mm': x_val, 'y_mm': 1850, 'v_mps': v_val}]
        process_frame(t_us, active_list, backlog_ms=10.0, simulated=True)
        time.sleep(0.09)

    # Phase 3: Lying still on floor for 9 seconds (Z ~ 0.30m, V ~ 0.02 m/s)
    for _ in range(90):
        t_us = int((time.time() - t_start) * 1e6)
        active_list = [{'slot': 1, 'x_mm': 1400, 'y_mm': 1850, 'v_mps': 0.02}]
        process_frame(t_us, active_list, backlog_ms=10.0, simulated=True)
        time.sleep(0.09)

    print("[SIMULATION] Chuỗi giả lập hoàn tất.\n")

def process_frame(t_us: int, active_list: list[dict], backlog_ms: float = 0.0, simulated: bool = False):
    global last_frame_info
    with detector_lock:
        summary, alarm = global_detector.update(t_us, active_list, backlog_ms=backlog_ms)
        if alarm:
            alarm_history.append(alarm)
            print("\n" + "="*70)
            print(f"🚨 [CẢNH BÁO TÉ NGÃ!] ALARM TRIGGERED! (t={alarm['alarm_time_s']}s, Latency={alarm['latency_s']}s)")
            print("="*70 + "\n")
            sys.stdout.write('\a')
            sys.stdout.flush()

        summary['tcp_connected'] = tcp_connected or simulated
        summary['alarms'] = list(alarm_history)
        last_frame_info = summary

    broadcast(summary)

class LiveWebRecorder(receiver.Recorder):
    def record(self, obj: object) -> tuple[str, bool]:
        global tcp_connected
        tcp_connected = True
        ack, res = super().record(obj)
        if not res:
            return ack, res
        r = validate_record(obj)
        if r["type"] == "frame":
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
            process_frame(r["t_us"], active_list, backlog_ms=backlog_ms)
        return ack, res

def start_http_server(host="0.0.0.0", port=8080):
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    server = ThreadedHTTPServer((host, port), WebHandler)
    server.serve_forever()

def main():
    parser = argparse.ArgumentParser(description="Web Dashboard for Fall Detection")
    parser.add_argument("--tcp-port", type=int, default=9000, help="ESP32 TCP port")
    parser.add_argument("--web-port", type=int, default=8080, help="Web Dashboard port")
    parser.add_argument("--out", type=Path, default=Path("data_web_session"))
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open web browser")
    args = parser.parse_args()

    # 1. Start HTTP Server in background thread
    http_thread = threading.Thread(target=start_http_server, args=("0.0.0.0", args.web_port), daemon=True)
    http_thread.start()
    web_url = f"http://localhost:{args.web_port}"

    print("\n" + "="*80)
    print("[WEB GUI] GIAO DIEN WEB DASHBOARD DA KHOI CHAY THANH CONG!")
    print(f"   * Truy cap Dashboard tai trinh duyet: {web_url}")
    print(f"   * Dang lang nghe ket noi TCP tu ESP32 tai cong: {args.tcp_port}")
    print("   * Tinh nang noi bat:")
    print("      - Canh bao am thanh thoi gian thuc (Web Audio API)")
    print("      - Ban do quet phong 2D (Top-down Room View)")
    print("      - Do thi cao do Z(t) & van toc V(t) 60 FPS")
    print("      - Nut bam 'Gia lap Nga Demo' truc tiep tren giao dien Web")
    print("="*80 + "\n")

    if not args.no_browser:
        try:
            webbrowser.open(web_url)
        except Exception:
            pass

    # 2. Start TCP Receiver for ESP32
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    rec = LiveWebRecorder(args.out / f"web_{stamp}", "P01", "WEB_TRIAL", "live_dashboard", "Web Dashboard run", False)

    try:
        receiver.serve("0.0.0.0", args.tcp_port, rec)
    except KeyboardInterrupt:
        print("\n[DỪNG HỆ THỐNG] Đóng kết nối.")
    finally:
        rec.close()

if __name__ == "__main__":
    raise SystemExit(main())
