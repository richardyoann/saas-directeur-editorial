# MCO — résultat image incertain

15 octobre 2026 — classe d'incident reproduite en test avec moteur simulé et
perte d'acquittement PostgreSQL simulée. Aucun incident matériel PC n'est déduit.

## Symptôme et cause

- HTTP 504 : le client a expiré ; le moteur peut encore avoir calculé une image.
- HTTP 502 : rejet, réponse invalide ou résultat réseau incertain ; lire le code
  normalisé de l'asset, pas des logs contenant les prompts.
- HTTP 503 après écriture du PNG : le commit DB peut avoir réussi malgré une
  erreur d'acquittement. La cause exacte côté PC reste à établir.
- Asset `generating` : requête active, interruption ou finalisation incertaine.
  Son âge seul ne prouve pas l'arrêt du moteur.

Le test confirme qu'une erreur DB après écriture conserve le fichier privé et
qu'un deuxième POST est refusé, sans nouvel appel au moteur.

## Diagnostic sans mutation

1. Relever le SHA actif, UUID du run, numéro de scène et état actuel dans Studio.
2. Utiliser « Vérifier les images et leur historique » : il ne génère rien.
3. Examiner le moteur local et son processus, sans l'arrêter ni renvoyer le prompt.
4. Contrôler uniquement les champs techniques en base sous le tenant authentifié :

```sql
SELECT entity_id, version,
       content->>'scenario_id' AS scenario_id,
       content->>'scene_id' AS scene_id,
       content->>'status' AS status,
       content->>'created_at' AS created_at,
       content->>'finished_at' AS finished_at,
       content->>'error_code' AS error_code,
       content->>'duration_seconds' AS duration_seconds,
       content->>'png_sha256' AS png_sha256,
       content->>'outcome_uncertain' AS outcome_uncertain
FROM po_entity
WHERE tenant_id = :tenant_uuid AND kind = 'result' AND NOT deleted
  AND content->>'type' = 'scene_image_asset'
  AND content->>'run_id' = :run_uuid;
```

Les paramètres nommés sont des placeholders à lier dans le client SQL. Ne pas
exporter `content` en entier : il contient le prompt et les descriptions privées.

## Réconciliation explicite

Comparer l'état du moteur, le fichier hors release, l'empreinte et les événements
audit/outbox. Un enregistrement `ready` avec fichier conforme peut être vérifié
en lecture seule ; un fichier seul ne suffit jamais à accepter le résultat.
Si une discordance demeure, conserver le fichier et ouvrir une intervention
liée aux UUID/SHA. Ne pas supprimer l'asset, modifier directement son JSONB,
relancer la génération ou vider les médias pour débloquer le bouton.

Le logiciel ne réconcilie pas automatiquement un asset `generating`/`failed` et
n'annonce aucune reprise matérielle réussie. Une réparation future devra être
transactionnelle, auditée et liée à une preuve de fin du moteur.

## Validation et limite

Tests : classification timeout/HTTP, un seul appel fournisseur, double demande
refusée, conservation du PNG sur erreur d'acquittement, contrôle multi-tenant,
altération d'empreinte détectée et contrôle sans nouvelle écriture auditée.
Les PNG de ces tests sont des fixtures ; les repères textuels et une CI réussie
ne prouvent ni GPU, ni décodage artistique complet, ni cohérence visuelle.
