@echo off
REM First run creates a virtualenv and installs dependencies, then starts the server.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env copy .env.example .env
python run.py
