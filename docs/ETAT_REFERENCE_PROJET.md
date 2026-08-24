# ETAT DE REFERENCE PROJET — DEALER QUOTE MANAGER

Date de référence : 24/08/2026
Branche : serveur-v1
Commit serveur validé : 36c03ea
Statut : RECETTE V1 VALIDEE

---

## 1. OBJECTIF V1

Dealer Quote Manager permet de :

- importer un devis / calcul Volvo ;
- récupérer les pièces, main-d'oeuvre et services ;
- appliquer les règles commerciales dealer ;
- appliquer les indexations annuelles ;
- calculer les services additionnels ;
- gérer huile et coolant ;
- appliquer les remises client ;
- calculer les frais logistiques, administratifs et déplacement ;
- produire un prix total, mensuel et par heure ;
- proposer les packages Base Care, Comfort Care et Advanced Care.

---

## 2. PACKAGES VALIDES

### Base Care

Services :

- 1,1
- 1,2
- 1,3
- 1,4
- 2,1
- 3,1
- 3,3_1
- 3,3_2
- 3,3_3

### Comfort Care

Services :

- 1,1
- 1,2
- 1,3
- 2,2
- 3,1
- 3,2
- 3,3_1
- 3,3_2
- 3,3_3
- 4,1
- 4,2

### Advanced Care

Services :

- 1,1
- 1,2
- 1,3
- 2,2
- 2,3
- 3,1
- 3,2
- 3,3_1
- 3,3_2
- 3,3_3
- 4,1
- 4,2
- 6,1

IMPORTANT :

- Il n'existe pas de package "Basic".
- "Basic engine status" est un service, pas un package.
- Les customizations sont une couche optionnelle séparée.

---

## 3. REGLES SERVICES 2.x

### 2,1

Maintenance parts / components uniquement.

### 2,2

Maintenance parts + labour.

### 2,3

Preventive repair parts + labour.

### Protection anti-double comptage

Si 2,2 est présent :

- 2,1 ne doit jamais rajouter les pièces de maintenance une seconde fois.

Cette règle s'applique :

- aux services issus de l'import ;
- aux sélections manuelles ;
- aux packages.

### Service 2,2 importé Volvo

Si le service 2,2 est détecté dans l'import Volvo :

- il est automatiquement inclus ;
- il est verrouillé ;
- un package ne peut pas le supprimer ;
- son montant importé ne doit pas être ajouté une seconde fois.

---

## 4. PRICING PIECES

Le calcul pièces distingue :

- prix catalogue / référence ;
- discount code ;
- remise dealer ;
- coût net dealer ;
- remise client ;
- prix client.

Les remises client peuvent être différentes selon les lignes / DC.

La remise client est appliquée avant indexation.

Validation serveur effectuée avec remises client non nulles.

Statut : VALIDE.

---

## 5. MAIN-D'OEUVRE

La main-d'oeuvre importée est conservée comme base.

Le taux horaire dealer est configurable.

La marge main-d'oeuvre est appliquée selon les paramètres.

Statut : VALIDE.

---

## 6. INDEXATIONS

Les indexations annuelles sont cumulatives.

Exemple validé :

- année 1 : facteur 1,00
- année 2 : +10 % -> 1,10
- année 3 : +10 % -> 1,21

Les indexations sont gérées dans les paramètres de calcul.

Statut : VALIDE.

---

## 7. FLUIDES

Les fluides sont gérés séparément :

- huile moteur ;
- coolant.

### Huile

Fonctions validées :

- référence catalogue ;
- prix par litre ;
- nombre de services ;
- quantité par service ;
- conditionnement ;
- litres consommés ou packs entiers ;
- remise dealer ;
- remise client ;
- neutralisation de l'huile importée si remplacement activé.

### Coolant

Fonctions validées :

- référence catalogue ;
- prix par litre ;
- nombre de services ;
- capacité circuit ;
- concentré / ready mixed ;
- pourcentage de concentré ;
- conditionnement ;
- remise dealer ;
- remise client ;
- neutralisation du coolant importé si remplacement activé.

### Compatibilité coolant

Alerte prévue si :

- type sélectionné incompatible avec le type importé identifiable ;
- type importé impossible à identifier.

Familles actuellement distinguées :

- Vert
- VCS-2 / Orange

### Cas de recette serveur validés

- huile seule : VALIDE
- coolant seul : VALIDE
- aucun fluide actif : VALIDE
- huile + coolant : VALIDE
- remises client fluides : VALIDE
- coût dealer fluides : VALIDE
- routage fluides vers 2,2 : VALIDE

IMPORTANT :

Un fluide peut conserver un montant théorique calculé dans la trace tout en étant désactivé.

Dans ce cas :

- software_active = false
- active_total = 0
- il ne doit pas entrer dans le total du devis.

