@echo off
cd /d "%~dp0"
py -3.12 run_fsm_or_svm.py --esp32-url http://radar.local
pause
