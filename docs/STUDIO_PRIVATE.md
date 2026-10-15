# Arvor Studio — interface éditoriale privée (WEB-001)

## Portée
Première interface **fonctionnelle** servie par FastAPI à `/studio`, sans framework JS ni services externes additionnels.
- Connexion web privée, session HttpOnly et protection CSRF.
- Liste des exécutions du tenant courant, pagination par curseur et filtre local sur la page chargée.
- Création d'histoire (brief strict, 1 à 6 scènes, 15 à 180 secondes).
- Consultation du storyboard structuré : scènes, narration, plans, émotions, couleurs, personnages, sons et prompts image.
- Analyse éditoriale et points historiques à vérifier.
- Historique des traitements (prompts et résultats), revue humaine : accepter, rejeter ou réviser dans l'éditeur guidé (champs structurés validés côté serveur, schémas Pydantic) ; journal paginé.
- États vides, chargement, erreurs HTTP, affichage sur ordinateur et téléphone.

**Ce qui n'est pas livré** : images produites, générateur vidéo, éditeur riche WYSIWYG (l'éditeur guidé par champs est livré), multi-comptes SaaS, liens publics et publication. L'interface peut afficher les *prompts* image stockés, pas des images qui n'existent pas.

## Configuration (PC privé)
L'application FastAPI existante charge déjà son fichier `.env`. Ajouter, sans versionner le secret :

```dotenv
EDITORIAL_WEB_PASSWORD=<secret distinct de 32 caractères minimum>
```

Conserver les variables existantes : `EDITORIAL_API_TOKEN` (32 caractères min.), `EDITORIAL_TENANT_ID`, `EDITORIAL_ACTOR_ID`, `PO_DATABASE_URL`, `LLM_BASE_URL`. Le mot de passe du studio **doit être différent** du jeton API. Un mot de passe absent, trop court ou identique au jeton rend la connexion impossible (503).

Démarrer avec **un seul worker** dans l'environnement privé déjà prévu :