---

## 8. FRAIS

### Déplacement

Frais fixes de déplacement supportés.

Test avec montant non nul validé.

### Logistique

Pourcentage appliqué sur la base prévue par le moteur de pricing.

### Administration

Pourcentage appliqué sur la base prévue par le moteur de pricing.

Statut : VALIDE.

---

## 9. TRACE DE CALCUL

Le moteur génère pricing_trace_json.

La trace permet de contrôler :

- import ;
- pièces ;
- coût dealer ;
- prix client ;
- remises ;
- main-d'oeuvre ;
- services ;
- fluides ;
- frais ;
- indexations ;
- résultat final.

Statut : VALIDE.

---

## 10. DEVIS DE REFERENCE

### Devis serveur 8

Utilisé pour la recette packages.

Etat de référence validé :

- Advanced Care
- total : 31 965,7595 EUR
- mensuel : 532,7626583333333 EUR
- prix / heure : 3,364816789473684 EUR/h
- fluid_total : 2 152,80 EUR
- huile : 24567221
- huile : 3 services
- huile : 30 L / service
- conditionnement huile : pack 20 L
- coolant : 24712786
- coolant : 0 service

Ne plus utiliser ce devis pour les tests destructifs.

### Devis serveur 9

Utilisé pour les cas limites.

Validations :

- remises client non nulles
- huile seule
- coolant seul
- aucun fluide

---

## 11. COMMITS DE REFERENCE

Principaux commits V1 :

- 36c03ea — Add coolant compatibility warning and generalize 2.1 2.2 protection
- 88be66d — Complete oil and coolant pricing module
- a0d8784 — Align care package service mapping
- 3d05910 — Add pricing calculation trace display
- f9d417e — Align care packages and prevent 2.1 2.2 double count
- 49c57e8 — Fix care packages Volvo lock and contract hours
- f535094 — Import control alert
- 4f1b183 — Detect/lock imported Volvo maintenance service
- 6123baf — Add fluid catalog lookup
- 0bbe5cc — Add overview fluid replacement option
- 482a798 — Cumulative legacy Excel indexation alignment
- 2c75393 — Separate imported Volvo hours from contract hours
- 51a2ac8 — Final client maintenance contract PDF
- 210253a — Show oil and coolant total in internal HTML report
- 64a6e7e — Add oil and coolant calculation to maintenance services
- cbd9dab — Parts pricing by dealer DC
- f05b1b0 — Remove global parts margin setting
- 57d2dca — Cumulative indexations
- bccd435 — Yearly indexations
- cbf6f80 — Move indexations to settings

---

## 12. DEPLOIEMENT SERVEUR

VPS :

- répertoire : /opt/dealer-quote-manager
- branche : serveur-v1
- service : dealer-quote-manager.service
- commit déployé et validé : 36c03ea

Adresse actuellement utilisée :

http://152.228.238.47:8001/

---

## 13. NE PAS REFAIRE SANS REGRESSION CONSTATEE

Ne pas reprendre les sujets suivants sans preuve de régression :

- architecture des packages ;
- suppression du package Basic ;
- mapping Base / Comfort / Advanced ;
- verrouillage du 2,2 importé ;
- anti-double comptage 2,1 / 2,2 ;
- pricing trace ;
- calcul dealer par DC ;
- remise client ;
- indexations cumulatives ;
- moteur huile ;
- moteur coolant ;
- dilution coolant ;
- conditionnement fluides ;
- neutralisation fluides importés ;
- alerte compatibilité coolant ;
- déplacement ;
- frais logistiques ;
- frais administratifs ;
- calcul final ;
- prix mensuel ;
- prix par heure.

---

## 14. REGLE GIT

Aucun :

- git add
- git commit
- git push

avant validation visuelle / comportementale de la modification concernée.

---

## 15. ETAT V1

### VALIDE

- moteur pricing principal
- packages
- services 2.x
- remises dealer
- remises client
- main-d'oeuvre
- indexations
- fluides
- frais
- pricing trace
- calcul total
- calcul mensuel
- calcul horaire
- serveur

### A TRAITER APRES V1

- amélioration UX
- historique et comparaison de devis
- exports professionnels supplémentaires
- statistiques de marge
- alertes d'incohérence supplémentaires
- automatisations Volvo supplémentaires
- décision métier définitive sur prix importé vs prix catalogue courant

---

## 16. REGLE DE REPRISE

Avant toute nouvelle modification :

1. lire ce fichier ;
2. vérifier le commit courant ;
3. ne pas rouvrir un élément marqué VALIDE sans régression démontrée ;
4. faire une modification limitée ;
5. tester localement ;
6. faire valider visuellement / comportementalement ;
7. seulement ensuite utiliser Git.

---

FIN ETAT DE REFERENCE V1
