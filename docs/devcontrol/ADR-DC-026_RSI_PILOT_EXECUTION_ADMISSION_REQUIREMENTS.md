# ADR-DC-026 — Exact-bound requirements before one DC-L16 pilot execution admission

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Kontekst

ADR-DC-025 kan udstede et crash-durable, host-local receipt for at én exact
ADR-DC-024 pilot-start authorization er blevet forbrugt. Receiptet er bevidst
ikke execution authority: `task_execution_authorized=false`,
`product_pilot_started=false` og alle publication/activation-authorities er
fortsat false.

Et durable receipt er nødvendigt replay-evidence, men efter serialization/reload
har det ikke længere den live transaction provenance, som fandtes under selve
consume-transaktionen. Derfor må et senere execution-led ikke fortolke et
receipt som en latent executor-capability eller genbruge historisk trust uden
frisk host-side kontrol.

## Beslutning

ADR-DC-026 indfører et deterministisk, inert requirements-manifest for en senere
separat DC-L16 execution-admission. Manifestet kan kun afledes fra ét exact,
replay-valid ADR-DC-025 `PilotStartConsumptionReceipt`.

Det observerer ingen host-state, aktiverer ingen product code, registrerer ingen
kommandoer og udfører ingen task. Det beskriver kun de egenskaber, som et senere
admission-led mindst skal bevise før én manual lokal pilot-execution kan
overvejes.

### 1. Exact ADR-DC-025 receipt er eneste input

Manifestet indlejrer hele receiptet og binder separat:

- receiptets canonical SHA-256;
- original ADR-DC-024 authorization-proof SHA-256;
- fresh ADR-DC-024 verification-proof SHA-256 fra consume-transaktionen;
- detached ADR-DC-024 signature SHA-256;
- detached ADR-DC-023 preflight-signature SHA-256;
- signed `start_nonce_sha256`;
- canonical host-ledger-root digest;
- repository, base SHA og requested-main SHA;
- trial ID og operator surface;
- exact selected pilot task;
- workspace-root digest;
- det menneskeligt signerede local-commit scope.

Nested receipt deserialiseres gennem ADR-DC-025's egen fail-closed constructor,
og alle duplicated bindings krydstjekkes mod det indlejrede receipt. Rebinding
af receipt, nonce, signatures, task, workspace eller source scope fejler lukket.

### 2. Durable evidence er ikke live admission authority

Et ADR-DC-025 receipt må bruges til at definere requirements både direkte efter
consume og efter durable reload. Det er tilsigtet: requirements er data, ikke
authority.

Et reloaded receipt genvinder ikke live transaction provenance. ADR-DC-026
kræver derfor eksplicit, at et senere admission-led:

- revaliderer den canonical host-ledger;
- re-verificerer upstream ADR-DC-023/024 authority frisk;
- kræver live ADR-DC-025 consumption-receipt provenance igen ved admission.

Det sidste krav kan opfyldes af det originale live receipt i samme trusted
transaction eller af en senere, separat recovery-boundary, der eksplicit
reetablerer tilsvarende live provenance. ADR-DC-026 implementerer ikke en sådan
recovery-boundary. Efter reload alene skal admission derfor fejle lukket.

Manifestets indlejrede durable receipt og dets historiske
`transaction_authenticated`-tilstand må aldrig bruges som erstatning for denne
live admission-time provenance.

### 3. Execution-admission requirements

Et senere admission-led skal mindst bevise alle følgende krav som sande:

