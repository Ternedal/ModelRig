# Running ModelRig

Order matters: **Ollama → worker → backend → pair → clients**.

Copy `modelrig.env.example` to `modelrig.env` and edit. The single most important
line: `MODELRIG_HOST=0.0.0.0` (not `127.0.0.1`) so your phone and other machines
can reach the backend.

## Windows (local dev / homelab)
```powershell
# once: build the backend and install worker deps
go build -o backend\modelrig-server.exe .\backend\cmd\modelrig-server
pip install -r worker\requirements.txt

# run both (binds 0.0.0.0):
powershell -ExecutionPolicy Bypass -File .\deploy\run-windows.ps1
```
`run-windows.ps1` starts the worker, waits, then runs the backend in the
foreground. Ctrl+C stops both. Pair a device from another terminal:
```powershell
.\backend\modelrig-server.exe -pair
```

## Linux (systemd)
```bash
sudo useradd -r -s /usr/sbin/nologin modelrig
sudo mkdir -p /opt/modelrig && sudo cp -r backend worker /opt/modelrig/
sudo cp deploy/modelrig.env.example /opt/modelrig/modelrig.env   # then edit
# build backend + install worker deps into /opt/modelrig as the modelrig user...

sudo cp deploy/modelrig-worker.service deploy/modelrig-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now modelrig-worker modelrig-backend
journalctl -u modelrig-backend -f
```
Edit the unit files' `User`, `WorkingDirectory`, `EnvironmentFile`, and
`ExecStart` paths to match your install (and point `ExecStart` at your venv's
`uvicorn` if you used one).

## Remote access
For access beyond your LAN, put the backend on a **Tailscale** IP and set
`MODELRIG_HOST` to that IP (or keep `0.0.0.0` and firewall to the tailnet). Avoid
exposing the plain-HTTP backend to the public internet; front it with TLS if you
must.

## Smoke-check a running stack
Use the reference CLI (see `../tools/README.md`):
```bash
python tools/modelrig-cli.py --url http://<host>:8080 pair --code XXXX-XXXX
python tools/modelrig-cli.py status
python tools/modelrig-cli.py chat "hello"
```
