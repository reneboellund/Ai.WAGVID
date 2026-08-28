# Governance og adgangskontrol

Ai.WAGVIDs governance-kontrolplan er organisationsafgrænset og deny-by-default. Brugere kan være medlem af flere organisationer, men den aktive organisation vælges eksplicit og gemmes i sessionen. Alle views foretager fortsat deres egen organisation- og rollekontrol.

## Roller og invitationer

Organisationsadministratorer kan invitere viewer, annotator, reviewer, fagkyndig reviewer, operatør, træner, forsker eller organisationsadministrator. Systemadministrator kan ikke uddeles via en organisationsinvitation. Invitationstokenet vises én gang og gemmes kun som SHA-256; det er bundet til modtagerens e-mail, udløber og kan kun anvendes én gang.

Rolleændringer kræver en begrundelse og bliver append-only audit-events. En administrator kan ikke deaktivere eller nedgradere sin egen administrative adgang via dette flow.

## Konfigurationsrevisioner

Konfiguration ændres ved at oprette en ny revision. Frosne revisioner kan hverken redigeres eller slettes. Hver revision har canonical SHA-256, aktør, årsag og eventuelt freeze-tidspunkt. Felter, der ligner passwords, tokens, API keys eller secrets, accepterer kun `env:`, `vault:` eller `secret:`-referencer.

## Datasetrettigheder

En datasetkilde registrerer immutable kildehash, rettigheds- og samtykkereference samt fire uafhængige tilladelser: analyse, opbevaring, træning og eksport. Ingen af dem udledes af de andre. Atlet- og eventgrupper omdannes til organisationsbundne HMAC-nøgler, før de gemmes i governance-eksporten. Recorden er append-only; ændrede rettigheder kræver en ny version/kildepost.

## Evidensdeling

En deling binder organisation, præcis video, navngiven modtager, handlingerne `view`/`download`, udløb og grant-ID. Tokenet gemmes kun som hash. Ved indløsning skal den autentificerede brugers e-mail eller brugernavn matche modtageren; derefter udstedes kun en kortlivet, objekt- og checksum-bundet adgang. Tilbagekaldelse kræver en årsag og træder i kraft før ny indløsning.

## Audit og drift

Governance-siden viser de seneste events og kan eksportere organisationsafgrænset UTF-8 CSV. Eksporten indeholder correlation ID og canonical JSON-metadata, men ingen invitationstokens, share tokens eller secret-værdier. Audit-eksporten registreres selv som en audit-event.
