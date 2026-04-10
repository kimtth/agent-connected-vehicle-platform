@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_webapp_deploy.ps1" %*