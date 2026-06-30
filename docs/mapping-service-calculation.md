# Mapping — ServiceCalculationExport.xlsx

## Onglet `First page`

| Donnée | Source | Destination |
|---|---|---|
| Installation | ligne moteur | engine.installation |
| ChassisID | ligne moteur | engine.chassis_id |
| Serial Number | ligne moteur | engine.serial_number |
| Product Name | ligne moteur | engine.product_name |
| Product Designation | ligne moteur | engine.product_designation |
| Product Part Number | ligne moteur | engine.product_part_number |
| Current Country | ligne moteur | engine.current_country |
| Currency | libellé colonne A | calculation_basis.currency |
| Total No of calculation hours | libellé colonne A | calculation_basis.total_calculation_hours |
| Op hrs / year | libellé colonne A | calculation_basis.op_hours_per_year |
| Labour rate | libellé colonne A | calculation_basis.labour_rate |
| No of service interventions | libellé colonne A | calculation_basis.number_of_service_interventions |
| Total material cost | libellé colonne A | calculation_result.total_material_cost |
| Total labour cost | libellé colonne A | calculation_result.total_labour_cost |
| Total | libellé colonne A | calculation_result.total |

## Onglet `Hidden for import`

| Colonne | Destination |
|---|---|
| Component | hidden_import_lines.component |
| Price | hidden_import_lines.unit_price |
| Time | hidden_import_lines.labour_time |
| Part No | hidden_import_lines.part_number |
| Qty | hidden_import_lines.quantity |

Le script classe automatiquement chaque ligne en :

- `service_group`,
- `labour`,
- `part`,
- `operation`.

## Onglet `Overview`

Utilisé pour extraire :

- les lignes globales,
- les quantités par date,
- les coûts par intervention,
- le coût accumulé.

## Onglets datés

Tous les onglets au format :

```text
YYYY-MM-DD (heures)
```

sont lus comme détails d'intervention.

Exemple :

```text
2027-06-25 (1500)
```

→ date : `2027-06-25`, heures moteur : `1500`.

## Onglet `Profitabillity`

Utilisé pour comparer :

- customer cost,
- workshop cost,
- profitability.
