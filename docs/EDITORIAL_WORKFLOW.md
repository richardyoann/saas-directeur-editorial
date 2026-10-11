# DEV-005 — premier parcours éditorial persistant

## Comportement

`POST /editorial/runs` prend un brief et une clé `Idempotency-Key` UUID.
Deux appels llama.cpp au maximum : analyse de l'angle, puis storyboard structuré.
Aucune relance implicite. Le résultat valide passe en `waiting_validation`,
avec une revue humaine obligatoire; il n'est ni publié ni transformé en vidéo.
Un JSON invalide, une durée incorrecte ou une sortie tronquée bloque la suite.

Un scénario contient des scènes ordonnées : narration, description visuelle,
personnages, paysage, couleurs, plan, émotion, son et prompt image.
Les personnages et paysages sont à ce stade des attributs structurés des scènes,
pas encore des objets partagés avec leur propre cycle de versions.
Aucune recherche historique externe ni vérification des sources n'est effectuée.

Le renvoi de la même clé et du même brief retourne l'exécution enregistrée sans
rappeler le modèle. Une clé réutilisée pour un autre brief donne 409. Une demande
déjà en cours retourne 202. Une interruption laisse l'exécution `running`;
ce MVP ne réessaie pas une exécution dont l'issue réseau pourrait être ambiguë.
Une reprise explicite supervisée/queue durable reste à développer.

## Persistance et historique

Réutilisation du schéma de `pilotage/migration.sql` : `po_entity`, `po_audit`,
`po_outbox`. Aucun DDL au démarrage, aucune nouvelle migration. Ne pas appliquer
ce schéma à une base existante pour résoudre une erreur sans examiner son schéma.
Cette implémentation ne prétend pas être compatible avec des tables métier
locales non présentes dans GitHub; un mapping devra être ajouté si elles diffèrent.

Avant l'appel IA, prompt exact et traitement `running` sont persistés. Ensuite,
la sortie exacte, le JSON validé ou le code d'erreur normalisé sont conservés.
Chaque étape termine dans une transaction comprenant données, audit et outbox.
Un échec SQL annule cette transaction. Il peut laisser un traitement en cours
après un appel modèle; aucune double génération automatique ne doit le masquer.
Les snapshots créés par ce service sont conservés en objets `result` distincts.
La bibliothèque d'audit reste accessible aux administrateurs de la base : il
ne s'agit pas d'une protection absolue contre une modification administrative.

`GET /editorial/runs/{uuid}` fournit le résultat courant.
`GET /editorial/runs/{uuid}/history` fournit les prompts et sorties exacts.
Aucun contenu métier n'est envoyé à Slack par ces routes. L'outbox existante
est alimentée avec les références d'audit; le worker Slack reste à activer.

## Configuration privée

Les nouvelles routes refusent les appels sans identité configurée. Le MVP est
prévu pour un compte privé; il ne fournit pas encore connexion utilisateur,
rotation de jetons, droits fins ou gestion SaaS multi-utilisateur.

Variables du processus :

- `PO_DATABASE_URL` : connexion au schéma audit existant.
- `LLM_BASE_URL` : serveur llama.cpp existant.
- `EDITORIAL_API_TOKEN` : secret aléatoire d'au moins 32 caractères, transmis
  uniquement dans `Authorization: Bearer …`; ne pas le partager dans le chat.
- `EDITORIAL_TENANT_ID`, `EDITORIAL_ACTOR_ID` : UUID de l'identité privée définis
  côté serveur, jamais fournis par le corps de la requête.
- `EDITORIAL_CODE_VERSION` : SHA déployé; `unidentified` sinon, sans inventer
  une preuve de version réellement déployée.

Conserver l'API locale ou derrière HTTPS authentifié. Le contrat historique
`/ai/generate` est préservé; sa politique d'accès initiale n'est pas modifiée.

Exemple de corps (header de clé UUID et authentification requis) :

```json
{"topic":"La légende de la ville d'Ys","genre":"legend","duration_seconds":60,"scene_count":3,"audience":"Grand public","tone":"Narratif et accessible","sources":[]}
```

## Validation et limites

Tests ASGI : parcours, rejouabilité, saisie, authentification, erreurs et sortie
tronquée. Les appels Qwen sont simulés. Tests PostgreSQL : relations, contenu,
audit/outbox atomiques, annulation, concurrence et isolation entre tenants.

`python -m unittest discover -s tests -v` nécessite une base dédiée pour les tests
PostgreSQL : `PO_TEST_DATABASE_URL` et `PO_ALLOW_TEST_MIGRATION=yes`. La CI crée
un PostgreSQL 16 isolé et n'accède à aucune base utilisateur. Un skip local
n'est pas présenté comme une validation PostgreSQL.

Le compte rendu utilisateur du 11 octobre confirme sa base et son LLM connectés;
la session de développement n'a pas accès au PC ni à ces connexions. Validation
Qwen réel, raccordement de l'interface Arvor, revue humaine/édition et reprise
asynchrone restent ouverts. Aucun merge ou déploiement local automatique.
