# Running ModelRig

Order matters: **Ollama → worker → backend → pair → clients**.

Copy `modelrig.env.example` to `modelrig.env` and edit. The single most important
line: `MODELRIG_HOST=0.0.0.0` (not `127.0.0.1`) so your phone and other machines
can reach the backend.

## Windows (local dev / homelab)
```powershell
# once: build the backend and install worker deps
go build -C backend -trimpath -o modelrig-server.exe .\cmd\modelrig-server
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
(to `logs\supervisor.log`/console) when free disk drops below `-min-free-gb` (default
5 GB) or VRAM passes `-vram-warn-pct` (default 95%) -- so a rig that is quietly
filling its disk or pinning its GPU says so before a pull or a model load fails.

### Supervisor config (v1.58.13)

The supervisor sets the environment its children run with, so the appliance is
self-bearing. Copy `deploy/modelrig.env.example` to **`modelrig.env`** in the
ModelRig root (next to the exes). The critical line is `MODELRIG_HOST=0.0.0.0` --
without it the server binds to loopback and the phone can't reach it. Point the
supervisor at a different file with `-env <path>` if needed. On every release the
updater now verifies BOTH backend and worker `/healthz` report the new version,
and rolls back if either doesn't.

### Updating the updater itself (one-time)

`modelrig-updater` updates the server, worker and supervisor — but a running exe
can't overwrite itself on Windows, so it does **not** replace itself. An existing
rig therefore keeps running whatever updater version it was installed with. To get
new updater logic (e.g. the 1.58.15 SHA-256 verification), replace
`modelrig-updater-windows-x64.exe` **once, by hand** from the release, while the
updater isn't running. After that, future updates verify checksums.

### Supervisor heartbeat (v1.58.23+)

The supervisor writes `logs\supervisor-heartbeat` every tick. After an update the
updater removes the old heartbeat, restarts, and requires a fresh heartbeat that
then advances -- proving the new supervisor is looping. If that can't be proven,
the update ROLLS BACK. On by default; the path defaults to the install's
`logs\supervisor-heartbeat`.

### Update-transaktion, lock og offline recovery (v1.58.29)

En update er nu én transaktion: `update-transaction.json` i roden skrives før
første ændring — findes den ved næste kørsel, rulles HELE sættet tilbage fra
forsøgets backup-mappe (ingen blandede versioner). Arkiveres som `.last` ved
commit/rollback; `manual_recovery` betyder: supervisor blev IKKE startet, kør
updateren igen eller gendan fra backup-mappen. `updater.lock` holder én instans
ad gangen (slet den manuelt efter et hårdt crash). `modelrig-updater -recover`
reparerer offline uden netværk eller kørende server. Fuldt design: UPDATER_DESIGN.md.

**v1.58.30:** journal-recovery stopper nu selv KalivSupervisor-tasken før
gendannelse og starter den igen efter succes — manuel `-recover` kræver ikke
længere at du stopper noget først. `committed`-journaler (hvor kun arkiv-
renamen fejlede) rulles aldrig tilbage. Forbi `backed_up` kræves backup for
ALLE targets, ellers `manual_recovery` uden at røre noget.

**v1.58.31:** en ulæselig/korrupt journal stopper nu updateren (fail closed) i
stedet for at blive ignoreret; journal-læseren vælger højeste revision af
hovedfil/`.tmp`, så en committet update ikke rulles tilbage efter et crash midt
i journal-skrivningen; og terminale journaler (`committed`/`rolled_back`)
stopper ikke længere en sund kørende rig — kun arkivet færdiggøres.

**v1.58.36:** rollback erklæres først færdig (`rolled_back` arkiveret) når den
gamle runtime er BEVIST oppe — ellers beholdes journalen som `manual_recovery`
og næste updater-kørsel gendanner idempotent. En ulæselig/konfliktende journal
stopper nu hele apparatet konservativt (task + processer) før updateren fejler
lukket; evidensen bevares, ingen automatisk genstart.

**v1.58.37 — atomisk release-flow:** releasen oprettes som **draft** via API,
og git-tagget pushes derefter separat (GitHub opretter ikke tags for drafts —
uden tag-push starter buildet aldrig). CI uploader assets + SHA256SUMS til
draften, verificerer hele asset-listen, og publicerer først derefter
(`--draft=false --latest`). En halvt uploadet release kan aldrig blive synlig
eller samles op af updateren.
