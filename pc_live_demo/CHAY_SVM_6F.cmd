@echo off
cd /d "%~dp0"
py -3.12 run_svm_6f.py --esp32-url http://radar.local
pause
