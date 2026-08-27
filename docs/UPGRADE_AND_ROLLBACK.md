# Opgradering og rollback

Release-manifestet i `release/manifest.json` binder version, Git-revision, migrations, konfigurationsmigreringer, Android-protokol og rollback-egenskaber sammen. Opgraderings-UI'et er et kontrol- og journalværktøj; det eksekverer ikke vilkårlig kode.

Preflight blokerer opgradering uden en frisk verificeret backup, kendt migrationsvej, drænet analysekø, afsluttede uploads og brugbare storage-providere. Før deployment sættes systemet i vedligeholdelsestilstand. GET, health, readiness og update-administration forbliver tilgængelige, mens andre writes får HTTP 503.

## Runbook

1. Publicér og gennemgå release-manifestet.
2. Opret og verificér en `pre-upgrade` backup.
3. Dræn uploads og analysejobs, og kør preflight igen.
4. Gem opgraderingsplanen i journalen og aktivér vedligeholdelsestilstand.
5. Deploy kode, anvend migrations med den eksterne deployment-runner, og kør systemkontrol og smoke tests.
6. Afslut vedligeholdelse først efter eksplicit verificering.

Kode kan rulles tilbage alene, når manifestet siger `code_only: true` og ingen inkompatibel forward-only migration er anvendt. Ellers kræves restore fra den bundne backup. Hver udførelse skal bevare journal, backup-ID, migrationer, kontrolresultater og fejlårsag.
