# Agent 3 read-only developer-pilot (T-020)

Denne pilot måler den eksperimentelle Agent 3-sti på den fysiske rig uden at
aktivere den i normal chat og uden at tillade write-tools.

## Hvad den beviser

- 20 frosne danske tasks bliver planlagt gennem den server-authoritative
  `/api/v1/experimental/agent3/plan`-sti.
- Hver plan skal matche den forventede read-only plan byte-for-byte på
  tool/args/risk, før dens engangs-`plan_id` må bruges.
- Preview-, start- og durable capability-receipts skal være tilladte, uden
  blockers og med `production_activation=false`.
- Run, steps og events skal vise et fuldt read-only forløb uden confirmation,
  skjult write eller retry.
- Outcome-answer genereres lokalt som preview. Rå tool-resultater og svar gemmes
  ikke i rapporten; kun hashes, længder og typed outcomes.
- En separat stop/fallback-probe stopper en to-trins read-plan efter første step
  og sender den præcis samme user-turn gennem normal `/api/v1/chat`.

Piloten kræver en frisk Agent 3-rig-validation, der er markeret
`eligible_for_developer_preview`, og den binder rapporten til:

- ren checkout og præcis Git commit-SHA;
- `VERSION`;
- workerens runtime-rapporterede code fingerprint;
- planner-, answer- og fallback-model.

## Sikkerhedsgrænser

Harnessen:

- kalder aldrig write-, destructive-, admin- eller desktop-tools;
- starter aldrig en plan, hvis modeloutputtet afviger fra den frosne read-plan;
- confirmer aldrig en handling;
- kalder aldrig retry eller replan-apply;
- ændrer ikke feature flags, routing eller produktionsaktivering;
- gemmer ikke bearer-token, prompts, rå svar, tool-resultater eller HTTP-fejltekst.

En task-fejl stopper ikke de øvrige målinger. Fejlen registreres kun som type og
SHA-256, så rapporten både er komplet og redacted.

## Forudsætninger

1. Kør fra en ren checkout af den candidate, der faktisk er installeret på riggen.
2. Backend og worker skal køre med `KALIV_AGENT3_ENABLED=1`.
3. Den aktuelle rig-validation skal være frisk og matche version + code fingerprint.
4. Tools skal være enabled, og modellerne skal være installeret lokalt.
5. Sæt paired-device-token i miljøet; skriv det aldrig på kommandolinjen.

## Kørsel på Windows-riggen

```powershell
$env:MODELRIG_TOKEN = "<paired device token>"

python scripts/agent3_readonly_pilot.py `
  --base-url http://127.0.0.1:8080 `
  --planner-model qwen3:14b `
  --answer-model qwen3:14b `
  --fallback-model qwen3:14b `
  --report validation/agent3-readonly-pilot-latest.json
```

Exit code:

- `0`: alle 20 tasks samt stop/fallback bestod;
- `1`: der blev skrevet en komplet rapport, men mindst én gate fejlede;
- `2`: harnessen kunne ikke etablere troværdig candidate/status/task-set evidens.

## Review og evidens

Den rullende `*-latest.json` er ignoreret af Git. Før T-020 kan lukkes:

1. Kontrollér `success=true`, `20/20`, `error_types={}` og stop/fallback-success.
2. Kontrollér candidate Git SHA, version og code fingerprint mod den installerede
   release/candidate.
3. Kontrollér at alle task-resultater har `route=rig_tools_local`, nul skjulte
   confirmation-events og kun read-tools.
4. Kontrollér latency, replans, retries og eventforløb for outliers.
5. Kopiér den manuelt reviewede rapport til et dateret filnavn, fx
   `validation/agent3-readonly-pilot-2026-07-19.json`, før den eventuelt committes.

Kode- og testdelen kan forberedes under validation-frysen. Den fysiske rapport er
stadig RIG-evidens og kan ikke erstattes af CI.
