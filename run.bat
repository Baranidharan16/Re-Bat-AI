@echo off
REM One-command start (Windows): backend + built dashboard on http://localhost:8000
cd /d %~dp0backend
if not exist .venv ( py -3 -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python -m app.ml.bootstrap
if not exist ..\frontend\dist\index.html ( pushd ..\frontend & call npm install & call npm run build & popd )
echo RE-BAT AI -^> http://localhost:8000   (API docs: /docs)
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8000/app/live"
uvicorn app.main:app --host 0.0.0.0 --port 8000