```bash
.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Puis ouvrir **http://localhost:8000/studio** depuis le PC. Pour un accès depuis un téléphone, placer l'application derrière un reverse proxy HTTPS authentifié, en configurant et vérifiant la terminaison TLS et la gestion des en-têtes de protocole; **ne pas** exposer le port HTTP brut à Internet. La passerelle refuse les requêtes HTTP non locales. Pour un déploiement HTTPS derrière proxy, le schéma ASGI doit être correctement transmis ; tester cookies Secure et contrôle Origin.

Le mot de passe saisi est comparé côté serveur et n'est pas stocké dans le navigateur. Le cookie aléatoire est HttpOnly, SameSite=Strict, et Secure pour les requêtes HTTPS. Le jeton API, le tenant et l'acteur restent côté serveur. Les POST exigent Origin identique + X-CSRF-Token. En-têtes no-store/CSP/frame-ancestors. Maximum 5 échecs de connexion par IP en 15 minutes (par processus).

## Limites de sécurité et exploitation
- Sessions **en mémoire**, expirées après huit heures; un redémarrage déconnecte les navigateurs; la déconnexion supprime la session.
- Utiliser **un processus/worker**. Un magasin de sessions partagé et un mécanisme robuste de rate-limit sont nécessaires avant un déploiement multi-instances.
- Cette authentification est adaptée à un **atelier privé mono-identité**, pas à un SaaS public. Audit, identité, tenant et accès restent fixés par la configuration de l'API.
- Ne pas mettre `EDITORIAL_WEB_PASSWORD` dans le code, les logs, les captures, Slack ou Git.
- Un échec timeout/5xx après une création peut avoir laissé une exécution en cours : la clé d'idempotence reste associée au brief dans le navigateur pour une **reprise explicite uniquement**. Vérifier PostgreSQL avant toute reprise opérationnelle.
- Un 409 de revue impose de recharger; aucune décision n'est envoyée automatiquement après un conflit.
- Les contenus de l'histoire, les prompts et les sorties sont affichés seulement après session valide. Le contenu dynamique est injecté via `textContent` (pas de HTML arbitraire).
- La recherche dans le menu ne porte que sur les exécutions chargées; le compteur avec «+» signale des pages non encore chargées.

## Vérifications et reprise
1. Tests de sécurité et contrats : `python -m unittest tests.test_studio -v`.
2. Régression totale : `python -m unittest discover -s tests -v` avec PostgreSQL de test isolé, `PO_TEST_DATABASE_URL` et `PO_ALLOW_TEST_MIGRATION=yes`.
3. Tester manuellement : connexion/déconnexion, liste, pagination, nouveau brief, analyse, scènes, revue, révision, erreur 409, téléphone, clavier, erreurs 401/422/503.
4. Valider le SHA exact et les tests avec un parcours Qwen **réel** sur le PC avant de qualifier la livraison.
5. Retour arrière : revenir à l'ancienne release FastAPI. Cette PR n'ajoute aucune migration ni tâche automatique. Les histoires déjà historisées sont conservées.

Ne pas considérer l'acceptation produit acquise sur la seule base de tests techniques verts.

## Revue et parcours navigateur (14 octobre 2026)

La régression API/PostgreSQL ne suffit pas à prouver l'usage du navigateur. La CI dédiée exécute les parcours Chromium contre une API simulée jetable, sans modifier la base utilisateur : connexion/déconnexion, lien direct, création, scénarios, analyse, historique, approbation, rejet, révision, pagination, recherche, navigation précédente, mobile, conflit 409, JSON invalide et reprise explicite après interruption réseau. Elle ne remplace pas la recette finale Qwen/PostgreSQL/PC réels.

## Garde de livraison ajouté à l'audit sécurité (14 octobre 2026)

Toute future activation PC exige désormais un `EDITORIAL_WEB_PASSWORD` différent du jeton API, d'au moins 32 caractères, enregistré dans la configuration privée du processus (non versionnée). Avant de basculer la release et après redémarrage, la livraison vérifie en boucle locale HTML, CSS/JS, absence de session, connexion privée, lecture de bibliothèque authentifiée et déconnexion effective. Un échec empêche ou annule la bascule. Le parcours Qwen/PostgreSQL réel reste testé séparément; ces sondes ne constituent pas une recette fonctionnelle utilisateur exhaustive.

La route de compatibilité `/ai/generate` exige une identité et un jeton API même en boucle locale. La capacité de génération est bornée à deux exécutions simultanées par processus avec HTTP 429 en surcharge. Cette protection n'est pas un quota SaaS distribué et ne remplace pas une limitation par utilisateur ou tenant.

Les tests de sécurité et de livraison sont exécutés en CI sur PostgreSQL jetable et via HTTP simulé; aucune configuration PC ni base utilisateur n'est modifiée par les tests.


## Personnages et visuels privés (MEDIA-001, code proposé)

Un nouvel onglet Studio recense les personnages (fiches Qwen facultatives,
compatibilité des anciennes histoires), leurs apparitions et les prompts image.
La génération d'images requiert la validation de l'analyse et du storyboard,
une action explicite par scène, un modèle d'images local distinct de Qwen et
le stockage `EDITORIAL_MEDIA_ROOT`. L'asset PNG n'est accessible que sous
session Studio ou API authentifiée ; les statuts sont historisés avec audit.
Le modèle d'images **n'est pas installé** par cette évolution. Cf.
[MEDIA_001_VISUAL_INTEGRATION.md](MEDIA_001_VISUAL_INTEGRATION.md).

## Limites d'entrée — revue Lot 1 du 15 octobre 2026

Les corps POST/PUT/PATCH sont bornés globalement à **256 000 octets** avant
parsing FastAPI ; ingestion limitée à **15 secondes** (HTTP 413/408). Le seuil
Studio plus strict de **64 000 octets** reste applicable. Ce délai porte sur
l'envoi du corps, pas sur la génération Qwen. JSON excessivement imbriqué et
mot de passe contenant un surrogate isolé : HTTP 422 ; CSRF non ASCII invalide :
403. Un mot de passe Unicode UTF-8 valide reste utilisable.

Aucune nouvelle variable ni modification de démarrage. Pour un futur upload,
concevoir une route et des limites dédiées avant de relever ce plafond.
Vérifier tests/test_qa_lot1.py puis la CI complète sur DB jetable.
La [revue Lot 1](QA_LOT1_2026-10-15.md) distingue les correctifs de la recette PC.
