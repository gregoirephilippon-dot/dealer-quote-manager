# Carnet de bord serveur - Dealer Quote Manager

## Objectif

Préparer Dealer Quote Manager pour une version serveur sécurisée, multi-utilisateur, hébergeable souplement.

## Branche

Branche de travail : serveur-v1

## Version de départ

La branche serveur-v1 démarre depuis la version locale stable comprenant :

- import Service Calculator
- historique devis
- calcul coût / prix / marge
- export PDF avec marge
- retour d'expérience local
- retour d'expérience Google Sheet
- package EXE local validé

## Priorité actuelle

Ne pas ajouter les modules métier avancés tout de suite.

Priorité 1 :

- configuration serveur portable
- préparation hébergement
- préparation base PostgreSQL
- utilisateurs
- sociétés
- rôles
- séparation des données par société
- sécurité

## Architecture cible

- Backend : Python + FastAPI
- Base : PostgreSQL pour serveur
- SQLite conservé pour tests locaux si utile
- Stockage fichiers : storage/uploads, storage/pdf, storage/logos, storage/contracts
- Configuration : fichier .env
- Déploiement : serveur classique ou Docker plus tard
- Utilisation client : navigateur, sans installation locale

## Règles de développement

1. Une étape à la fois
2. Test local avant commit
3. Commit après validation
4. Ne pas casser main
5. Préparer le code pour serveur, pas seulement pour PC local
6. Garder une trace des décisions dans ce carnet

## Étapes prévues

### Phase 1 - Socle serveur

- créer configuration .env
- centraliser les chemins
- préparer storage
- préparer DATABASE_URL
- préparer SECRET_KEY

### Phase 2 - Utilisateurs et sociétés

- créer table companies
- créer table users
- créer rôles
- ajouter login
- rattacher les devis à une société

### Phase 3 - Mise en ligne privée

- préparer serveur test
- HTTPS
- comptes testeurs
- import Excel
- historique
- PDF
- feedback

### Phase 4 - Modules métier futurs

- logo société dans PDF
- contacts intelligents
- contrat type personnalisable
- validation dirigeant
- signature électronique
- contrat actif
- alertes fin contrat
- Google Agenda
- atelier / magasin
- campagnes Volvo pièces
