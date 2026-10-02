@echo off
cd /d "%~dp0"
python check_runtime.py
if errorlevel 1 exit /b 1
python -m unittest discover -s . -p "test*.py"
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm TranskripTHOR.spec
if errorlevel 1 exit /b 1
