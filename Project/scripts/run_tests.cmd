@echo off
set "TEST_LAYER=%~1"
if "%TEST_LAYER%"=="" set "TEST_LAYER=Full"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_tests.ps1" -Layer %TEST_LAYER%
