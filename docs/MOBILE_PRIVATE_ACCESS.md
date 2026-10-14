# Accès HTTPS privé depuis le téléphone (MOBILE-001)

## Principe de moindre exposition

L'application FastAPI reste liée à `127.0.0.1:8000` et à **un seul worker** (sessions Studio en mémoire). Pour ouvrir Arvor Studio sur téléphone, utiliser un tunnel privé TLS plutôt que publier un port ou activer un site public.

Solution proposée : **Tailscale Serve**, accessible uniquement aux appareils autorisés du même tailnet. Le serveur Tailscale doit tourner sur l'hôte qui peut accéder au port `127.0.0.1:8000` de FastAPI. Sur Windows + WSL, confirmer cette connectivité avant toute configuration ; l'emplacement réel de Tailscale (Windows ou WSL) détermine le chemin réseau. Aucune installation ou activation automatique dans ce dépôt.

Documentation officielle : https://tailscale.com/docs/reference/tailscale-cli/serve et https://tailscale.com/docs/features/tailscale-serve

## Préparation locale / conditions

1. Appliquer les mises à jour Tailscale et connecter **PC et téléphone** au même tailnet. Activer les certificats HTTPS pour le tailnet et limiter les accès via les ACL/grants Tailscale.
2. Préserver l'API sur la boucle locale (jamais `0.0.0.0` et pas de redirection de port routeur).
3. Démarrer l'application en conservant le secret Studio et le jeton API **différents** dans sa configuration privée :
   ```bash
   .venv/bin/python -m uvicorn apps.api.main:app \
     --host 127.0.0.1 --port 8000 --workers 1 \
     --proxy-headers --forwarded-allow-ips 127.0.0.1
   ```
4. Ce paramétrage doit être également appliqué au **service systemd réellement utilisé** lors d'une future livraison PC. Le script de livraison ne change pas automatiquement l'unité systemd ; sauvegarder son état puis faire valider cette modification séparément.
5. Sur l'hôte du service, vérifier `curl --fail http://127.0.0.1:8000/studio`. Ensuite, après authentification Tailscale et activation HTTPS sur le tailnet :
   ```bash
   tailscale serve --bg 8000
   tailscale serve status
   ```
   **Ne pas utiliser `tailscale funnel`**, qui rendrait le service public. Ne pas passer `--forwarded-allow-ips '*'` : seul le proxy local (`127.0.0.1`) doit être cru.
6. Le statut Serve donne l'URL réellement attribuée, généralement `https://<nom-machine>.<tailnet>.ts.net/studio`. Ne jamais inventer cette URL : la relever à partir de `tailscale serve status`.
7. Sur Android, avec Tailscale connecté, tester ouverture, connexion, cookies Secure/HttpOnly, revue, déconnexion, puis refus depuis un appareil non autorisé par les ACL. Vérifier le comportement si l'API Windows et le proxy sont dans deux environnements séparés.

## Test de recette et sécurité

- **HTTPS réellement vu par l'application** : une connexion transmise par un proxy de confiance avec `X-Forwarded-Proto: https` doit permettre la page et poser un cookie `Secure; HttpOnly; SameSite=Strict`. Le contrôle d'Origin et CSRF reste obligatoire.
- **Proxy non fiable** : envoyer de faux en-têtes forwarded depuis une IP non autorisée doit être rejeté (HTTP 403) : ne jamais autoriser toutes les sources à définir ces valeurs.
- **Anti-bruteforce** : le proxy de confiance transmet `X-Forwarded-For` ; deux appareils autorisés doivent disposer de compteurs d'échecs distincts (contrôle avec 5 mauvais mots de passe sur l'un, succès sur l'autre). Confirmer sur le vrai proxy : si l'IP n'est pas correctement transmise, bloquer l'accès mobile avant correction.
- **Version SaaS** : cette solution reste mono-identité ; les quotas et sessions en mémoire ne sont pas appropriés pour un service multi-client distribué.
- **Arrêt / retour arrière** : `tailscale serve --https=443 8000 off` ou `tailscale serve reset` après vérification de la configuration affichée. Le reset supprime aussi d'autres services Serve éventuels : ne pas l'exécuter sans audit préalable. Le service local HTTP reste accessible uniquement depuis le PC.

## Non couvert
Aucun URL final vérifié, aucun vrai téléphone relié ni test HTTPS de bout en bout sur le PC à ce stade. Les tests `tests/test_mobile_proxy.py` vérifient le chemin Uvicorn ASGI simulé et non un tunnel Tailscale réel.
