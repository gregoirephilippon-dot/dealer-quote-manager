# Dealer Quote Manager — Prototype d'import

Premier socle du futur logiciel : importer un fichier `ServiceCalculationExport.xlsx` et produire un JSON propre.

## Installation

```bash
cd dealer-quote-manager
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Sur Mac/Linux :

```bash
source .venv/bin/activate
```

## Utilisation

```bash
python backend/app/importers/service_calculation_importer.py ServiceCalculationExport.xlsx --out data/examples/service_calculation_summary.json --pretty
```

## Ce que l'importeur extrait

- informations moteur,
- base de calcul,
- résultats globaux,
- lignes de l'onglet `Hidden for import`,
- planning depuis `Overview`,
- détails des onglets par intervention,
- profitability,
- premier brouillon de devis.

## Prochaine étape

Créer une petite base SQLite et enregistrer automatiquement le `quote_draft` dans une table `devis`.
