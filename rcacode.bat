@echo off
setlocal
cd /d "%~dp0"
python interface/CLI.py %*
