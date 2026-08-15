# ADR-A3-001: Chattens adgang til Agent 3

**Status:** VEDTAGET af Anders 15-08-2026 ("jeg går med din anbefaling").
**Udkast:** skrevet af Claude efter PR #597, hvor dvale-gaten fældede en wiring af agent-kortet ind i chatten.
**Serie:** første dokument i A3-serien, efter A4-seriens form.
**Stopreglen (A4-005) er overholdt:** dette dokument landes FØR den kode, det beskriver.

---

## 1. Kontekst

Anders har bedt om, at chatten skal kunne **vise og starte** Agent 3-kørsler (skærm 12, som hidtil har stået ærligt uwiret).

Da wiringen blev bygget (PR #597), fældede CI den:

```
tests/workflow_agent3_dormant.py
  FAIL: normal routing is agent3-free: AppUi.kt
```

Gaten kræver, at `AppUi.kt` og `TurnRouter.kt` ikke nævner `agent3` overhovedet. Wiringen blev rullet tilbage frem for at flytte referencen til en fil, gaten ikke scanner — det ville have bestået gaten og brudt dens hensigt.

**Hvad gaten faktisk beskytter:** at en almindelig chat-tur ikke kan blive til en agent-kørsel. Agent 3 lægger en plan på forhånd, udfører i trin, har read-checkpoints, en immutabel write-hale og digest-bundne godkendelser. Chat (V2) er værktøjer + RAG med bekræftelse pr. handling. Kendte den normale routing Agent 3, kunne en regression sende en helt almindelig besked ned ad agent-stien. Det er den ulykke, invarianten forhindrer.

**Det egentlige spørgsmål er derfor ikke** "må chat-koden nævne agent3", men:

> Må en almindelig chat-tur kunne blive til en agent-kørsel — uden at mennesket valgte det?

Svaret på DET skal blive ved at være nej, uanset hvad vi beslutter om fladen.

**Aktuel tilstand (uændret af dette dokument):** `KALIV_AGENT3_ENABLED` er slukket som udgangspunkt på riggen; `production_activation` er `false`; Stage A-beviset er fortsat blokeringen for produktionsaktivering.

---

## 2. Beslutninger

**D1 — Invarianten omformuleres, den fjernes ikke.**
Reglen bliver: *den normale tur-routing må aldrig referere Agent 3.* Tur-routing = den kodesti, der afgør hvor en tastet besked sendes hen (`TurnRouter.kt` + chattens send-sti). Chattens **flade** må derimod huse et agent-panel, når panelet ligger i sin egen fil med sin egen indgang.

**D2 — Kun eksplicit igangsættelse.**
En agent-kørsel må kun starte fra en handling, mennesket foretager for netop den besked. Aldrig automatisk, aldrig som fallback, aldrig fordi en model vurderer at "det her ligner en opgave". Ingen heuristik må kunne vælge agent-stien.

**D3 — Riggens flag bestemmer, og klienten skal opdage det, ikke antage det.**
Agent-indgangen findes kun i UI'et, når riggen faktisk tilbyder Agent 3. Klienten spørger én gang; svarer ruten ikke, forsvinder indgangen, og der pollès ikke videre i sessionen (fail-quiet, som i #597's forberedelse).

**D4 — Plan-preview, godkendelser og checkpoint-fladen flytter IKKE ind i chatten.**
De bliver på den dedikerede Agent 3-skærm. Chatten viser kørslen og sender videre.
*Begrundelse:* digest-bundne godkendelser og den immutable write-hale er sikkerhedsflader. To implementeringer af samme sikkerhedsflade betyder, at den svageste bliver den, der bruges. Vi har lige set, hvor let to implementeringer af selv et QR-linkformat driver fra hinanden — det krævede en paritets-gate. Sikkerheds-UI i to udgaver er værre.

**D5 — Chatten må starte READ-planer; alt med et write-trin kræver den dedikerede skærm.**
Indeholder planen et write-trin, siger chatten det rent ud og linker videre til godkendelse. Chatten godkender ikke writes.

**D6 — Stop må ske fra chatten, med to skridt og ærlig tekst.**
"Resten af trinnene køres ikke. Det der allerede er udført, rulles ikke tilbage." Riggens svar afgør, om kortet bliver stående.

**D7 — Gaten udskiftes, den svækkes ikke.**
`workflow_agent3_dormant.py` opdateres som **konsekvens af beslutningen** — ikke for at få noget til at passere:
- `TurnRouter.kt`: absolut forbud, uændret.
- Chatfladen: forbud mod Agent 3-klienten og mod `/experimental/agent3`-stier i send-stien; agent-panelet skal ligge i `ui/agent/**` med én neutral indgang.
- Nyt: en adfærdskontrakt (kontrakttest 3), der beviser at kun en eksplicit brugerhandling kan producere en start.
- Go-rutegating, lazy worker-mount og `production_activation = false`: uændret.

