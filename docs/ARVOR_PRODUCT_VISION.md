# ARVOR — Charte de vision produit « Private First »

**Version :** 1.0  
**Décision utilisateur :** validée le 18 octobre 2026  
**Statut :** référentiel fonctionnel à conserver pour la roadmap, les PR, les agents de développement et les recettes.  
**Portée :** Arvor / Directeur éditorial — dépôt privé `richardyoann/saas-directeur-editorial`.

> **Mission figée :** Arvor est **d'abord un atelier audiovisuel privé, local et prioritairement open source** permettant de produire des **vidéos courtes, ludiques et éducatives**, notamment sur les légendes, mythes et le patrimoine bretons, destinées aux réseaux sociaux. Sa réussite se mesure à la production effective de vidéos de qualité avec peu de travail manuel et à la capacité de générer **au moins 200 € par mois de bénéfice après coûts directs**. **Le SaaS commercial à abonnements n'est qu'une option ultérieure**, conditionnée à la preuve du fonctionnement et de la rentabilité.

## 1. Principes non négociables

1. **Usage privé prioritaire** : un outil personnel opérationnel avant toute ouverture au public. Pas de facturation, acquisition clients, multi-tenant ni RBAC commercial en priorité.
2. **Vidéo MP4 de bout en bout** : un scénario JSON ou une image isolée ne constituent pas un produit fini.
3. **Open source et local privilégiés** : retenir un outil pour sa qualité, sa maintenance, ses exigences matérielles, sa licence et sa sécurité ; ne pas exclure un autre outil uniquement pour un principe théorique.
4. **Production économique sur matériel existant** : faire d'abord un conte illustré animé ou motion comic ; la vidéo générative IA intégrale est facultative.
5. **Contrôle éditorial humain** : faits historiques distingués des éléments romancés, sources conservées, droits vérifiés, validation humaine avant publication.
6. **Interface simple** : UI sobre, moderne, intuitive, fidèle au prototype attendu ; complexité technique reléguée en administration.
7. **Données privées et durables** : secrets jamais codés en dur, sauvegardes vérifiées, stockage privé, audit par action, versions et restauration ; aucune exposition publique implicite.
8. **Aucune livraison PC automatique** : un test vert, un commit ou une PR fusionnée ne vaut jamais accord de déploiement. Respect de la validation du SHA exact, de la recette et du rollback non destructif.
9. **Pas de promesse de revenus** : calculer le bénéfice sur les recettes encaissées après frais réels, pas sur les vues ni sur une estimation publicitaire.
10. **80/20** : toute nouvelle fonctionnalité doit améliorer la qualité d'une vidéo, réduire son coût, son temps de production ou l'effort manuel ; sinon la différer.

## 2. Pipeline cible à réaliser

| Étape | Livrable attendu | Critère de validation |
|---|---|---|
| 1. Idée et brief | Sujet, audience, durée, angle | Brief persistant et révisable |
| 2. Recherche | Sources, variantes, faits, incertitudes | Validation humaine des affirmations pédagogiques |
| 3. Script et storyboard | Scènes, narration, durées, prompts | Cohérence narrative ; somme des durées vérifiée |
| 4. Continuité visuelle | Fiches personnages, lieux, palettes, références | Les éléments réapparaissent de manière reconnaissable |
| 5. Illustrations | Images par scène | Médias lisibles et intègres, traçables dans MinIO |
| 6. Voix et sons | Voix off en français, musique, bruitages | Compréhensibilité, niveaux, licences vérifiées |
| 7. Sous-titres | SRT et incrustation éventuelle | Synchronisation, lisibilité sur smartphone |
| 8. Montage | Transitions, panoramiques, zooms, export | MP4 complet ; piste audio correcte |
| 9. Recette | Visionnage et validations humaines | Pas de corruption, problème de droit ou incohérence majeure |
| 10. Publication/mesure | Fichier publiable et tableau de suivi | Suivi des performances et revenus, publication non automatique |

**Format de départ :** vidéo verticale 9:16 de 30 à 60 secondes ; cible 1080 × 1920, MP4 H.264 / audio AAC, sous-titres mobiles et accroche claire. Le format technique est une **cible d'acceptation**, non la preuve d'une capacité déjà présente.

**Définition de « vidéo terminée » :** elle est réellement visionnable du début à la fin, possède voix/sons/sous-titres attendus, montage rythmé, images cohérentes, métadonnées de provenance et accords éditoriaux ; elle peut être exportée sans manipulation technique manuelle non documentée. Pas de faux succès si seul le scénario, le JSON ou un test simulé existe.

## 3. Plan de réalisation — jalons et décisions

### Phase A — MVP vidéo privé (P0)

