# REL-004 — Preuve read-only de livraison et recette vidéo 75 secondes

Date : 18 octobre 2026. Périmètre : contrôles complémentaires, **aucune livraison PC et aucune migration**.

## 1. Attestation de la release effectivement exécutée

Depuis le checkout de la release à diagnostiquer et sur le PC concerné :

```bash
python scripts/verify_pc_release.py \
  --root /home/yoann_admin/editorial-runtime \
  --expected-sha <SHA_COMPLET_40_CARACTERES>
```

Remplacer le marqueur par le SHA Git **explicitement attendu** (ne pas le déduire du reçu à vérifier).
Le script n'utilise que des lectures locales et trois GET loopback : `/health`, `/ready`, `/studio`.
Il exige toutes les preuves suivantes simultanément :

- `current` est un lien vers un sous-répertoire direct de `releases/` portant le SHA exact ;
- `last_delivery.json` est un fichier régulier, porte le même SHA et les preuves `passed` du contrat actuel, y compris migration seulement sur la DB jetable et accès métier en lecture seule ;
- `editorial-api.service` est actif, son WorkingDirectory est le lien `current`, et le répertoire réellement exécuté par son MainPID est cette release ;
- `/health=200` avec `status=ok`, `/ready=200` avec `ready=true` et `/studio=200`.

Code retour 0 avec `verified=true` seulement si tout concorde. Sinon code 1 et motif générique sans secrets. Cela complète le diagnostic historique `scripts/diagnose_runtime.py` qui donne des indices, mais **ne constitue pas à lui seul une preuve d'identité du processus**.

Ne jamais interpréter cette attestation comme autorisation de mise en production : elle vérifie uniquement un état présent. Elle ne prouve ni la durée de vie du service après cette lecture, ni la qualité éditoriale, ni le fonctionnement de l'IA ou de la génération d'images. En cas d'échec, utiliser `docs/mco/RUNBOOK_DIAGNOSTIC_PC.md` ; ne pas supprimer de release, redémarrer, fusionner ou restaurer des données automatiquement.

## 2. Recette technique de vidéo 75 secondes

Le script `scripts/smoke_video_75.py` fabrique une image PNG synthétique dans un dossier temporaire, puis utilise **le vrai moteur FFmpeg du projet** pour exporter une vidéo verticale de 75 secondes avec fichier SRT. `ffprobe` confirme durée (tolérance de 0,25 s), flux vidéo unique et résolution 720×1280. Tous les médias et la sortie sont temporaires. Pas de base, Qwen, stockage MinIO, données privées ni publication.

Exécution après installation **préalablement approuvée** de FFmpeg :

```bash
python -m scripts.smoke_video_75
```

Depuis GitHub : workflow **Synthetic 75s video acceptance**, manuel ou sur PR modifiant le moteur vidéo ou son test. Une CI GitHub indisponible / sans runner ne vaut pas réussite ; l'exécution doit porter la preuve d'un job terminé avec ses étapes. Les tests Python `tests/test_verify_pc_release.py` et `tests/test_smoke_video_75.py` restent inclus dans la régression normale. Ils sont synthétiques : seuls le workflow FFmpeg réel et la recette PC permettent d'affirmer une exportation vidéo réelle.

## 3. Sécurité, limites et décision

### Revue corrective du 18 octobre 2026

Deux défauts corrigés avant validation : la sonde `/studio` appliquait la
limite JSON de 8 Ko au HTML réel de plus de 12 Ko, et la comparaison de durée
acceptait `NaN`. Le statut Studio est désormais lu sans télécharger son corps ;
les réponses `/health` et `/ready` restent bornées à 8 Ko. La durée FFprobe
doit être finie. Aucun accès, redémarrage ou changement PC ajouté.

TDD local Python 3.12.14 : nouveaux cas en erreur/échec avant correction,
puis 12 tests ciblés réussis, 0 échec/erreur/skip. Réseau bloqué pendant ces
tests et variables d'environnement vidées ; preuves PC simulées uniquement.
Le smoke FFmpeg réel corrigé a aussi réussi localement : média synthétique,
MP4 75 s, 720×1280, SRT finissant à 75 s, fichiers temporaires nettoyés.
Il ne teste pas encore le profil `--arvor-75` de la PR #209 ni la voix,
Qwen, MinIO, les contrats HTTP métier, PostgreSQL ou le PC réel.

Le workflow vidéo initial `39137918929` a échoué sans étapes. Le résultat
local ne remplace ni la régression historique complète 3.12/3.14 ni les
contrôles requis sur le nouveau SHA. L'attestation croise nom de release,
reçu, service et cwd ; elle n'est pas une vérification cryptographique du
contenu installé ni une preuve que le socket HTTP appartient à ce PID.

Les scénarios sont séparés : l'attestation lit une installation existante ; le smoke vidéo écrit **uniquement dans un répertoire temporaire neuf**. Aucune des deux commandes n'autorise un SHA, ne modifie la base, ne change la configuration ou ne déclenche `deploy_local.py`.

Si les runners GitHub Actions restent bloqués **avant le démarrage des étapes** (incident du 18 octobre, PR #210), garder la PR en brouillon et lever le blocage infrastructure par les vérifications du propriétaire GitHub. N'annoncer ni CI verte, ni MEP PC, ni résultat vidéo 75s tant que les jobs correspondants ne sont pas exécutés.

### Critères d'acceptation

- [x] Tests isolés du vérificateur sur reçus incohérents, mauvais SHA, service inactif, répertoire PID différent, API non prête.
- [x] Contrôle FFmpeg/FFprobe prévu sur média synthétique et 75 secondes exactes.
- [ ] Exécution du job GitHub Actions vidéo 75s sur un runner opérationnel.
- [ ] Régression complète + audit de sécurité réels sur SHA de PR.
- [ ] Diagnostic de release sur le vrai PC, en lecture seule.
- [ ] Toute nouvelle livraison sur PC : approbation spécifique du SHA complet, indépendante de cette PR.
