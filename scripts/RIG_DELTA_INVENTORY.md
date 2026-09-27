# Post-cutover rig delta inventory

The first old-rig -> new-rig migration is stateful and fail-closed. After that cutover, the two machines can drift again: new repositories appear, Ollama models are pulled, WSL packages are installed, tools change and local runtime installers add scheduled tasks or services.

`rig-delta-inventory.ps1` is the read-only answer to that problem. It does not migrate anything automatically. It captures comparable manifests on both machines and produces a delta report so each difference can be moved by its owning installer/migration path.

## Safety boundary

The inventory never captures environment-variable values, API keys, tokens, passwords, `.env` contents, BodyRig private/licensed model payload bytes, or arbitrary user documents.

## Capture the old rig

~~~powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rig-delta-inventory.ps1 -Action Capture -Label old-rig -InstallRoot C:\Rig -OutFile D:\RigMigration\old-rig-current.json
~~~

By default it inventories repositories under `C:\Rig\src`, Ollama models, installed Windows applications, WSL distributions plus manually installed apt packages, NVIDIA GPUs/drivers, common runtime tools, Python venvs inside rig repositories, rig-related scheduled tasks/services and top-level `C:\Rig` entries.

Use `-AdditionalRepoRoot C:\Users\admin\Desktop,C:\dev` for code outside the standard layout. Use `-SkipPythonPackages` if `pip freeze` is unnecessary.

## Capture the new rig

~~~powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rig-delta-inventory.ps1 -Action Capture -Label new-rig -InstallRoot C:\Rig -OutFile D:\RigMigration\new-rig-current.json
~~~

## Compare

~~~powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rig-delta-inventory.ps1 -Action Compare -SourceManifest D:\RigMigration\old-rig-current.json -TargetManifest D:\RigMigration\new-rig-current.json -CompareOutFile D:\RigMigration\rig-delta-current.json
~~~

The report separates source-only and target-only repositories, repository HEAD/branch/dirty differences, missing/different Ollama models, WSL and apt-package differences, source-only Windows applications, missing scheduled tasks/services, and source-only rig entries.

## Reconciliation rules

Repository differences should go through Git/GitHub after dirty work is preserved. Ollama models should be pulled by name rather than copying blob stores. WSL packages should be reinstalled with WSL/apt. Windows applications should be reinstalled intentionally. Scheduled tasks/services should be recreated by the owning installer/bootstrap. ModelRig/VoiceRig mutable state should use the existing migration operators, and BodyRig private assets should continue through its explicit parity/provisioning path.
