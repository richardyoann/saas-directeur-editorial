# Médias MinIO — résultat incertain et reprise

Procédure préventive MEDIA-004, 16 octobre 2026 ; aucun incident réel du PC
diagnostiqué pendant son développement.

- `image_storage_result_uncertain` : arrêter le replay. Le PNG local de secours
  doit rester présent ; chercher l'objet avec les UUID tenant/run/scène et
  vérifier taille/SHA-256. PUT peut avoir réussi malgré un timeout.
- SQL non acquitté après upload : conserver l'objet. Vérifier `po_entity`,
  `po_audit`, `po_outbox` sur les UUID précis et le résultat courant avant
  toute correction. Ne jamais déduire l'échec du commit d'un timeout client.
- Archive CLI interrompue : conserver sources et `minio-archive.jsonl`.
  `started` seul ne prouve pas absence d'objet. `stored` sans `recorded` exige
  vérification SQL ; `recorded` prouve l'acquittement reçu, pas la sauvegarde.
- 412/409 sur PUT : ne pas remplacer ni supprimer l'objet pour faire passer
  le transfert. Comparer la preuve existante et réconcilier manuellement.
- Lecture corrompue : téléchargement refusé et temporaire supprimé. Restaurer
  une copie vérifiée ; ne pas régénérer automatiquement l'image.

Diagnostic initial en lecture seule : santé MinIO, espace disque, bucket privé,
droits du compte applicatif, référence JSONB, HEAD de la clé et version exactes.
Ne pas coller de secrets, textes, noms métier ou journaux privés dans Slack.
Consigner symptôme, preuve, hypothèse confirmée/supposée, correction, validation
et limites suivant le modèle de l'index MCO. Aucune suppression automatique de
source, d'objet, de volume ou de journal n'est fournie.