1. `host_ledger_revalidation_required=true`;
2. `fresh_upstream_authority_reverification_required=true`;
3. `live_consumption_receipt_required_at_admission=true`;
4. `allowlisted_task_registry_required=true`;
5. `exact_selected_task_required=true`;
6. `canonical_workspace_revalidation_required=true`;
7. `feature_flag_enabled_observation_required=true`;
8. `native_windows_isolation_required=true`;
9. `trusted_git_closure_required=true`;
10. `kill_switch_armed_required=true`;
11. `revoke_not_asserted_required=true`;
12. `restart_recovery_proof_required=true`;
13. `network_write_blocked_required=true`;
14. `credentials_absent_required=true`;
15. `unattended_cadence_forbidden=true`;
16. `general_shell_forbidden=true`;
17. `model_defined_commands_forbidden=true`;
18. `exact_source_base_head_binding_required=true`;
19. `exact_toolchain_binding_required=true`;
20. `execution_receipt_required=true`;
21. `manual_operator_invocation_required=true`.

Kravene er conjunctive. Et senere admission-led må ikke slå ét krav fra som en
"optional" eller degraded mode.

### 4. Human scope må ikke udvides

`selected_pilot_task_id`, operator surface, workspace-root digest og
`local_commits_allowed_by_human_scope` kommer transitivt fra den menneskeligt
signerede ADR-DC-024/021/016 chain via ADR-DC-025 receiptet.

ADR-DC-026 giver ikke local-commit authority, selv når human scope historisk
tillod local-only commits. Feltet bevarer kun den øvre signed grænse, som et
senere separat led højst kan indsnævre — aldrig udvide.

### 5. Explicit authority stop

Et valid requirements-manifest skal holde:

- `execution_admission_observed=false`;
- `task_execution_authorized=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- `remote_write_authorized=false`;
- `push_authorized=false`;
- `pr_mutation_authorized=false`;
- `merge_authorized=false`;
- `release_authorized=false`;
- `deploy_authorized=false`;
- `production_activation_authorized=false`.

Authority er kun:

`dc-l16-pilot-execution-admission-requirements-only`

Manifestet er derfor ikke en Start-knap, executor-ticket eller capability. Det
kan kun fortælle et senere admission-led, hvad der skal bevises.

## Fail-closed krav

ADR-DC-026 skal mindst afvise:

1. andre objekttyper end exact ADR-DC-025 receipt;
2. receipt med invalid canonical replay identity;
3. receipt uden committed host replay guard, consumed/start-receipt state eller
   den forventede ADR-DC-025 authority;
4. receipt der hævder task execution, product start, local commit eller nogen
   remote/publication/activation authority;
5. receipt/signature/nonce/ledger/task/workspace/source rebinding;
6. et requirements-felt, der forsøges sat false;
7. et runtime/execution/publication/activation-felt, der forsøges sat true;
8. malformed nested receipt ved deserialisering;
9. ukendt repository eller ugyldige SHA/identifier-formater.

## Test- og integrationsstrategi

Den adversarielle ADR-DC-026 support-contract køres gennem den eksisterende
Stage-B support-chain, så den låste top-level testinventory ikke udvides med et
nyt selvstændigt workflow-entrypoint.

Kontrakten beviser bl.a.:

- exact embedded receipt-binding og canonical roundtrip;
- at alle 21 requirements er obligatorisk true;
- at alle authority-expansion fields er obligatorisk false;
- at manifest-roundtrip ikke kan bevare ADR-DC-025 live transaction provenance;
- at et durable/reloaded receipt fortsat kun kan definere requirements;
- at en senere admission eksplicit kræver live receipt provenance igen;
- at forged execution-authority i receiptet afvises;
- at normal `modelrig_command_catalog()` fortsat er tom;
- at requirements-modulet ikke indeholder subprocess/socket/network/GitHub
  execution paths.

## Ikke i denne slice

ADR-DC-026 tilføjer ikke:

- product feature-flag enable/read;
- host-ledger revalidation implementation;
- upstream signature re-verification implementation;
- live-receipt recovery/re-authentication implementation;
- task registry eller executor;
- general shell eller model-defined commands;
- workspace mutation eller local commit;
- network credentials eller remote transport;
- Git/GitHub write;
- merge/release/deploy;
- faktisk pilot-start eller task execution;
- production activation.

Et senere ADR-led skal implementere den egentlige execution-admission og bevise
alle kravene ovenfor uden at udvide den signerede human scope.
