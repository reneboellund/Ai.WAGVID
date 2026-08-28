# Analyse- og rapportprodukt

Rapportlaget forbinder de modelneutrale analysekerner med det organisationsafgrænsede Django-produkt. Det udfører ikke inference i web-requests.

## Scoreverifikation

En scoreverifikationsrapport kan kun genereres fra et `AnalysisResult`, der allerede er markeret `FROZEN` og har `frozen_at`. Rapporten binder source-media-ID og SHA-256, modelprofil/-run, rulepack, scoreledger, kronologiske fradrag, evidens, menneskelige beslutninger og eventuelt officielt resultat. Artifactet får canonical SHA-256 og kan ikke redigeres eller slettes. En ny rapport bliver en ny revision.

Det officielle resultat præsenteres som sammenligningsdata; rapporten erklærer ikke automatisk panelet eller AI'en korrekt. Uafklarede fradrag forbliver eksplicitte.

## Performance og longitudinal analyse

Performance- og longitudinal-kernerne adskiller observeret faktum, mønster, coaching-hypotese og foreslået træningsfokus. Kun schema-validerede JSON-rapporter kan publiceres. Publiceringen deduplikeres på payload-digest og knyttes valgfrit til gymnast og event i samme organisation.

## Konkurrencebatch

Event-batchplanen producerer identitetsminimerede worker-tasks. Worker-planen indeholder media-ID/checksum, apparat, ruleprofile og analyseprofil, men ikke atlet-, konkurrence- eller rutineidentitet og aldrig officielle scoreværdier. Officielle payloads opbevares kun som digests i dispatch-planen og må først frigives til sammenligning efter en dokumenteret AI-freeze.

Gentaget planlægning af samme event og analyseprofil er idempotent, mens en ny profil opretter en ny plan. Faktisk kø-dispatch, freeze receipts og official reveal skal ske gennem den eksterne worker-/orchestratorproces og dens state machine.

## Adgang og eksport

Generering/publicering kræver admin-, reviewer-, fagkyndig-reviewer- eller coachrolle. Læsning følger organisationens rapportadgang. JSON-downloads er tenant-scoped, `private, no-store` og digest-bundet via ETag. Alle genereringer og batchplaner audit-logges.
