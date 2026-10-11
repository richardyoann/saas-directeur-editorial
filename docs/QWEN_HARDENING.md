# EDIT-001 — Contrats PC ↔ Qwen et diagnostic

## Constat au 11 octobre 2026

Baseline inspectée : 53d3f37e4e8bc9687a2e999172e297632e5c699a.
La synthèse Slack de 22 h 56 signale un échec réel EDIT-001. Aucun run ID,
code d'erreur ou journal détaillé n'a été retrouvé dans les issues #38/#39,
la discussion #63 ou les messages du canal. Sa cause exacte n'est pas prouvée.
Le run de livraison PC 38163563435 avait été ignoré : cela ne constitue
ni un appel Qwen échoué ni une preuve de livraison.

Fragilités constatées dans le code : JSON strict attendu mais sans contrainte
de format envoyée au serveur; consignes et données dans un seul message user;
historical_checks demandé aussi au storyboard qui interdit ce champ;
diagnostic live générique; délai client de 150 s pour deux étapes pouvant
chacune atteindre 120 s. Ce dernier point est un risque conditionnel, pas
la cause démontrée de l'échec signalé.

## Renforcement implémenté

- Avant l'envoi : prompt non vide borné à 65 536 octets dans le fournisseur,
  max_tokens entier strict 1–2048, consignes système 8 192 octets maximum,
  schéma JSON sérialisable sans NaN et limité à 32 768 octets. Route générique :
  prompt limité à 16 000 caractères et booléens refusés pour max_tokens.
- Workflow : message system séparé, données user, température 0,1,
  response_format={type: json_object, schema: ...} documenté pour llama.cpp.
  Nombre exact de scènes contraint; plan de durées proposé par le code.
  historical_checks reste limité à l'analyse. Deux appels maximum sans retry.
- Transport : redirections refusées même si le client les autorise, réponse
  décodée bornée à 262 144 octets pendant la lecture et délai total 120 s
  par appel en plus des timeouts HTTP existants. Aucun contenu brut dans les erreurs.
- Avant retour : JSON amont sans clés dupliquées ni NaN/Infinity; une seule
  choice. Sortie éditoriale limitée à 131 072 octets, JSON strict, types et
  champs explicites, nombre de scènes et somme des durées validés. Une sortie
  tronquée, un finish_reason absent ou autre que stop bloque le workflow.
- Accès : /ai/generate exige maintenant l'identité privée lorsque l'une des
  variables EDITORIAL_API_TOKEN/TENANT_ID/ACTOR_ID est configurée. Configuration
  partielle ou invalide : refus 503; appel anonyme avec config valide : 401.
  Sans ces variables, le contrat historique de bootstrap local demeure anonyme.
  La livraison privée exige déjà le jeton. Ne pas exposer le bootstrap sur le réseau.
- Historique : versions prompt 1.1.0 et workflow editorial-v1.1; paramètres
  ajoutés au traitement. L'ancien résultat d'une clé n'est jamais écrasé :
  un changement de version peut produire 409, imposant une nouvelle clé de test.
- Contrôle de livraison : timeout HTTP de 260 s pour le parcours à deux appels;
  seules des catégories d'erreur fixes sont exposées. Diagnostic séparé en lecture seule.

Le schéma demandé au serveur ne remplace jamais la validation Python.
Une version llama.cpp incompatible ou qui ignore le schéma ne bénéficie
d'aucun fallback silencieux. Un message système réduit les ambiguïtés mais
n'est pas une protection absolue contre l'injection de prompt. Aucun outil
ou exécution système n'est offert au modèle par ce fournisseur.

## Diagnostiquer l'exécution en échec sur le PC

Depuis le dépôt WSL, avec le .env privé existant et le run UUID concerné :

```bash
.venv/bin/python scripts/diagnose_editorial_run.py --run-id UUID_DE_L_EXECUTION
```

Le script lit uniquement GET /editorial/runs/{id} et /history sur l'API
loopback. Il ne crée aucune génération, ne relance aucun traitement et ne
migre rien. Sortie : statut, code normalisé, étape, finish_reason et validité
du schéma. Ni jeton, ni URL, ni brief, ni réponse privée imprimés.
Si l'exécution a été interrompue avant persistance, son diagnostic exige
les journaux locaux du service; aucune conclusion inventée.

## Validation et limites

Suite locale initiale : 104 tests découverts, 95 réussis, 9 PostgreSQL ignorés,
0 échec, 0 erreur. Le garde de livraison reste donc bloquant localement.
La régression CI sur le SHA de la PR doit exécuter les 9 tests sur PostgreSQL
16 jetable avant qualification. HTTP/Qwen simulés dans ces tests.

Validation réelle restante : version/build llama.cpp, template Qwen effectivement
chargé, support du schéma, contexte disponible et vitesse sur le PC; jeton et
pare-feu du serveur modèle; génération structurée et persistance réelles.
HTTP loopback/WSL n'apporte pas de chiffrement. Tout passage sur un réseau
non isolé exige HTTPS et authentification du serveur. Aucun réglage réseau,
poids, service Windows/WSL ou secret n'a été changé par cette PR.

Retour arrière : revert du code de la PR, sans migration. Réutiliser les
anciennes clés après revert peut produire un conflit de version; créer une
nouvelle clé technique, sans supprimer les traces ni modifier les résultats.

Référence fournisseur : https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
section POST /v1/chat/completions. La version installée reste à vérifier.