- Fiabiliser CI/CD, tests de non-régression, navigateur, sécurité minimale et livraison sur le PC pour **un SHA effectivement vérifié**.
- Valider le parcours : idée → script → scènes → image(s) locale(s) → voix → sous-titres → montage → MP4.
- Mettre en place le contrôle éditorial, les preuves de provenance, l'export, la reprise sur incident et la protection des médias.
- Conserver le studio UX/UI attendu et éviter de multiplier les interfaces concurrentes.
- **Gate A :** une vidéo complète de qualité satisfaisante est produite localement, conservée et relue, avec un temps manuel mesuré.

### Phase B — Production reproductible privée (P1)

- Transformer le parcours en une chaîne réutilisable ; file de tâches fiable sans relance ambiguë des générations.
- Tester plusieurs contenus, la continuité des personnages, les voix et la fiabilité du MP4.
- Mesurer durée, taux d'échec, consommation CPU/GPU/RAM, stockage, kWh et coût par vidéo.
- Viser **3 vidéos par semaine** initialement, cadence ajustable selon la qualité et le temps disponible.
- **Gate B :** un lot de vidéos distinctes a été publié volontairement, sans correction manuelle technique répétitive ni pertes de données.

### Phase C — Validation économique (P1)

- Tester la diffusion sur les réseaux pertinents, selon leurs conditions du moment et les droits des contenus.
- Suivre par plateforme : impressions, rétention, vues, engagement, abonnés, recettes encaissées, coûts directs, temps manuel.
- Seuil de décision fixé à **200 € / mois de bénéfice après coûts directs**, idéalement observé **3 mois consécutifs** pour éviter de conclure sur un pic isolé.
- L'objectif financier est un **critère d'expérimentation**, pas une garantie ; ne pas bâtir le plan sur la seule monétisation publicitaire des vues.
- **Gate C :** rentabilité reproductible et outil stable ; décision humaine documentée avant toute ouverture commerciale.

### Phase D — SaaS public et abonnements (P3, différée)

À envisager **seulement si Gate C est franchi et qu'une validation explicite le demande** : gestion des comptes et rôles, isolation multi-tenant testée, facturation, abonnements, quotas, factures, suppression/portabilité RGPD, sauvegardes isolées, monitoring d'exploitation, conditions d'utilisation et support. La mise en ligne n'est jamais une conséquence automatique d'une PR ou d'un bon résultat économique.

## 4. Architecture cible « local-first »

### Éléments déjà présents dans le dépôt (présence ≠ recette PC)

- FastAPI / Python : API et studio web privé ; frontend HTML / CSS / JavaScript.
- PostgreSQL : histoires, révisions, états, historique et audit.
- Qwen avec llama.cpp : génération de texte/storyboard en local.
- Service image local distinct : interface de génération PNG configurable ; nécessite moteur et modèle réellement disponibles.
- MinIO : références privées de médias ; code prévu pour images, WAV, MP4, SRT et manifeste.
- Docker Compose : PostgreSQL / MinIO ; Redis est optionnel et **n'est pas** la file de traitement éditoriale effective documentée dans le README.
- CI, tests et workflows de livraison privée : la présence des fichiers ne prouve pas leur exécution effective ni le SHA actif sur le PC.

### Composants techniques recommandés, uniquement après test de compatibilité

- **Montage et encodage :** FFmpeg pour fabriquer le MP4 avec images fixes, panoramiques/zooms, transitions, voix, musique et sous-titres.
- **Voix locale :** moteur TTS open source léger (ex. Piper, à comparer avec les licences et voix françaises disponibles).
- **Reconnaissance / alignement facultatif :** Whisper/whisper.cpp pour obtenir les repères temporels, ou alignement sur texte TTS lorsque disponible.
- **Graphismes :** moteur Stable Diffusion local compatible avec le matériel et 8 Go VRAM ; mesurer la vitesse et la qualité, ne pas présumer d'une accélération GPU opérationnelle.
- **Stockage :** MinIO pour actifs pérennes, PostgreSQL pour métadonnées ; conserver un espace temporaire disque pour FFmpeg et les récupérations après erreur. MinIO n'est pas, à lui seul, une accélération garantie.
- **Pilotage :** tâches asynchrones persistantes, limite de concurrence GPU, statut explicite et contrôle du coût/temps.

**Stratégie matérielle :** Windows 11 / WSL2, Ryzen 5 5500, 32 Go RAM, Radeon RX 580 8 Go. Génération de texte, audio, illustrations de taille maîtrisée et montage de scènes illustrées : **plausibles** en local. Génération IA vidéo fluide multi-scènes en 1080p : **risquée en temps de calcul et compatibilité**, à traiter en amélioration optionnelle ; la génération des images peut nécessiter un ajustement de modèles/résolution, des traitements CPU ou un futur changement matériel. Aucun débit de vidéos/minute n'est promis sans benchmark réel.

## 5. Mesures et indicateurs

