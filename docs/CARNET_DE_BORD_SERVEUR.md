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

## Module maintenance logiciel

### Objectif

Prévoir dès la conception serveur un module permettant la maintenance technique du logiciel par une personne autorisée, qui ne sera pas forcément le créateur initial.

Ce module est différent du Super Admin commercial.

### Différence entre Super Admin et Maintenance

SUPER_ADMIN :
- gestion des sociétés clientes
- gestion des licences
- gestion des utilisateurs clients
- activation ou suspension des accès
- suivi commercial et administratif

TECH_ADMIN :
- état du serveur
- version du logiciel
- sauvegardes
- journaux d'erreurs
- espace disque
- tests système
- mode maintenance
- suivi des mises à jour
- diagnostic technique

### Rôles internes à prévoir

- OWNER : propriétaire / éditeur principal du logiciel
- SUPER_ADMIN : administration clients, sociétés, licences
- TECH_ADMIN : maintenance technique complète
- TECH_SUPPORT : support technique limité
- COMPANY_ADMIN : administrateur d'une société cliente
- CONTRACT_MANAGER : utilisateur principal côté client
- TESTER : utilisateur test limité

### Fonctions futures du module maintenance

- afficher la version installée
- afficher l'état général du serveur
- vérifier la connexion base de données
- vérifier l'espace disque
- consulter les dernières erreurs
- vérifier les sauvegardes
- tester l'envoi email
- tester Google Agenda
- tester la signature électronique plus tard
- activer un mode maintenance
- consulter le journal des mises à jour

### Règle de confidentialité

Un utilisateur de maintenance ne doit pas voir automatiquement toutes les données sensibles des clients.

À terme, il faudra prévoir :
- support niveau 1 sans accès aux marges ni PDF clients
- support niveau 2 avec accès temporaire autorisé
- accès complet réservé au propriétaire ou à un profil technique validé

### Décision

Le module maintenance n'est pas une fonction vendue aux clients.
C'est un outil interne pour assurer la stabilité, les mises à jour et le support du logiciel.
