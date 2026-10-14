#!/usr/bin/env bash
# One-command start (macOS/Linux): backend + built dashboard on http://localhost:8000
set -e
cd "$(dirname "$0")/backend"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
python -m app.ml.bootstrap
if [ ! -f ../frontend/dist/index.html ] && command -v npm >/dev/null; then (cd ../frontend && npm install && npm run build); fi
echo "RE-BAT AI → http://localhost:8000   (API docs: /docs)"
(sleep 5; (command -v xdg-open >/dev/null && xdg-open http://localhost:8000/app/live) || (command -v open >/dev/null && open http://localhost:8000/app/live)) >/dev/null 2>&1 &
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
