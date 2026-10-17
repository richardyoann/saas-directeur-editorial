# Diagnostic PC : reçu de livraison invalide

Le diagnostic en lecture seule ne doit pas s'interrompre lorsque
`last_delivery.json` contient une liste, un scalaire JSON, du texte non UTF-8,
ou une structure JSON trop profondément imbriquée.

Dans ces cas, `receipt_sha` reste null et la cohérence reste fausse.
Un reçu invalide ne constitue jamais une preuve de livraison.
Le fichier et la release ne sont pas modifiés. Aucun contenu de reçu
ni exception brute n'est ajouté à la sortie.

Commande de vérification, depuis le dépôt :

```bash
python -m unittest discover -s tests -p test_runtime_receipt.py -v
```

Validation exécutée dans l'environnement isolé de développement :
6 tests réussis, aucun skip. Les cas non objet déclenchaient auparavant
AttributeError sur `data.get`. Les tests vérifient aussi la conservation
des octets du reçu. Aucun service PC, PostgreSQL, Qwen ou MinIO contacté.
La CI complète et la recette PC restent à effectuer avant livraison.
