# Economie de tokens — 12 octobre 2026

## Economie de contexte et de tokens
- Chercher avant de lire; extraire uniquement les passages utiles. Charger les skills et references a la demande.
- Preferer scripts et CLI existants; regrouper les lectures independantes et limiter chaque sortie a un resume ou 150 lignes.
- Eviter les polls rapproches; attendre un evenement ou un controle final.
- Petites demandes : traitement direct. Delegation seulement utile ou revue requise, deux sous-agents maximum, sans recursion par defaut.
- Transmettre objectif, chemins, SHA et contraintes, sans copier toute la conversation; retour concis avec preuves. Ne pas refaire le travail sans anomalie.
- Navigation/documentation bornees : profils economiques. Garder un raisonnement adapte et les validations indispensables pour securite, incidents et deploiement.
- Ne reutiliser les preuves que pour le meme SHA et les memes preconditions. Arreter apres les controles pertinents reussis.
- Reponses courtes, sauf livrables demandant du detail. Documentation et installation/deploiement tenus a jour. Aucun gain chiffre sans comparaison incluant les sous-agents.

## Installation et validation

Profils natifs .codex/agents, limite de deux sous-agents dans .codex/config.toml; installation equivalente dans C:/Users/Admin/.codex. Modele principal conserve; gpt-6-luna/low pour les deux roles bornes. Revenir au modele principal si indisponible ou inadequat. Les neuf roles historiques restent inchanges. Aucun skill supplementaire ni service externe requis.

Nouvelle session compatible necessaire pour charger les profils; aucune invocation ou reduction mesuree n'est annoncee sur la seule presence des fichiers. TOML valide et controle CLI local. Les validations CI et deploiement restent obligatoires.

Baseline avant analyse : conversation 01a125b1-eeb0-7713-b840-c1ab1cbbcca1, entree 18 205 544 dont cache 17 437 312, sortie 41 050. Autres sessions et sous-agents exclus; ce n'est pas une facture. Comparer prochaines taches de complexite equivalente, memes criteres/qualite, en incluant sous-agents, reprises, entree/cache/sortie et temps. Aucun gain chiffre encore demontre.

Reprise : revert des fichiers projet. Windows : sauvegarde config.toml.before-token-economy-<date> avant ajout, nouveaux profils economy_*.toml et consigne dans AGENTS.md. Restaurer la configuration seulement si aucun changement ulterieur n'est a conserver.

Sources : https://learn.chatgpt.com/docs/agent-configuration/subagents ; https://learn.chatgpt.com/docs/config-file/config-reference
