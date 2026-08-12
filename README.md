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
