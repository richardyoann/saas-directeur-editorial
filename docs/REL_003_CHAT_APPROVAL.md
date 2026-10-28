# REL-003 — validation PC depuis la conversation

16 octobre 2026. Préparation sur base `07a4e29a43aaa2b973bae926b8027d0feb2d390d`.
Aucune livraison PC ni activation de variable effectuée par cette modification.

Après présentation d'un SHA complet, des tests et des risques, une validation
explicite de l'utilisateur autorise Codex à créer la branche technique
`delivery-approved/<SHA complet>`, exactement sur ce commit de main.
Utiliser le connecteur GitHub create_branch (sha explicite), après avoir vérifié
que main correspond toujours à la version présentée. Ne jamais créer cette
branche sur simple demande de développement ou de préparation.
Une branche existante ne doit pas être déplacée, supprimée ou recréée pour
rejouer une installation : inspecter d'abord le résultat du run.

GitHub reçoit l'événement create et exécute Chat approved PC delivery.
Le validateur sur runner hébergé vérifie le dépôt, le format du SHA, le contenu
de la branche et le SHA courant de main avant tout accès au runner privé.
Le SHA validé doit être égal à la variable de dépôt `LOCAL_PC_APPROVED_SHA`,
configurée uniquement par un administrateur. Le job auto-hébergé est ignoré si
la variable est absente, vide ou différente du SHA validé : la seule création
d'une branche `delivery-approved/*` ne suffit plus. Le workflow ne modifie
aucune variable. Le script de déploiement conserve ses preuves CI, sa
vérification de main, sa recette isolée, ses contrôles HTTP et son retour
arrière.

## Interrupteur initial

LOCAL_PC_ENABLED doit être true une fois, après autorisation de l'utilisateur.
Il reste l'arrêt général et n'est jamais contourné. Le connecteur de cette
session ne sait ni lire ni modifier cette variable. Si false ou absente, le
job PC reste ignoré ; l'activation initiale doit être faite par un accès autorisé.
LOCAL_RELEASE_ROOT et LOCAL_CONFIG_PATH doivent déjà être configurés.
LOCAL_PC_APPROVED_SHA est désormais le verrou de la voie create : il doit
contenir le SHA complet exact autorisé, et être retiré ou remplacé avant toute
autre livraison. Une autorisation ne couvre jamais un SHA ultérieur.

## Droits, traçabilité et limites

Seuls des comptes ou applications ayant le droit de créer une branche dans
le dépôt peuvent émettre ce déclenchement. Ces droits sont équivalents à une
autorisation de livraison pour cette voie : ne pas les accorder à un acteur
non fiable. La branche, son SHA et le run Actions sont les traces techniques ;
l'accord humain est conservé dans la conversation et doit être référencé dans
le compte rendu. Le workflow ne prétend pas authentifier le texte d'un accord
ChatGPT et ne surveille pas automatiquement les conversations.

Le workflow doit être fusionné sur la branche par défaut pour recevoir create.
Ne pas créer de branche delivery-approved pour tester sans validation explicite
du SHA à installer. Une CI verte n'est ni une installation ni une acceptation
éditoriale. Les suites historiques et le contrôle main restent obligatoires.
Les notifications et corrections existantes ne sont pas remplacées ici.
Retour arrière de cette fonctionnalité : désactiver Chat approved PC delivery,
sans toucher aux données ni aux releases.

## Validation

Tests locaux réussis : SHA exact accepté ; dépôt incorrect, format invalide,
branche déplacée et main modifié refusés ; workflow auto-hébergé sans
`vars.LOCAL_PC_APPROVED_SHA` rejeté par `scripts/ci_policy.py` ; job PC non
déclenché si la variable diffère du SHA validé.
Régression complète et premier événement create : à qualifier sur le SHA final.
Aucun test Qwen/HTTP réel ni changement PC effectué.
