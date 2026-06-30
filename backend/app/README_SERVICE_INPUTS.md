# Mise à jour : Services & temps modifiables

## Fichiers à remplacer / ajouter

Copier dans :

```text
C:\Users\gesco\Documents\Calculateur-de-contrat\dealer-quote-manager\backend\app\
```

- `database.py`
- `apply_pricing.py`
- `main.py`
- `service_catalog.py`

## Relance

Arrêter le serveur avec CTRL+C, puis :

```powershell
cd C:\Users\gesco\Documents\Calculateur-de-contrat\dealer-quote-manager\backend\app
python database.py
python main.py
```

## Nouveautés

- Nouvelle table `quote_services`
- Nouvelle page “Services & temps”
- Pour chaque service :
  - inclure / exclure
  - temps h
  - quantité
  - prix unitaire
  - prix fixe
  - extra travel
- Recalcul du devis avec les services additionnels sélectionnés

## Important

Cette V2 ajoute les services sélectionnés au coût importé.
Si l’export ServiceCalculation contient déjà la maintenance de base, ne coche pas le service correspondant en plus, sinon il y aura doublon.
