@echo off
cd /d "%~dp0"
py -3.12 web_dashboard.py --model models/fall_svm_6f_2s.joblib --posture-mode data4 --esp32-url http://radar.local --no-mqtt
pause
