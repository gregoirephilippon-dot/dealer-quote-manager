# Dealer Quote Manager — serveur-v1

Application web interne pour préparer, calculer et suivre les offres de contrats de service dealer.

Cette version `serveur-v1` contient :

- connexion utilisateur,
- gestion des sociétés,
- rôles et accès société,
- import Service Calculator Volvo,
- construction de l'offre de contrat,
- paramètres de calcul dealer,
- codes remises dealer,
- catalogue prix pièces,
- génération d'offre client PDF / HTML,
- protections par société active,
- pages admin protégées,
- confirmations sur les actions sensibles.

## Lancement local

Depuis PowerShell :

```powershell
cd C:\Users\gesco\Documents\Calculateur-de-contrat\dealer-quote-manager

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd backend\app
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

Puis ouvrir :

```text
http://127.0.0.1:8001
```

## Configuration

Copier le modèle :

```powershell
copy .env.example .env
```

Variables principales :

```text
APP_ENV=local
APP_NAME=Dealer Quote Manager
APP_VERSION=serveur-v1
PUBLIC_URL=http://127.0.0.1:8001
SECRET_KEY=change-me-in-production
DATABASE_URL=sqlite:///data/dealer_quote_manager.sqlite
```

Important avant production :

```text
SECRET_KEY doit être remplacée par une vraie valeur secrète.
.env ne doit jamais être commité.
data/ ne doit pas être commité.
```

## Base de données

En local, la base par défaut est :

```text
data/dealer_quote_manager.sqlite
```

Cette base est volontairement ignorée par Git.

## Dossiers ignorés

Les éléments suivants ne doivent pas être versionnés :

```text
.env
data/
*.sqlite
storage/
build/
dist/
release/
direct_*.py
backend/app/*.backup_*
```

## Pages principales

```text
/                         Offres contrats
/login                    Connexion
/logout                   Déconnexion
/settings                 Paramètres calcul
/dealer-discounts         Codes remises dealer
/price-catalog            Catalogue prix pièces
/server/company-switch    Changer société active
/server/context           Contexte société active
/server/users             Gestion utilisateurs
```

## Sécurité actuelle

La version serveur-v1 inclut :

```text
- login obligatoire,
- blocage des utilisateurs inactifs,
- blocage sans accès société actif,
- contexte société active obligatoire,
- filtrage des offres par société,
- blocage accès devis hors société active,
- pages globales réservées OWNER / SUPER_ADMIN / COMPANY_ADMIN,
- page utilisateurs réservée OWNER / SUPER_ADMIN,
- confirmation avant reset des codes remises,
- confirmation obligatoire avant import catalogue pièces.
```

## Checkpoints Git

Checkpoints actuels :

```text
checkpoint-serveur-v1-ux-admin-2026-08-12
checkpoint-serveur-v1-security-admin-imports-2026-08-12
```

## Prochaine étape serveur

Préparation future :

```text
1. configuration production,
2. sauvegarde base,
3. migration PostgreSQL possible,
4. Docker ou service Windows/Linux,
5. déploiement VPS ou serveur interne.
```


## Scripts locaux utiles

### Lancer le serveur local

Double-cliquer sur :

start_server.bat

Ou lancer depuis PowerShell :

.\start_server.bat

### Sauvegarder la base locale

Double-cliquer sur :

backup_database.bat

Ou lancer depuis PowerShell :

.\backup_database.bat

Les sauvegardes sont créées dans :

storage\backups\

### Ancien packaging Windows EXE

Le script suivant est conserve uniquement pour l'ancien mode package portable :

legacy_build_full_package.bat

Le mode actuel serveur-v1 doit etre lance avec :

start_server.bat

### Verifier rapidement le projet

Double-cliquer sur :

check_project.bat

Ou lancer depuis PowerShell :

.\check_project.bat

### Lancer le serveur sur le reseau local

Double-cliquer sur :

start_server_lan.bat

Ce mode permet d'acceder a l'application depuis un autre PC du meme reseau.

Le script affiche l'adresse IPv4 du PC serveur.

Exemple :

http://192.168.86.22:8001

Le mode local simple reste :

start_server.bat

### Restaurer une sauvegarde locale

Double-cliquer sur :

restore_database.bat

Le script liste les sauvegardes disponibles dans :

storage\backups\

Il demande le nom exact de la sauvegarde a restaurer.

Avant remplacement, il sauvegarde automatiquement la base actuelle avec un nom :

avant_restauration_YYYYMMDD-HHMMSS.sqlite

Ne pas utiliser pendant que le serveur est lance.

## PC serveur de test

Cette procédure permet de lancer Dealer Quote Manager sur un PC dédié du réseau local, pour tester l'accès multi-utilisateur depuis d'autres postes.

### 1. Récupérer le projet

Sur le PC serveur :

    cd C:\Users\afric
    git clone https://github.com/gregoirephilippon-dot/dealer-quote-manager.git
    cd dealer-quote-manager
    git checkout serveur-v1

Si le projet est déjà présent :

    cd C:\Users\afric\dealer-quote-manager
    git pull

### 2. Initialiser la base de test

    python backend\app\setup_server_test.py

Ce script prépare une installation serveur de test :

- initialise la base ;
- crée les tables utilisateurs, sociétés et accès société ;
- crée une société de test ;
- crée un compte administrateur de test ;
- ajoute quotes.company_id si la colonne est absente ;
- rattache les devis existants à la société de test si nécessaire.

Compte de test créé :

    Email    : admin@test.local
    Mot passe: admin1234

### 3. Lancer le serveur stable

    .\start_server_stable.bat

Ce script lance le serveur sans mode --reload, vérifie les dépendances, initialise la base de test et refuse de démarrer si le port 8001 est déjà utilisé.

### 4. Accès depuis un autre PC du réseau

Depuis un autre poste du même réseau local :

    http://ADRESSE_IPV4_DU_PC_SERVEUR:8001

Exemple :

    http://192.168.86.26:8001

### 5. Arrêter le serveur

Dans la fenêtre du serveur :

    CTRL + C

### 6. Si le port 8001 est déjà utilisé

Vérifier le processus :

    netstat -ano | findstr :8001

Arrêter le processus concerné :

    taskkill /PID PID_ICI /T /F

Sur un PC de test uniquement, il est aussi possible d'arrêter tous les processus Python :

    taskkill /IM python.exe /T /F

### 7. Cycle de mise à jour

Développement sur le PC principal :

    git add .
    git commit -m "Message"
    git push

Mise à jour sur le PC serveur :

    cd C:\Users\afric\dealer-quote-manager
    git pull
    .\start_server_stable.bat

Le PC serveur sert uniquement à faire tourner l'application et tester les accès. Le développement continue sur le PC principal.

