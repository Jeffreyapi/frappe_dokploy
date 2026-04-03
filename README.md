# frappe_dokploy

Infrastructure générique de **build** et **déploiement** pour applications Frappe/ERPNext.

Conçu pour être utilisé comme **git submodule** dans chaque repo d'application Frappe.
Peut aussi fonctionner en mode standalone pour tester l'infrastructure seule.

---

## Démarrage rapide (nouveau repo)

```bash
git init
git submodule add https://github.com/Jeffreyapi/frappe_dokploy.git frappe_deploy

# dépendance TUI via uv (package manager unique)
# Option 1 (recommandé) : venv local
uv venv .venv
source .venv/bin/activate    # Windows : .venv\\Scripts\\activate
uv pip install textual

# Option 2 (global) : sans venv
# uv pip install --system textual

# lance le TUI depuis la racine du projet (où se trouve le dossier frappe_deploy)
python frappe_deploy/scripts/fd.py
# (alternatif) cd frappe_deploy && python -m scripts.fd
```

---

## Structure du repo

```
frappe_dokploy/
├── Dockerfile                   # build Frappe + apps + s5cmd (context = ce répertoire)
├── docker-compose.yml           # stack complète (incluse via include: dans le repo app)
├── docker-compose.build.yml     # override build local à la volée
├── apps.json                    # exemple pour mode standalone uniquement
├── .env.example                 # exemple pour mode standalone uniquement
├── resources/
│   ├── nginx-entrypoint.sh      # entrypoint nginx avec substitution de variables
│   └── nginx-template.conf      # config nginx (headers sécurité, gzip, websocket)
├── deploy/
│   ├── scripts/
│   │   ├── init.sh              # orchestrateur : configure → create|restore|update
│   │   └── site.sh              # cycle de vie complet du site Frappe
│   └── config/
│       └── skip_fixtures.list   # patterns de fixtures à neutraliser (vide = aucune)
└── templates/                   # fichiers à copier dans chaque repo app
    ├── docker-compose.app.yml   # wrapper include: + labels Traefik
    ├── .env.app.example         # variables spécifiques au projet
    ├── publish.app.yml          # workflow CI/CD GitHub Actions
    └── Makefile                 # commandes de développement
```

---

## Créer une nouvelle app Frappe (flux recommandé)

Ce flux part d'un repo vide, ajoute le submodule `frappe_dokploy`, ouvre le
devcontainer pour disposer d'un bench prêt, puis génère l'app avec `bench`.

> **Prérequis** : VS Code + extension Dev Containers (ou Codespaces), Docker
démarré, et permissions GitHub pour créer le repo applicatif.

---

### 1 — Préparer le repo et copier le submodule

```bash
mkdir mon_app && cd mon_app
# initialiser votre repo git (ou créez-le d'abord sur GitHub puis clonez-le)
git init

# ajouter l'infra en submodule
git submodule add https://github.com/Jeffreyapi/frappe_dokploy.git frappe_deploy

# copier les fichiers de base depuis le submodule
cp frappe_deploy/templates/docker-compose.app.yml  docker-compose.yml
cp frappe_deploy/templates/.env.app.example        .env.example
cp frappe_deploy/templates/Makefile                Makefile
mkdir -p .github/workflows
cp frappe_deploy/templates/publish.app.yml         .github/workflows/publish.yml

# devcontainer (pour avoir le bench prêt dans VS Code)
mkdir -p .devcontainer
cp frappe_deploy/templates/.devcontainer/Dockerfile                   .devcontainer/Dockerfile
cp frappe_deploy/templates/.devcontainer/devcontainer.json            .devcontainer/devcontainer.json
cp frappe_deploy/templates/.devcontainer/devcontainer-post-create.sh  .devcontainer/devcontainer-post-create.sh
chmod +x .devcontainer/devcontainer-post-create.sh

# remplacer MY_APP automatiquement (prend le nom du dossier courant)
chmod +x frappe_deploy/scripts/rename_app.sh
frappe_deploy/scripts/rename_app.sh
# Optionnel : APP_NAME=mon_app frappe_deploy/scripts/rename_app.sh
```

---

### 2 — Ouvrir le devcontainer pour obtenir le bench

Dans VS Code : `F1 → Dev Containers: Reopen in Container` (ou Codespaces).
Le script post-create fait : MariaDB + Redis, `bench init frappe-bench` et
création du site `development.localhost` prêt à recevoir l'app.

> Tip : un TUI léger est dispo (`python -m scripts.fd`) pour lancer l'init
> (copie + remplacements) et afficher les commandes bench.

---

### 3 — Générer l'app avec bench (à l'intérieur du devcontainer)

