@echo off
cd /d "%~dp0"
set PARKING_EYE_SLOT_MODEL=runs\segment\train4\weights\best.pt
call .\.venv\Scripts\activate.bat
python -m uvicorn server:app --host 0.0.0.0 --port 8000