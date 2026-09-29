# BodyRig rig link — Slice D

Denne draft er forbindelseslaget mellem Kaliv og den levende BodyRig-frame-kilde.
Den er stablet på #858, som igen er stablet på den kvalificerede #846-kandidat.

`production_activation=false`.

## Authority

`BodyRigRigLink` har kun to credential-kilder:

1. `BODYRIG_RIG_URL` + `BODYRIG_RIG_TOKEN` fra process environment — Windows
   proof og manuelle renderer-kørsler;
2. Android intent extras `bodyrig_rig_url` + `bodyrig_rig_token` fra den landede
   `KalivBodyBridge`.

Kaliv ejer pairing og credential storage. Kaliv Body/Unity må derfor ikke have
sin egen pairing-form, kalde `/api/v1/pair/claim` eller persistére device-token i
`PlayerPrefs` eller et andet sekundært lager.

En højere-prioriteret source, hvor kun URL eller token findes, eller hvor URL'en
er malformed, er eksplicit authority og **fejler lukket**. Den må ikke falde
videre til intent eller fixture som om kilden var fraværende.

På Android uden env eller intent authority bliver rig-linken unresolved og beder
operatøren starte Kaliv Body fra Kaliv. Der oprettes ingen live frame source.

## Rig-origin

Rig-adressen er en ren absolut `http://` eller `https://` origin med host og
valgfri port. Userinfo, path ud over `/`, query og fragment afvises. Accepteret
værdi normaliseres til `UriPartial.Authority`, fordi frame-source selv appender
`/api/v1/body/frames`.

Tokenet må ikke indgå i logs, receipts, exceptionstekster eller repo-filer.
Resolveren må gerne logge source + normaliseret origin.

## Bootstrap

På Windows/desktop uden env authority bevares den deterministiske fixture-path.
Hvis bare én env-variabel er sat, går bootstrappen gennem resolveren, så partial
configuration fejler lukket.

På Android går bootstrappen altid gennem resolveren. `BodyRigFrameSource`
oprettes først når resolveren har emitteret et valideret `(url, token)`-par.
AR-placement fra #858 forbliver uafhængig og ejer kun avatar-rooten.

## Proof-grænse

`tests/bodyrig/rig_link_contract.py` binder source-order, fail-closed partials,
ren origin, fravær af lokal token-persistence/pairing, præcis Kaliv-intent-paritet
og bootstrap-wiring. Testen køres af renderer-gaten på exact PR-head.

Software-proof er ikke et fysisk Android/network-bevis. Senere fysisk acceptance
skal bevise en rigtig Kaliv → Kaliv Body launch med rigtig device-token og live
frames uden credential leakage.
