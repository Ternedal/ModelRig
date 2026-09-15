# ModelRig 2.0.13 Windows human UX review

Review only the JAR shipped in this directory. The receipt recorder verifies its SHA-256 against `REVIEW_AUTHORITY.txt` before recording a decision.

The original #779 observations must all be checked explicitly:

1. **Navigation** — Chat/Agent navigation remains reachable from Settings/pairing.
2. **Window chrome** — only the native Windows minimise/maximise/close controls appear.
3. **Pairing labels** — every pairing/address control has a visible meaningful label.
4. **Token masking** — device token is masked by default and only visible after explicit reveal.
5. **Light mode** — core desktop surfaces remain readable with usable contrast.
6. **Handlingslog** — operator view is structured/human-readable, not a raw key=value dump.
7. **Control Center** — attention/unknown state identifies the affected component/reason.

A PASS receipt is impossible unless all seven switches are supplied. A FAIL receipt may be recorded with failing checks left unset.

Example PASS:

```powershell
.\RECORD_UX_REVIEW.ps1 -Decision PASS -Reviewer "Anders" `
  -Navigation -WindowChrome -PairingLabels -TokenMasking `
  -LightMode -ActionLog -ControlCenter
```

The resulting `HUMAN_UX_REVIEW_RECEIPT.json` does not itself authorize merge, release, physical execution, or production activation. Exact-head software qualification must separately be green.