```bash
# dans le terminal VS Code
cd ~/frappe-bench
bench new-app mon_app

# ramener le code dans le repo (workspace) et symlink vers le bench
cp -a apps/mon_app/. /workspaces/mon_app/
rm -rf apps/mon_app
ln -s /workspaces/mon_app apps/mon_app

# installer l'app sur le site de dev
bench --site development.localhost install-app mon_app
bench start  # serveur de dev : http://development.localhost:8000
```

> Le `Makefile` reste valable pour les commandes Docker de déploiement.

---

### 4 — Versionner et pousser sur GitHub

```bash
cd /workspaces/mon_app
git add .
git commit -m "chore: scaffold initial"
git remote add origin https://github.com/Jeffreyapi/mon_app.git
git push -u origin main
```

---

### Récapitulatif du flux

```
submodule + templates        → infra prête
Reopen in Container          → bench initialisé
bench new-app + symlink      → app générée dans le repo
install-app + bench start    → test local immédiat
git push                     → repo prêt pour CI/CD
```

---

## Mode Submodule (usage principal)

### Structure du repo app après configuration

```
mon_app/
├── mon_app/                 ← code Python Frappe (le module de l'app)
│   ├── hooks.py
│   └── ...
├── setup.py
├── apps.json                ← apps à embarquer dans l'image (spécifique au projet)
├── .env.example             ← valeurs de config sans secrets (commité)
├── .env                     ← secrets locaux (gitignore)
├── docker-compose.yml       ← inclut frappe_deploy + labels Traefik du projet
├── Makefile                 ← raccourcis de commandes
└── frappe_deploy/           ← ce repo, en git submodule
    ├── Dockerfile
    ├── docker-compose.yml
    └── ...
```

---

### Étape 1 — Ajouter le submodule

```bash
cd mon_app
git submodule add https://github.com/Jeffreyapi/frappe_dokploy.git frappe_deploy
git commit -m "chore: add frappe_deploy submodule"
```

Cloner un repo qui possède déjà le submodule :

```bash
# Avec submodules d'emblée (recommandé)
git clone --recurse-submodules https://github.com/Jeffreyapi/mon_app.git

# Après un clone normal
git submodule update --init
```

---

### Étape 2 — Copier les templates

Toutes les commandes suivantes s'exécutent depuis la **racine du repo app**.

```bash
# ── Déploiement (obligatoire) ─────────────────────────────────────────────────
cp frappe_deploy/templates/docker-compose.app.yml  docker-compose.yml
cp frappe_deploy/templates/.env.app.example        .env.example
cp frappe_deploy/templates/Makefile                Makefile
mkdir -p .github/workflows
cp frappe_deploy/templates/publish.app.yml         .github/workflows/publish.yml

# ── Devcontainer (optionnel, pour développer l'app dans VS Code) ──────────────
mkdir -p .devcontainer
cp frappe_deploy/templates/.devcontainer/Dockerfile                   .devcontainer/Dockerfile
cp frappe_deploy/templates/.devcontainer/devcontainer.json            .devcontainer/devcontainer.json
cp frappe_deploy/templates/.devcontainer/devcontainer-post-create.sh  .devcontainer/devcontainer-post-create.sh
chmod +x .devcontainer/devcontainer-post-create.sh
```

Remplacer `MY_APP` par le nom réel de l'application dans tous les fichiers copiés :

```bash
# Remplacer MY_APP dans tous les fichiers copiés (Linux / WSL)
APP=pharmtek_crm   # ← adapter ici

sed -i "s/MY_APP/${APP}/g" \
  docker-compose.yml \
  .env.example \
  .github/workflows/publish.yml \
  .devcontainer/devcontainer.json \
  .devcontainer/devcontainer-post-create.sh
```

> Le `Makefile` ne contient pas de `MY_APP` — pas besoin de le modifier.

---

### Étape 3 — Créer `apps.json`

Ce fichier liste les apps Frappe à embarquer dans l'image Docker.
Il se place à la **racine du repo app** (pas dans `frappe_deploy/`).

**App sans ERPNext** (ex : pharmtek_crm) :
```json
[
  {
    "url": "https://${GH_PAT}:x-oauth-basic@github.com/Jeffreyapi/mon_app.git",
    "branch": "main"
  }
]
```

**App qui nécessite ERPNext** (ex : talents30, jurisconnect) — ERPNext **en premier** :
```json
[
  { "url": "https://github.com/frappe/erpnext.git", "branch": "version-15" },
  {
    "url": "https://${GH_PAT}:x-oauth-basic@github.com/Jeffreyapi/mon_app.git",
    "branch": "main"
  }
]
```

> `${GH_PAT}` est un placeholder substitué par `envsubst` avant le build.
> Ne jamais écrire le token directement dans ce fichier.

---

### Étape 4 — Configurer l'environnement

