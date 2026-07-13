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

## Appliance mode: autostart + supervisor (v1.58.8)

The launcher (`run-windows.ps1` / `start-kaliv.bat`) runs in the foreground and
stops when you close it or reboot. For a rig that just stays up:

1. Put `modelrig-supervisor-windows-x64.exe` (from the release) in the ModelRig
   root, next to `modelrig-server-windows-x64.exe`, with the worker exe in `worker/`.
2. Run once, elevated:
   `powershell -ExecutionPolicy Bypass -File scripts\kaliv-autostart.ps1`

The supervisor starts the worker + server at logon and restarts either one if it
exits or stops answering `/healthz`. Child output goes to `logs\worker.log` and
`logs\server.log` (rotated at 20 MB). Manage it with:

- `Start-ScheduledTask -TaskName KalivSupervisor` (start now, no reboot)
- `Stop-ScheduledTask  -TaskName KalivSupervisor` (stop; no restart until next logon)
- `Get-ScheduledTask   -TaskName KalivSupervisor` (status)

Tunables are flags on the exe (`-interval`, `-max-fails`, `-log-max-mb`, exe/health
paths); run `modelrig-supervisor-windows-x64.exe -h` for all of them.

## Controlled update with rollback (v1.58.9)

`modelrig-updater-windows-x64.exe` (from the release, kept in the ModelRig root)
updates the rig to the latest release safely:

- Check only: `modelrig-updater-windows-x64.exe -check` — prints whether a newer
  release exists and changes nothing.
- Update: `modelrig-updater-windows-x64.exe` — downloads the new server/worker/
  supervisor exes, backs up the current ones to `backups\exe-<version>\`, stops
  the supervisor, swaps, restarts, and verifies `/healthz` reports the new
  version. If the new version does NOT become healthy, it rolls back to the
  backup automatically.

Run it elevated (it stops/starts the KalivSupervisor task). The current version
is read from the running server; pass `-current 1.58.8` if the server is down.

### Resource warnings (v1.58.12)

The supervisor also watches for resource pressure and logs a rate-limited WARNING
(to `logs\server.log`/console) when free disk drops below `-min-free-gb` (default
5 GB) or VRAM passes `-vram-warn-pct` (default 95%) -- so a rig that is quietly
filling its disk or pinning its GPU says so before a pull or a model load fails.
