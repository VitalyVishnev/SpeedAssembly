@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_gui_exe.ps1" %*
