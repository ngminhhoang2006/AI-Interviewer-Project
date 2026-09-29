@echo off
start "" powershell -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0setup_windows_gui.ps1" -Mode Uninstall
