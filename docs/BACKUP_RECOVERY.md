# Backup og gendannelse

Ai.WAGVID adskiller kontrolplanet fra selve backup-runneren. Web-UI'et opretter et versionsbundet manifest, viser historik og verificerer checksums. En særskilt, mindst privilegeret runner udfører `pg_dump` i custom-format og leverer artifactets SHA-256 tilbage. Webprocessen starter aldrig lange databasekommandoer.

Et backup-sæt består af database-dump, ikke-hemmelig konfiguration og en provider-neutral objektinventarliste. Videoobjekterne kopieres ikke automatisk: inventory registrerer provider, bucket, key, version, checksum, retention og legal hold. Credentials gemmes aldrig; manifestet indeholder kun `env:`, `vault:` eller `secret:`-referencer.

## Operativ procedure

1. Opret planen under **Backup** med korrekt formål og destination.
2. Lad den godkendte runner hente manifestet, producere database-dump og de to JSON-artifacts.
3. Gem artifacts på en destination med anden fejlzone og adgangsmodel end primær storage.
4. Indtast runnerens SHA-256 og verificér planen.
5. Kør restore-preflight. Manglende secrets blokerer aktivering, men ikke en isoleret staging-restore.
6. Gendan først i et isoleret miljø, kontrollér migration head, objektinventory og stikprøver, og aktivér derefter eksplicit.

Restore må ikke overskrive eksisterende videoobjekter. Wasabis minimumsopbevaring og delete-omkostninger gælder fortsat; recovery-flowet må derfor ikke masse-slette objekter som oprydning.

Der skal udføres og dokumenteres en restore-øvelse mindst kvartalsvist. Et manifest er ikke bevis for en brugbar backup, før dumpet er verificeret og en staging-restore er gennemført.
