# T-022 current-main physical candidate

Denne branch samler den allerede CI-grønne, dormante T-022 final-gate-stack oven på
nuværende `main` uden at ændre runtime-ruter, tools, approval-semantik eller
produktionsaktivering.

## Autoritativ kandidat

- branch: `agent/t022-final-gate-current-main`
- version: `2.0.11`
- launcher: `START_AGENT3_WRITE_PILOT.cmd`
- entrypoint: `scripts/agent3_write_pilot_current_main.py`

Kør kun top-level launcheren. Den rebinder den historiske positive, negative,
collector- og final-gate-kæde til branch og version ovenfor, før kandidatens
renhed eller fysisk evidens vurderes.

De tre ældre sublaunchere er bevaret som interne/historiske operatortrin. De har
deres oprindelige branch-pins og stopper derfor sikkert, hvis de køres direkte
på denne kandidat. Det forhindrer en delkampagne i at blive forvekslet med den
autoritative 20-positive + 7-negative final gate.

## Hård grænse

Hosted CI kan kun bevise bindings- og kontraktkoden. En grøn CI-run er ikke fysisk
evidens. T-022 er først fysisk grøn, når top-level launcheren er kørt på den rene
Windows-rig med præcis én parret Android-enhed, alle 20 positive approvals og alle
syv adversarial cases er gennemført, og den sanitiserede final-gate-rapport er
grøn med `production_activation=false`.

Denne branch merger, releaser eller aktiverer ikke noget automatisk.
