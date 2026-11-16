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

from fall_window import FEATURE_SETS, feature_set_from_bundle
from configured_fsm import load_settings
from height_sync import HeightSync, apply_height
from posture_fsm import PostureFSM, old_posture, height_posture
from live_fall_fsm import MAX_BACKLOG_MS, MultiTargetFallDetector
from mqtt_publisher import MqttPublisher
import receiver

# Global broadcast queue for connected SSE clients
subscribers: list[queue.Queue] = []
subscribers_lock = threading.Lock()
detector_lock = threading.Lock()
global_detector = MultiTargetFallDetector(h_mount_mm=1700.0, v_thresh=0.78, hold_s=8.0)
ml_model_name = None
runtime_config = {'h_mount_m': 1.7, 'calibration_h_mount_m': 1.7,
                  'height_source': 'config', 'height_sync_status': 'manual'}
posture_mode = 'old'
posture_config = None
posture_detectors = {}
alarm_history: list[dict] = []
tcp_connected = False
last_detector_source = None
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
        <div class="subtitle">Đồ án Chuyên ngành 2 & Luận văn Tốt nghiệp - Cảm biến HLK-LD2450 & ESP32</div>
      </div>
    </div>
    <div class="header-badges">
      <div id="detector-mode" class="badge">Bộ phát hiện</div>
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
        <div class="banner-title" id="banner-title">ĐANG CHỜ DỮ LIỆU</div>
        <div class="banner-desc" id="banner-desc">Đang chờ dữ liệu từ ESP32.</div>
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
        <div class="card-val mono" id="val-z" style="color: #38bdf8;">—</div>
        <div class="card-sub" id="posture-tag">Chưa có dữ liệu</div>
      </div>

      <div class="card">
        <div class="card-label">Vận tốc tức thời (Doppler)</div>
        <div class="card-val mono" id="val-v" style="color: #fbbf24;">—</div>
        <div class="card-sub mono" id="peak-v-sub">Đỉnh rơi lớn nhất: 0.00 m/s</div>
      </div>

      <div class="card">
        <div class="card-label">Tọa độ Radar 2D (X, Y)</div>
        <div class="card-val mono" id="val-xy" style="font-size: 1.6rem; margin-top: 4px;">—</div>
        <div class="card-sub mono" id="sub-dist">Cự ly: —</div>
      </div>

      <div class="card">
        <div class="card-label">Mục tiêu Radar bám</div>
        <div class="card-val mono" id="val-slot" style="color: #a78bfa;">—</div>
        <div class="card-sub mono" id="val-frame-info">Đang chờ khung radar</div>
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
        <div id="radar-target-states" class="mono" style="white-space: pre-line; font-size: 0.8rem; margin-top: 10px;"></div>
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
    let primarySlot = null;

    // Radar Canvas
    const radarCanvas = document.getElementById('radarCanvas');
    const rCtx = radarCanvas.getContext('2d');

    // Timeline Canvas
    const timelineCanvas = document.getElementById('timelineCanvas');
    const tCtx = timelineCanvas.getContext('2d');

    function renderRadar(targets, statesBySlot, trackedSlot, delayed) {
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

      const tracked = targets.find(target => target.slot === trackedSlot && target.y_mm > 0);
      if (tracked) {
        const trackX = originX + (trackedSlot - 2) * 16;
        currentTrail.push(originY + Math.min(tracked.y_mm / 1000, 3.8) * scale);
        if (currentTrail.length > 25) currentTrail.shift();
        rCtx.strokeStyle = 'rgba(0, 240, 255, 0.15)';
        rCtx.lineWidth = 3;
        rCtx.beginPath();
        currentTrail.forEach((y, index) => {
          if (index === 0) rCtx.moveTo(trackX, y);
          else rCtx.lineTo(trackX, y);
        });
        rCtx.stroke();
      } else {
        currentTrail = [];
      }

      for (const target of targets) {
        if (target.y_mm <= 0) continue;
        // The map projects Y only. Offset the slots visually so dots at the same depth stay visible.
        const depth = target.y_mm / 1000;
        const x = originX + (target.slot - 2) * 16;
        const y = originY + Math.min(depth, 3.8) * scale;
        const state = statesBySlot.get(target.slot)?.state;
        rCtx.fillStyle = delayed ? '#fbbf24' :
          state === 'ALARM_TRIGGERED' ? '#ef4444' :
          state === 'SUSPECTED_FALL' ? '#f59e0b' : '#10b981';
        rCtx.beginPath();
        rCtx.arc(x, y, 7, 0, Math.PI * 2);
        rCtx.fill();
        rCtx.font = 'bold 11px JetBrains Mono';
        const label = `S${target.slot} · Y ${depth.toFixed(2)}m` + (delayed ? ' · trễ' : '');
        if (target.slot === 2) {
          rCtx.fillText(label, x - 12 - rCtx.measureText(label).width, y + 4);
        } else {
          rCtx.fillText(label, x + 12, y + (target.slot === 3 ? 17 : 4));
        }
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

      function plot(field, color, width) {
        tCtx.strokeStyle = color;
        tCtx.lineWidth = width;
        tCtx.beginPath();
        let hasPrevious = false;
        historyData.forEach((point, index) => {
          if (point === null) {
            hasPrevious = false;
            return;
          }
          const x = paddingLeft + (index / (maxHistoryPoints - 1)) * graphW;
          const value = Math.max(0, Math.min(maxZ, point[field]));
          const y = h - paddingBottom - (value / maxZ) * graphH;
          if (hasPrevious) tCtx.lineTo(x, y);
          else tCtx.moveTo(x, y);
          hasPrevious = true;
        });
        tCtx.stroke();
      }

      plot('z', '#38bdf8', 2.5);
      plot('v', '#fbbf24', 1.8);
    }

    // Connect to Server-Sent Events (SSE)
    const evtSource = new EventSource('/events');
    let pendingUpdate = null;
    let pendingAlarm = false;
    let receivedAlarmCount = null;
    let renderScheduled = false;

    evtSource.onmessage = function(e) {
      pendingUpdate = JSON.parse(e.data);
      const alarmCount = pendingUpdate.alarms?.length ?? 0;
      pendingAlarm ||= receivedAlarmCount !== null && alarmCount > receivedAlarmCount;
      receivedAlarmCount = alarmCount;
      if (renderScheduled) return;
      renderScheduled = true;
      requestAnimationFrame(() => {
        renderScheduled = false;
        updateUI(pendingUpdate, pendingAlarm);
        pendingUpdate = null;
        pendingAlarm = false;
      });
    };

    let prevAlarmCount = 0;

    function updateUI(data, newAlarm = false) {
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

      const mlMode = data.detector_mode === 'ML_2S_FSM';
      const modelName = data.model_name || 'Random Forest';
      document.getElementById('detector-mode').innerText = mlMode ?
        modelName + ' 2 giây + FSM' : 'FSM theo ngưỡng';
      if (data.runtime_config) {
        const cfg = data.runtime_config;
        let status = ' · H=' + cfg.h_mount_m.toFixed(2) + 'm';
        if (cfg.height_sync_status === 'error' || cfg.height_sync_status === 'waiting')
          status += ' · Chưa đồng bộ chiều cao ESP32';
        if (Math.abs(cfg.h_mount_m - cfg.calibration_h_mount_m) > 0.001)
          status += ' · Chưa kiểm chứng ngưỡng ở độ cao này';
        document.getElementById('detector-mode').innerText += status;
      }

      // Time
      document.getElementById('current-time-text').innerText = `${data.t_s.toFixed(1)}s`;

      const targets = data.raw_targets || [];
      const delayed = data.note === 'BACKLOG_EXCEEDED' || data.note === 'PC_ANALYSIS_DELAY';
      const statesBySlot = new Map((data.target_states || []).map(target => [target.slot, target]));
      const stateLabels = {
        MONITORING: 'Giám sát', SUSPECTED_FALL: 'Nghi ngã', ALARM_TRIGGERED: 'Cảnh báo ngã',
      };
      document.getElementById('radar-target-states').innerText = targets.map(target => {
        const track = statesBySlot.get(target.slot);
        const location = `S${target.slot} · Y ${(target.y_mm / 1000).toFixed(2)} m`;
        if (!track) return location + ' · Khung đến trễ';
        const scoreLabel = modelName.startsWith('SVM RBF') ? 'Điểm SVM' : 'Điểm AI';
        const score = mlMode ? (track.ml_score == null ? ' · Đang gom khung' :
          ` · ${scoreLabel} ${track.ml_score.toFixed(2)}`) : '';
        return `${location} · Z ${track.z_est_m.toFixed(2)} m · ${stateLabels[track.state]}${score}`;
      }).join('\\n');
      const hasTrack = data.slot != null;
      const hasFrame = Number.isFinite(data.backlog_ms);
      const timing = `Hàng đợi ESP32: ${Math.round(data.backlog_ms)} ms` +
        (Number.isFinite(data.pc_wait_ms) ? ` · Chờ trên PC: ${Math.round(data.pc_wait_ms)} ms` : '');
      const frameNote = delayed ? timing + ' · Tạm dừng phân tích' :
        hasTrack ? timing :
        hasFrame ? 'Radar chưa thấy mục tiêu' :
        'Đang chờ khung radar';

      document.getElementById('val-z').innerText = hasTrack ? `${data.z_est_m.toFixed(2)} m` : '—';
      document.getElementById('val-v').innerText = hasTrack ? `${data.v_mps.toFixed(2)} m/s` : '—';
      document.getElementById('val-xy').innerText = hasTrack ?
        `S${data.slot} · X: ${Math.round(data.x_mm)} | Y: ${Math.round(data.y_mm)}` : '—';

      const dist = Math.hypot(data.x_mm, data.y_mm) / 1000.0;
      document.getElementById('sub-dist').innerText = hasTrack ?
        `Cự ly cách radar: ${dist.toFixed(2)} m` : 'Cự ly: —';
      document.getElementById('val-slot').innerText = targets.length ?
        `${targets.length} MỤC TIÊU` : hasFrame ? 'KHÔNG CÓ' : '—';
      document.getElementById('val-frame-info').innerText = frameNote;

      const posture = document.getElementById('posture-tag');
      const postureNames = {
        STAND: 'ĐỨNG', SIT: 'NGỒI', SIT_OR_BEND: 'NGỒI / CÚI',
        BEND: 'NGHI CÚI (đang theo dõi)', LYING: 'Ở THẤP / NẰM',
      };
      if (!hasTrack) {
        posture.innerText = 'Chưa có tư thế hợp lệ';
      } else if (data.posture_mode !== 'old' && data.posture_label) {
        posture.innerText = postureNames[data.posture_label] || 'Chưa rõ tư thế';
      } else if (data.z_est_m >= 1.0) {
        posture.innerHTML = '<span class="badge badge-online">ĐỨNG THẲNG (≥1.0m)</span>';
      } else if (data.z_est_m >= 0.48) {
        posture.innerHTML = '<span class="badge">NGỒI / CÚI (0.48–1.0m)</span>';
      } else {
        posture.innerHTML = '<span class="badge badge-offline">SÁT SÀN NHÀ (<0.48m)</span>';
      }

      // FSM Banner
      const banner = document.getElementById('status-banner');
      const bTitle = document.getElementById('banner-title');
      const bDesc = document.getElementById('banner-desc');
      const cWrap = document.getElementById('countdown-wrap');
      const pBar = document.getElementById('progress-bar');

      if (!hasTrack) {
        banner.className = 'banner-monitoring';
        bTitle.innerText = delayed ? 'DỮ LIỆU RADAR ĐẾN TRỄ' : 'ĐANG CHỜ MỤC TIÊU HỢP LỆ';
        bDesc.innerText = frameNote;
        cWrap.style.display = 'none';
      } else if (data.state === 'MONITORING') {
        banner.className = 'banner-monitoring';
        bTitle.innerText = '🟢 HỆ THỐNG ĐANG GIÁM SÁT (MONITORING)';
        bDesc.innerText = `Đang giám sát ${statesBySlot.size} mục tiêu. Đồ thị đang hiển thị S${data.slot}.`;
        cWrap.style.display = 'none';
      } else if (data.state === 'SUSPECTED_FALL') {
        banner.className = 'banner-suspected';
        bTitle.innerText = `🟡 S${data.slot} NGHI NGÃ - ĐANG XÁC MINH NẰM SÀN (${data.hold_time_s.toFixed(1)}s / 8.0s)`;
        bDesc.innerText = mlMode ? 'Mô hình nghi ngã. FSM đang xác nhận mục tiêu tiếp tục ở sát sàn.' : 'Phát hiện hạ thấp nhanh. FSM đang xác nhận mục tiêu tiếp tục ở sát sàn.';
        cWrap.style.display = 'block';
        const pct = Math.min(100, (data.hold_time_s / 8.0) * 100);
        pBar.style.width = `${pct}%`;
        playBeep(440, 0.08); // warning ping
      } else if (data.state === 'ALARM_TRIGGERED') {
        banner.className = 'banner-alarm';
        const alarmSlots = [...statesBySlot.values()]
          .filter(track => track.state === 'ALARM_TRIGGERED').map(track => `S${track.slot}`);
        bTitle.innerText = `🚨 CẢNH BÁO TÉ NGÃ · ${alarmSlots.join(', ')}`;
        bDesc.innerText = 'Đã phát hiện dấu hiệu ngã và xác nhận mục tiêu ở sát sàn trong 8 giây.';
        cWrap.style.display = 'none';
        playBeep(980, 0.3); // loud emergency siren
      }

      if (primarySlot !== data.slot) {
        primarySlot = data.slot;
        currentTrail = [];
        if (historyData.length > 0 && historyData[historyData.length - 1] !== null) historyData.push(null);
      }
      if (hasFrame) {
        historyData.push(hasTrack ? { z: data.z_est_m, v: data.v_mps } : null);
        if (historyData.length > maxHistoryPoints) historyData.splice(0, historyData.length - maxHistoryPoints);
      }

      renderRadar(targets, statesBySlot, data.slot, delayed);
      renderTimeline();

      if (newAlarm && data.state !== 'ALARM_TRIGGERED') playBeep(980, 0.3);

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
            <td class="mono">${a.drop_rate_mps == null ? '—' : a.drop_rate_mps + ' m/s'}</td>
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

def put_latest(target_queue, item):
    """Push without blocking a producer, replacing the oldest item if full."""
    try:
        target_queue.put_nowait(item)
    except queue.Full:
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass  # The consumer took it since put_nowait reported full.
        target_queue.put_nowait(item)


def broadcast(payload: dict):
    with subscribers_lock:
        for q in subscribers:
            put_latest(q, payload)

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

            q = queue.Queue(maxsize=1)
            with detector_lock:
                init_data = dict(last_frame_info)
                init_data['tcp_connected'] = tcp_connected
                init_data['alarms'] = list(alarm_history)
                with subscribers_lock:
                    subscribers.append(q)
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
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
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
                global_detector.reset_stream()
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
        global_detector.reset_stream()

    # Phase 1: Standing upright for 2 seconds (Z = 1.50m)
    t_start = time.time()
    for _ in range(25):
        t_us = int((time.time() - t_start) * 1e6)
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

def process_frame(t_us: int, active_list: list[dict], backlog_ms: float = 0.0,
                  simulated: bool = False, source=None, *, pc_wait_ms=0.0,
                  skipped_frame=False):
    global last_frame_info, last_detector_source
    with detector_lock:
        if simulated:
            source = "simulation"
        if source != last_detector_source or skipped_frame:
            global_detector.reset_stream()
            for detector in posture_detectors.values():
                detector.reset()
            last_detector_source = source
        summary, alarms = global_detector.update(t_us, active_list, backlog_ms=backlog_ms + pc_wait_ms)
        valid_slots = set()
        for track in summary.get('target_states', []):
            slot = track['slot']
            valid_slots.add(slot)
            if posture_mode == 'data4':
                label = posture_detectors[slot].update(t_us / 1e6, track['z_est_m'])
            elif posture_mode == 'data3':
                label = height_posture(track['z_est_m'], posture_config['low_m'], posture_config['high_m'])
            else:
                label = old_posture(track['z_est_m'])
            track['posture_label'] = label
            track['posture_provisional'] = label == 'BEND'
            if slot == summary['slot']:
                summary['posture_label'] = label
        for slot, detector in posture_detectors.items():
            if slot not in valid_slots:
                detector.reset()
        summary['posture_mode'] = posture_mode
        if summary['note'] == 'BACKLOG_EXCEEDED' and backlog_ms <= MAX_BACKLOG_MS:
            summary['note'] = 'PC_ANALYSIS_DELAY'
        for alarm in alarms:
            alarm_history.append(alarm)
            print("\n" + "="*70)
            print(f"🚨 [CẢNH BÁO TÉ NGÃ!] ALARM TRIGGERED! (S{alarm['slot']}, t={alarm['alarm_time_s']}s, Latency={alarm['latency_s']}s)")
            print("="*70 + "\n")
            sys.stdout.write('\a')
            sys.stdout.flush()

        summary['raw_targets'] = active_list
        summary['model_name'] = ml_model_name
        summary['runtime_config'] = dict(runtime_config)
        summary['backlog_ms'] = backlog_ms
        summary['pc_wait_ms'] = pc_wait_ms
        summary['tcp_connected'] = tcp_connected or simulated
        summary['alarms'] = list(alarm_history)
        last_frame_info = summary
        broadcast(summary)

    publish_mqtt(summary, alarms)


# ---------------- MQTT Cloud (xem tren dien thoai tu bat ky dau) ----------------
mqtt_pub: MqttPublisher | None = None
_mqtt_last = {'t': 0.0, 'state': None}


def publish_mqtt(summary: dict, alarms: list[dict]):
    """Throttled publish: <= 4 msg/s for live state, immediate on state change or alarm."""
    if mqtt_pub is None:
        return
    now = time.time()
    changed = summary['state'] != _mqtt_last['state']
    if changed or alarms or now - _mqtt_last['t'] >= 0.25:
        _mqtt_last['t'], _mqtt_last['state'] = now, summary['state']
        mqtt_pub.publish('state', {
            't': summary['t_s'], 's': summary['state'], 'z': summary['z_est_m'],
            'v': summary['v_mps'], 'x': summary['x_mm'], 'y': summary['y_mm'],
            'slot': summary['slot'], 'h': summary['hold_time_s'],
            'c': summary['tcp_connected'], 'n': summary['note'],
            'na': len(summary['alarms']),
        })
    for alarm in alarms:
        payload = dict(alarm, wall_time=dt.datetime.now().strftime('%H:%M:%S %d/%m/%Y'))
        mqtt_pub.publish('alarm', payload)
        mqtt_pub.publish('last_alarm', payload, retain=True)

class LiveWebRecorder(receiver.Recorder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.analysis_queue = queue.Queue(maxsize=4)
        self.analysis_thread = threading.Thread(target=self.analyze_frames, daemon=True)
        self.analysis_thread.start()

    def record(self, obj: object) -> tuple[str, bool]:
        global tcp_connected
        received_at = time.monotonic()
        tcp_connected = True
        ack, res = super().record(obj)
        if res:
            # Recorder has already validated, decoded and persisted this frame.
            put_latest(self.analysis_queue, (self.total, received_at, obj, self.latest_targets))
        return ack, res

    def analyze_frames(self):
        last_frame_number = 0
        while True:
            item = self.analysis_queue.get()
            if item is None:
                return
            frame_number, received_at, record, targets = item
            active_list = [
                {'slot': slot, 'x_mm': target['x_mm'], 'y_mm': target['y_mm'],
                 'v_mps': target['speed_cms'] / 100.0}
                for slot, target in enumerate(targets, 1) if target['active']
            ]
            backlog_ms = (record["sent_us"] - record["t_us"]) / 1000.0
            process_frame(record["t_us"], active_list, backlog_ms=backlog_ms,
                          source=(record["device_id"], record["boot_id"]),
                          pc_wait_ms=(time.monotonic() - received_at) * 1000,
                          skipped_frame=frame_number != last_frame_number + 1)
            last_frame_number = frame_number

    def close(self):
        put_latest(self.analysis_queue, None)
        self.analysis_thread.join(timeout=2.0)
        super().close()

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
    parser.add_argument("--model", type=Path, help="Use a trained 2-second SVM or Random Forest model")
    parser.add_argument("--fsm-config", type=Path,
                        default=Path(__file__).parent / 'fsm_parameters_1p7m.json')
    parser.add_argument("--height", type=float, help="Actual PC mounting height in metres (1.00 to 2.50)")
    parser.add_argument("--esp32-url", help="Read H_mount from ESP32 /api/state, e.g. http://radar.local")
    parser.add_argument('--posture-mode', choices=('old','data3','data4'), default='old',
                        help='Old thresholds, data-derived 3 groups, or experimental causal 4 groups')
    parser.add_argument('--posture-config', type=Path,
                        default=Path(__file__).parent/'posture_config_1p7m.json')
    parser.add_argument("--mqtt", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable/disable MQTT publishing (off by default in model mode)")
    parser.add_argument("--mqtt-host", default="broker.hivemq.com")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-topic", default="doan2/hoangduy1812/ld2450",
                        help="Topic goc; trang dien thoai phai dung cung topic nay")
    args = parser.parse_args()

    global mqtt_pub, global_detector, ml_model_name, posture_mode, posture_config, posture_detectors
    posture_mode = args.posture_mode
    if posture_mode != 'old':
        try:
            posture_config = json.loads(args.posture_config.read_text(encoding='utf-8'))
            if set(posture_config) != {'low_m','high_m','bend_drop_m','bend_timeout_s'}:
                raise ValueError('Invalid posture config keys')
            if not (0 < posture_config['low_m'] < posture_config['high_m'] < 1.7
                    and posture_config['bend_drop_m'] > 0 and posture_config['bend_timeout_s'] > 0):
                raise ValueError('Invalid posture thresholds')
            posture_detectors = {slot: PostureFSM(**posture_config) for slot in (1,2,3)}
        except (OSError,ValueError,TypeError) as exc:
            parser.error(f'Invalid posture config: {exc}')
    try:
        settings = load_settings(args.fsm_config)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(f'Invalid FSM config: {exc}')
    if args.height is not None:
        if not 1.0 <= args.height <= 2.5:
            parser.error('--height must be between 1.00 and 2.50 m')
        settings['h_mount_mm'] = args.height * 1000.0
    runtime_config.update(h_mount_m=settings['h_mount_mm']/1000.0,
                          height_source='manual' if args.height is not None else 'config',
                          height_sync_status='waiting' if args.esp32_url else 'manual')
    global_detector = MultiTargetFallDetector(**settings)
    if args.model is not None:
        import joblib

        bundle = joblib.load(args.model)
        model = bundle["model"]
        try:
            feature_set = feature_set_from_bundle(bundle)
        except (KeyError, TypeError, ValueError) as exc:
            parser.error(str(exc))

        classifier = bundle.get("classifier", "rf")
        if classifier == "svm" and callable(getattr(model, "decision_function", None)):
            ml_model_name = "SVM RBF"

            def score_window(t_us, features):
                return model.decision_function([features])[0]
        elif classifier == "rf" and callable(getattr(model, "predict_proba", None)):
            ml_model_name = "Random Forest"

            def score_window(t_us, features):
                return model.predict_proba([features])[0, 1]
        else:
            parser.error("The saved model must be a supported SVM or Random Forest bundle.")

        ml_model_name += f" ({len(FEATURE_SETS[feature_set])} đặc trưng)"
        global_detector = MultiTargetFallDetector(
            **settings, window_score=score_window,
            ml_threshold=bundle["threshold"], feature_set=feature_set,
        )
    last_frame_info.update(global_detector.get_summary(0, note="Chờ kết nối ESP32..."))
    last_frame_info['model_name'] = ml_model_name
    last_frame_info['runtime_config'] = dict(runtime_config)
    session_stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    config_log_dir = args.out / f'web_{session_stamp}'
    rec = LiveWebRecorder(config_log_dir, "P01", "WEB_TRIAL", "live_dashboard", "Web Dashboard run", False)
    def log_configuration():
        record = {'wall_time': dt.datetime.now().isoformat(), **runtime_config,
                  'fsm_settings_at_start': settings,
                  'posture_mode': posture_mode, 'posture_config': posture_config,
                  'model': str(args.model) if args.model else None}
        with (config_log_dir/'configuration_changes.ndjson').open('a',encoding='utf-8') as f:
            f.write(json.dumps(record,ensure_ascii=False)+'\n')
    log_configuration()
    def on_height(value):
        with detector_lock:
            changed = apply_height(global_detector, value)
            if changed:
                for detector in posture_detectors.values():
                    detector.reset()
            changed_source = runtime_config['height_source'] != 'esp32'
            runtime_config.update(h_mount_m=value,height_source='esp32',height_sync_status='ok')
            if changed or changed_source:
                log_configuration()
                if changed:
                    print(f'[CONFIG] ESP32 H_mount={value:.2f} m; reset all slot windows/FSM.')
            last_frame_info['runtime_config'] = dict(runtime_config)
    def on_height_error(message):
        with detector_lock:
            runtime_config['height_sync_status'] = 'error'
            last_frame_info['runtime_config'] = dict(runtime_config)
    height_sync = HeightSync(args.esp32_url,on_height,on_height_error).start() if args.esp32_url else None
    use_mqtt = args.mqtt if args.mqtt is not None else args.model is None
    if use_mqtt:
        mqtt_pub = MqttPublisher(args.mqtt_host, args.mqtt_port, args.mqtt_topic).start()
        print(f"[MQTT] Gui trang thai len {args.mqtt_host} | topic: {args.mqtt_topic}/state, /alarm")

    # 1. Start HTTP Server in background thread
    http_thread = threading.Thread(target=start_http_server, args=("0.0.0.0", args.web_port), daemon=True)
    http_thread.start()
    web_url = f"http://localhost:{args.web_port}"

    print("\n" + "="*80)
    print("[WEB GUI] GIAO DIEN WEB DASHBOARD DA KHOI CHAY THANH CONG!")
    print(f"   * Truy cap Dashboard tai trinh duyet: {web_url}")
    print(f"   * Dang lang nghe ket noi TCP tu ESP32 tai cong: {args.tcp_port}")
    print(f"   * Mô hình: {ml_model_name + ' 2 giây + FSM' if ml_model_name else 'FSM theo ngưỡng'}")
    print(f"   * FSM config: {args.fsm_config}; H_mount khởi tạo={runtime_config['h_mount_m']:.2f} m")
    print(f"   * Posture mode: {posture_mode}; ngưỡng tư thế: {posture_config}")
    if args.esp32_url:
        print(f"   * Đồng bộ H_mount từ {args.esp32_url.rstrip('/')}/api/state")
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
    try:
        receiver.serve("0.0.0.0", args.tcp_port, rec)
    except KeyboardInterrupt:
        print("\n[DỪNG HỆ THỐNG] Đóng kết nối.")
    finally:
        if height_sync is not None:
            height_sync.close()
        rec.close()

if __name__ == "__main__":
    raise SystemExit(main())
