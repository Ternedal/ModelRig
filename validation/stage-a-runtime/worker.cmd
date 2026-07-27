@echo off
cd /d "C:\Users\admin\Desktop\ModelRig-git"
set "PYTHONPATH=C:\Users\admin\Desktop\ModelRig-git\worker"
set "PYTHONDONTWRITEBYTECODE=1"
set "KALIV_AGENT3_ENABLED=1"
set "KALIV_TOOLS_ENABLED=1"
set "KALIV_AGENT3_PLANNER_MODEL=qwen3:14b"
set "KALIV_AGENT3_VALIDATION_REPORT=C:\Users\admin\Desktop\ModelRig-git\validation\agent3-rig-validation-latest.json"
python -m uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099