- **Production :** vidéos exportées et validées / semaine, % de vidéos finies sans reprise, délai total et temps manuel par vidéo.
- **Qualité :** images cohérentes, erreurs factuelles détectées, lisibilité sous-titres, problèmes son/vidéo, avis à la recette.
- **Technique :** statuts des traitements, échecs, reprises, coût GPU/CPU, tailles MinIO, tests CI, SHA PC prouvé.
- **Audience :** rétention, partages, abonnements, visionnages selon plateforme.
- **Rentabilité :** encaissements réels moins électricité imputable, hébergement éventuel, logiciels/services, licences, matériels amortis si pertinent, et autres coûts directs. Le temps humain est suivi séparément pour piloter la véritable rentabilité du projet.
- **Objectif économique :** au moins **200 € mensuels de bénéfice après coûts directs** ; poursuivre l'expérimentation seulement si la tendance, la qualité et le temps consacré le justifient.

## 6. Priorités techniques concrètes

**P0** — Corriger les tests/CI et la recette locale ; empêcher les réponses asynchrones périmées d'écraser la navigation ; démontrer un MP4 entier.  
**P1** — Vérifier l'intégrité des PNG, les sauvegardes MinIO et la récupération ; fiabiliser voix/SRT/montage ; simplifier l'UX ; produire un suivi par vidéo.  
**P2** — Réduire les coûts et la charge : cache de résultats stables, quotas locaux, profiling, rendu parallèle seulement si mesuré sûr, alertes MCO utiles.  
**P3** — Multi-tenant, facturation, rôles commerciaux, analytics clients et publication automatisée : **pas avant décision explicite**.

Ne pas appliquer des correctifs génériques qui diminuent la sécurité réelle du MVP (en-têtes de proxy acceptés sans liste de confiance, CSRF relâché, limitation IP contournable, interdiction des adresses locales du LLM). Vérifier les tests existants avant toute transformation.

## 7. Graphify et skills d'agent — règle d'adoption

**Statut : intéressant, optionnel, pas installé ni activé par ce document.**

Graphify (`graphifyy` sur PyPI ; commande `graphify`) peut fournir une cartographie navigable de classes, imports, fonctions, dépendances et points de passage du projet, et aider un agent Codex à identifier les fichiers à modifier. Le parcours documenté inclut `graphify install --platform codex` et le skill `$graphify`, avec des fichiers dans `graphify-out/` comme `graph.html`, `GRAPH_REPORT.md`, `graph.json`.

Adoption conditionnelle :

1. Identifier le **dépôt officiel**, la licence, la version exacte et les dépendances avant installation ; inspecter les scripts et permissions.
2. Privilégier un environnement **isolé**, sans accès aux secrets réels, au système de livraison ni aux volumes PostgreSQL/MinIO.
3. Tester sur une **copie du dépôt débarrassée des secrets**, pas sur la configuration de production ; confirmer qu'aucun contenu sensible n'est publié dans le rapport ou le graphe.
4. Désactiver/omettre les éventuels backends LLM ou fonctions cloud pour l'essai code-only ; la cartographie du code peut fonctionner localement sans LLM, mais les autres modes peuvent contacter un modèle.
5. Générer d'abord en local, puis inspecter les sorties, la volumétrie et les chemins avant tout commit ou diffusion.
6. Ne pas interpréter un graphe comme une preuve d'absence de faille ni comme une substitution aux tests et à une revue de code.
7. Tout autre skill externe doit passer le même filtre : **valeur pour la production ou la maintenance, source contrôlée, exécution non destructive, pas de secrets, tests, accord avant installation PC**.

Documentation vérifiée le 18/10/2026 : https://github.com/Graphify-Labs/graphify et https://github.com/Graphify-Labs/docs/blob/main/quickstart.mdx ; paquet https://pypi.org/project/graphifyy/ .

## 8. Gouvernance et mise à jour de cette charte

- Toute PR et toute évolution doivent préciser : **quels critères de cette charte elle sert**, preuve de test et impacts sur la chaîne vidéo.
- Une tâche « présente dans Git » ne doit jamais être déclarée « livrée sur PC » sans preuve du commit installé et recette réelle.
- Les évolutions **peuvent** être proposées et documentées ; les changements de mission/positionnement, l'ouverture publique, les coûts récurrents et les livraisons nécessitent validation humaine.
- Cette charte constitue une **baseline de référence** ; les futures révisions portent un numéro, une date, un résumé du changement et l'accord du porteur du projet. Ne jamais réécrire rétroactivement une décision comme si elle avait toujours été différente.

**Synthèse figée :** *Créer de bonnes vidéos bretonnes avec Arvor, de manière locale et économique ; atteindre durablement 200 €/mois grâce à leur exploitation ; seulement ensuite décider si Arvor mérite de devenir un SaaS commercial.*