```bash
cp .env.example .env
# Renseigner au minimum : SITE_NAME, ADMIN_PASSWORD, DB_ROOT_PASSWORD, IMAGE_NAME

# Créer le réseau Traefik/Dokploy (une seule fois par machine)
docker network create dokploy-network
```

---

### Étape 5 — Démarrer la stack

**Mode standard** — image pré-construite depuis GHCR :
```bash
make up
# équivalent : docker compose up -d
```

**Mode build local** — reconstruit l'image depuis `apps.json` :
```bash
export GH_PAT=ghp_xxxxxxxxxxxx
make build
```

Suivre le démarrage automatique du site-manager :
```bash
make logs
# équivalent : docker compose logs -f site-manager
```

---

### Étape 6 — CI/CD

Le workflow `publish.yml` (copié depuis `templates/publish.app.yml`) se déclenche
automatiquement à chaque push sur `main`/`develop` ou tag `v*`.

**Secret GitHub requis** dans le repo app :

| Secret | Description |
|--------|-------------|
| `GH_PAT` | Token GitHub avec scopes `repo` + `write:packages` |

Image produite : `ghcr.io/jeffreyapi/MON_APP:main-abc1234` + `latest`.

---

## Devcontainer — environnement de développement

Le devcontainer permet de **coder** l'application Frappe dans VS Code ou GitHub
Codespaces avec un bench en mode développeur, du hot-reload et du debug Python.

> Ce n'est pas la stack Docker Compose de déploiement — c'est un environnement
> de développement séparé, tout-en-un (MariaDB + Redis + bench dans un seul conteneur).

### Versions alignées avec la prod

| Composant | Devcontainer | Stack de déploiement |
|-----------|:-----------:|:-------------------:|
| MariaDB | 10.6 | 10.6 ✓ |
| Node.js | 18 | 18 ✓ |
| Frappe | version-15 | version-15 ✓ |

### Ouvrir le devcontainer

**VS Code** (local) :
```
F1 → "Dev Containers: Reopen in Container"
```

**GitHub Codespaces** :
```
Code → Codespaces → Create codespace on main
```

### Ce que le post-create fait automatiquement

```
1. Démarre MariaDB 10.6 + Redis (services système dans le conteneur)
2. Installe uv + frappe-bench
3. bench init frappe-bench --frappe-branch version-15
4. Installe les apps publiques de apps.json (ex: ERPNext)
5. Installe l'app du repo en MODE ÉDITABLE :
     ln -s /workspaces/mon_app  frappe-bench/apps/mon_app
     pip install -e apps/mon_app
   → les modifications Python dans VS Code sont immédiatement actives
6. bench new-site development.localhost
7. bench install-app mon_app (+ ERPNext si présent)
8. Active le mode développeur
```

### Utilisation après ouverture

```bash
# Démarrer le serveur de développement (depuis le terminal VS Code)
cd ~/frappe-bench && bench start

# Accéder au site
# http://development.localhost:8000
# Login : Administrator / admin
```

### Debug Python avec VS Code

Ajouter `.vscode/launch.json` à la racine du repo app :

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Bench Web",
      "type": "debugpy",
      "request": "launch",
      "program": "${env:HOME}/frappe-bench/apps/frappe/frappe/utils/bench_helper.py",
      "args": ["frappe", "serve", "--port", "8000", "--noreload", "--nothreading"],
      "cwd": "${env:HOME}/frappe-bench/sites",
      "env": { "DEV_SERVER": "1" }
    }
  ]
}
```

Puis : `F5` → "Bench Web" pour démarrer le serveur avec breakpoints.

### Différence devcontainer vs stack de déploiement

| | Devcontainer | `docker compose up` |
|--|:--:|:--:|
| But | Coder | Déployer |
| MariaDB/Redis | Dans le conteneur | Conteneurs séparés |
| App Frappe | Symlink éditable | Image baked |
| Hot-reload | ✓ | ✗ |
| Debug Python | ✓ | ✗ |
| Traefik | ✗ | ✓ |

---

## Mode Standalone

Pour tester l'infrastructure sans code d'application custom.

```bash
git clone https://github.com/Jeffreyapi/frappe_dokploy.git
cd frappe_dokploy

cp .env.example .env
# Éditer .env : SITE_NAME, ADMIN_PASSWORD, DB_ROOT_PASSWORD

docker network create dokploy-network
docker compose up -d
docker compose logs -f site-manager
```

Build local en mode standalone :
```bash
export GH_PAT=ghp_xxxxxxxxxxxx
envsubst < apps.json > /tmp/apps.build.json
export APPS_JSON_BASE64=$(base64 -w 0 /tmp/apps.build.json)

docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
```

---

## Référence des variables d'environnement

Le `.env` est lu depuis la **racine du répertoire de travail** (là où `docker compose`
est lancé), que ce soit en mode submodule ou standalone.

### Image Docker

| Variable | Description | Défaut |
|----------|-------------|--------|
| `IMAGE_NAME` | Image à utiliser | `ghcr.io/jeffreyapi/frappe` |
| `APP_VERSION` | Tag de l'image | `latest` |
| `PULL_POLICY` | `always` \| `never` \| `if_not_present` | `always` |

### Site Frappe

| Variable | Req. | Description | Défaut |
|----------|:----:|-------------|--------|
| `SITE_NAME` | ✓ | Nom de domaine du site Frappe | — |
| `ADMIN_PASSWORD` | ✓ | Mot de passe administrateur | — |
| `FRAPPE_SITE_NAME_HEADER` | | Header de résolution du site | `$host` |

### Base de données

| Variable | Req. | Description | Défaut |
|----------|:----:|-------------|--------|
| `DB_ROOT_PASSWORD` | ✓ | Mot de passe root MariaDB | — |
| `DB_HOST` | | Hôte MariaDB | `db` |
| `DB_PORT` | | Port MariaDB | `3306` |
| `ENABLE_DB` | | `1` = MariaDB embarquée, `0` = DB externe | `1` |

### Comportement du site-manager

| Variable | Description | Défaut |
|----------|-------------|--------|
| `ENVIRONMENT` | `dev` ou `prod` | `dev` |
| `RESTORE` | `1` = restaurer depuis S3 au démarrage | `0` |
| `APPS` | Apps à installer sur le site (virgules) | vide |
| `UPDATE_APPS` | Apps ciblées pour le build/update (vide = toutes) | vide |
| `SITE_MANAGER_RUN` | `1` = actif, `0` = désactivé | `1` |
| `NEUTRALIZE_MODE` | `rm` = supprimer \| `empty` = vider les fixtures | `rm` |
| `SKIP_FIXTURES` | Patterns de fixtures à neutraliser (CSV) | vide |

### Backup S3

| Variable | Description |
|----------|-------------|
| `S3_BACKUP_BUCKET` | Nom du bucket |
| `S3_BACKUP_ACCESS_KEY` | Clé d'accès |
| `S3_BACKUP_SECRET_KEY` | Clé secrète |
| `S3_ENDPOINT_URL` | Endpoint S3-compatible (MinIO, etc.) |

### Frontend / Nginx

| Variable | Description | Défaut |
|----------|-------------|--------|
| `FRONTEND_PORT` | Port exposé localement | `8080` |
| `CLIENT_MAX_BODY_SIZE` | Taille max des uploads | `50m` |
| `PROXY_READ_TIMEOUT` | Timeout proxy nginx (secondes) | `120` |

---

## Cycle de vie du site

Logique automatique au démarrage (`init.sh`) :

```
démarrage
  └─→ configure    (toujours : met à jour common_site_config.json)
        ├─→ RESTORE=1  → restore   (télécharge depuis S3 et restaure)
        ├─→ site existe → update   (migrate + build assets)
        └─→ site absent → create   (nouveau site + installation des apps)
```

Actions manuelles :

```bash
# Via Makefile
make backup
make update
make configure

# Ou via docker compose
docker compose run --rm site-manager backup
docker compose run --rm site-manager restore
docker compose run --rm site-manager update
docker compose run --rm site-manager configure

# Mode debug (logs verbeux)
docker compose run --rm -e FRAPPE_DEBUG=1 site-manager update
```

---

## Neutralisation des fixtures

Évite d'écraser des données de production lors des migrations.

**Via le fichier** `frappe_deploy/deploy/config/skip_fixtures.list` :
```
# Un pattern par ligne (nom de fichier sans .json, insensible à la casse)
CustomDocType
AnotherFixture
```

**Via `.env`** (inline) :
```env
SKIP_FIXTURES=CustomDocType,AnotherFixture
NEUTRALIZE_MODE=rm    # rm = suppression | empty = remplacer par []
```

---

## Mettre à jour le submodule

Quand des corrections ou nouvelles fonctionnalités sont disponibles :

```bash
cd frappe_deploy && git pull origin main && cd ..
git add frappe_deploy
git commit -m "chore: bump frappe_deploy"
git push
```

---

## Ports et healthchecks

| Service | Port interne | Healthcheck |
|---------|:-----------:|-------------|
| `frontend` | 8080 | `wait-for-it 0.0.0.0:8080` |
| `backend` | 8000 | `wait-for-it 0.0.0.0:8000` |
| `websocket` | 9000 | `wait-for-it 0.0.0.0:9000` |
| `db` | 3306 | `mysqladmin ping` |
| `redis-*` | 6379 | `redis-cli ping` |