**D8 — Dette dokument aktiverer ingenting.**
Det ændrer hvad klienten må, når riggen selv har slået Agent 3 til. Stage A, `production_activation` og aktiveringsporten er urørte. Agent 4 er ikke omfattet.

---

## 3. Fravalgte alternativer

**A. Behold dvalen absolut — agenten bliver på sin egen skærm.**
Billigst og sikrest. Fravalgt fordi skærm 12 så aldrig bliver andet end en tegning. *Bemærk: dette er et fuldt forsvarligt valg, hvis du hellere vil vente til Stage A er i hus.*

**B. Fuld åbning — chatten planlægger, godkender, viser checkpoints og starter alt.**
Bedst på papiret i UX. Fravalgt: duplikerer sikkerhedsfladen (D4), og gaten mister sin betydning, fordi der ikke længere er en grænse at håndhæve. En write-godkendelse i en chatboble er præcis dér, hvor et fejltryk sker.

**C. Smal åbning — D1-D8 ovenfor. ANBEFALET AF CLAUDE, VALGT AF ANDERS.**

---

## 4. Konsekvenser

**Ændres:** chatten kan vise en igangværende kørsel og starte en read-plan efter eksplicit valg; agent-panelet får egen fil og indgang; dvale-gaten bliver strengere på adfærd og mere præcis på placering.

**Ændres ikke:** Agent 3 slukket som udgangspunkt; godkendelser/preview/checkpoints bor på den dedikerede skærm; `production_activation` = false; Stage A er stadig blokeringen; Agent 4 urørt.

---

## 5. Kontrakttests (grønne før implementeringen landes)

1. **Tur-routing er agent-fri.** `TurnRouter.kt` + chattens send-sti indeholder ingen Agent 3-reference. *(Mutation: indsæt en reference → rød.)*
2. **Panelet bor for sig.** Agent-fladen ligger i `ui/agent/**`; chatten kalder én neutral indgang.
3. **Kun eksplicit start.** En ren policy-funktion tager en hændelse ind og returnerer højst én start-intention: eksplicit brugerhandling → intention; alt andet (modelforslag, automatisk genoptagelse, "lignede en opgave") → null. *(Mutation: gør modelforslag til gyldig kilde → rød.)*
4. **Flaget styrer synligheden.** Uden agent-svar fra riggen: ingen indgang, ingen polling efter første forsøg.
5. **Writes kan ikke starte fra chatten.** En plan med mindst ét write-trin kan ikke startes ad chattens vej.
6. **Ingen automatisk genoptagelse.** Intet i chatfladen kalder resume.
7. **Terminale kørsler forsvinder.** Færdig/fejlet/annulleret bliver ikke stående som levende. *(Findes: `AgentRunPresentation`.)*
8. **Dvale-invarianterne står.** Go-ruter flag-gatede, worker mounter lazily, `production_activation` aldrig true.

---

## 6. Implementering (efter vedtagelse)

| Slice | Indhold | Bevis |
|---|---|---|
| 1 | Flyt `AgentRunPresentation` + kortet til `ui/agent/**`; opdatér dvale-gaten efter D7; ingen wiring | Gate omskrevet + selvtest |
| 2 | Vis aktiv kørsel i chatten (fail-quiet opdagelse, to-skridts stop, tap → checkpoint-skærmen) | Kontrakttest 1-2, 4, 6-7 |
| 3 | Start READ-plan fra eksplicit valg; write-planer henvises videre | Kontrakttest 3, 5 |
| 4 | Release + feltafprøvning på riggen | — |

---

## 7. Operationelle valg og risici

Anders vedtog anbefalingen og bad om at komme i gang. De tre operationelle spørgsmål følger derfor Claudes forslag; de er reversible og kan omgøres uden ny ADR.

1. **Run ↔ samtale.** En kørsel startet i én samtale vises kun dér: run-id bindes lokalt til samtalen. Kørsler startet andre steder ses på agent-skærmen.
2. **Flaget slukkes midt i en kørsel.** Chatten siger "kan ikke længere se kørslen" — den antager ALDRIG at kørslen er stoppet, for det ved den ikke.
3. **Polling og batteri.** 5 s mens et kort vises, 60 s uden, helt stop når ruten ikke svarer (fail-quiet).
4. **Tidspunkt.** Bygges NU, før Stage A-beviset. Det er en prioritering, ikke en sikkerhedsafhængighed: intet her aktiverer Agent 3, og `production_activation` forbliver false.

**Tilbageværende risiko, skrevet ned med vilje:** en kørsel startet fra chatten kan ende med at vente på en write-godkendelse, som chatten ikke må give. Fladen SKAL derfor sige det tydeligt og linke videre — ellers ser kørslen bare ud til at gå i stå.

---

## 8. Hvad dokumentet bevidst ikke gør

- Aktiverer ikke Agent 3 nogen steder.
- Rører ikke godkendelsesmekanik, write-hale eller replan-flow.
- Rører ikke Agent 4, ADR-A4-serien eller DevControl.
- Flytter ikke Stage A-porten.
