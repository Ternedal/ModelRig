@echo off
cd /d "C:\Users\admin\Desktop\ModelRig-git\validation\stage-a-runtime"
set "MODELRIG_HOST=127.0.0.1"
set "MODELRIG_PORT=8080"
set "MODELRIG_DATA=C:\Users\admin\Desktop\modelrig-data.json"
set "KALIV_AGENT3_ENABLED=1"
"C:\Users\admin\Desktop\ModelRig-git\validation\stage-a-runtime\modelrig-server-stage-a.exe"
