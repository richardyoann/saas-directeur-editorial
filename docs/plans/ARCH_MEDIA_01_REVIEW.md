# ARCH-MEDIA-01 — Découplage des règles média

Date : 18 octobre 2026. Base : `1aeddcb8e496510034a272484f9bde955fd11fb0`.
Branche : `fix/ARCH-MEDIA-01-decouplage-media`. Candidat de revue ; validation globale en attente. Aucun déploiement ni acceptation métier.

## Changement

Avant : `visuals → media_storage → visuals` (imports différés).
Après : `visuals → media_storage → media_rules` et `visuals → media_rules`.

Le module `editorial/media_rules.py` contient uniquement bibliothèque standard, constantes, exceptions et fonctions pures : personnages, prompt, provenance, validation PNG et politique d’URL privée. Les sept définitions déplacées ont une AST identique à la base. Le module `visuals` réexporte les mêmes objets pour préserver les signatures et imports publics historiques. `media_storage.client` utilise la règle neutre au lieu de réimporter visuals. Transport, stockage, routes, transactions et worker restent dans leurs modules actuels.

Un module plat suffit pour cette première PR ; la structure en package du plan cible sera introduite si nécessaire pour les ports/service. Aucun package d’infrastructure ou service applicatif anticipé ici.

## Validation locale initiale

Python système 3.14. Aucun paquet installé.

- RED : le nouveau module absent provoque ImportError avant extraction.
- Caractérisation avant extraction : 5 tests comportementaux réussis contre les définitions initiales isolées par AST (ce contrôle ne remplace pas une intégration runtime).
- `python3 -m unittest discover -s tests -p test_media_rules.py -v` : 7 tests réussis, 0 échec, 0 erreur, 0 skip.
- Test historique ajouté à VisualContractTests : identité des réexports et exceptions ; exécution bloquée localement par httpx absent.
- `python3 scripts/run_regression.py` : 120 tests découverts, 91 réussis, 1 échec, 28 erreurs, 0 skip ; exit 1. Les imports manquants empêchent la découverte de nombreuses classes : ce nombre n’est pas la taille réelle de la suite complète.
- Même régression sur une archive isolée de la base : 113 tests, 84 réussis, 1 échec, 28 erreurs, 0 skip ; exit 1. Les 7 réussites supplémentaires correspondent aux nouveaux tests purs. L’échec de CLI préflight vient de httpx absent ; les erreurs sont des dépendances absentes (FastAPI/HTTPX/Pydantic/dotenv/psycopg/boto3).
- `python3 -m compileall -q editorial` et `git diff --check` : réussis.
- Comparaison AST des 7 fonctions/classes déplacées : identiques à la base.
- `graphify update .` : réussi ; graphe et sauvegardes préexistants conservés. Parseur SQL absent ; aucune installation effectuée.

Les tests PostgreSQL, parcours Studio, concurrence/audit/outbox et panne DB ne sont pas validés dans cet environnement. Aucun service dédié de test configuré et aucune base métier utilisée. L’autorisation d’installer requirements.txt dans un venv isolé a été demandée ; une absence de réponse ne vaut pas autorisation. La CI existante de PR utilise PostgreSQL jetable et doit fournir les preuves au SHA candidat.

## Risques, compatibilité et reprise

Les corps des fonctions, valeurs des constantes, paramètres image, exceptions, limites PNG/URL et contenu des reçus sont conservés. Pas de validation CRC supplémentaire introduite dans cette extraction. Les écritures métier/audit/outbox, IDs, verrouillage, récupération et refus des retries ambigus ne sont pas modifiés. Le nom de module Python des objets déplacés change ; les imports historiques restent compatibles, mais aucune compatibilité de pickle interversion n’est revendiquée (aucun usage identifié dans le périmètre).

Aucune dépendance, variable d’environnement, commande d’installation, unité systemd, workflow ou migration ne change. La release PC active n’est pas inspectée ni modifiée ; compatibilité de configuration attendue, recette PC non exécutée. Tout futur déploiement exige validation du SHA exact. Reprise : revenir au code précédent sans toucher médias ou données.

Revue de contenu : aucun secret ajouté ; fixtures PNG et textes de test synthétiques uniquement. AGENTS.md, le plan non suivi et les autres artefacts préexistants restent exclus du commit de PR1. Les sorties graphify locales sont rafraîchies sans suppression des documents existants.

PR2 reste suspendue jusqu’à validation technique de PR1 et remise du rapport de revue. Aucune fusion automatique.
