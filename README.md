# frappe_dokploy

Infrastructure générique de **build** et **déploiement** pour applications Frappe v16.

Conçu pour être utilisé comme **git submodule** (`frappe_deploy/`) dans chaque repo d'application.
Le TUI `fd.py` initialise un nouveau repo en générant les 4 fichiers projet-spécifiques — tout le
reste (Dockerfile, docker-compose, scripts) vit dans ce submodule et n'est jamais copié.

---

## Démarrage rapide

```bash
# 1. Créer le repo app (ou cloner un repo GitHub vide)
mkdir mon_app && cd mon_app
git init

# 2. Ajouter le submodule
git submodule add https://github.com/Jeffreyapi/frappe_dokploy.git frappe_deploy

# 3. Installer Textual (dépendance du TUI)
uv venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
uv pip install textual

# 4. Lancer le TUI depuis la racine du repo app
python frappe_deploy/scripts/fd.py
```

Le TUI génère les 4 fichiers, puis :

```bash
# 5. Copier .env.example → .env et ajuster les valeurs
cp .env.example .env

# 6. Committer et pousser
git add -A && git commit -m "init: mon_app" && git push

# 7. Ouvrir dans VS Code / GitHub Codespaces
# F1 → "Dev Containers: Reopen in Container"
```

---

## Architecture

### Ce que fournit le submodule (jamais copié)

```
frappe_deploy/                        ← frappe_dokploy cloné en submodule
├── Dockerfile                        # image production (base ghcr.io/frappe/base)
├── docker-compose.yml                # stack complète avec labels Traefik (${APP_NAME}, ${SITE_NAME})
├── docker-compose.build.yml          # override build local
├── .devcontainer/
│   └── Dockerfile                    # image dev (Ubuntu 24.04, Python 3.14, MariaDB, Redis)
├── .github/workflows/
│   └── build-image.yml               # workflow réutilisable (workflow_call)
├── scripts/
│   ├── fd.py                         # TUI d'initialisation
│   └── devcontainer-setup.sh         # setup dev (appelé par postCreateCommand)
├── deploy/
│   ├── scripts/
│   │   ├── init.sh                   # orchestrateur site-manager
│   │   └── site.sh                   # cycle de vie du site Frappe
│   └── config/
│       └── skip_fixtures.list        # fixtures à neutraliser
└── resources/
    ├── nginx-entrypoint.sh
    └── nginx-template.conf
```

### Ce que génère le TUI (4 fichiers projet-spécifiques)

```
mon_app/
├── .env.example                      # variables dev + prod (commité, sans secrets)
├── apps.json                         # apps à embarquer dans l'image Docker
├── .devcontainer/
│   └── devcontainer.json             # pointe vers frappe_deploy pour le Dockerfile et le setup
└── .github/workflows/
    └── publish.yml                   # appelle le workflow réutilisable build-image.yml
```

### Structure complète après le premier Codespace

```
mon_app/
├── mon_app/                          ← module Python Frappe (scaffoldé par bench new-app)
├── pyproject.toml
├── apps.json
├── .env.example
├── .env                              ← secrets locaux (gitignored)
├── .devcontainer/
│   └── devcontainer.json
├── .github/workflows/
│   └── publish.yml
└── frappe_deploy/                    ← submodule (frappe_dokploy)
```

---

## Le TUI fd.py

Lance depuis la racine du repo app :

```bash
python frappe_deploy/scripts/fd.py
```

### Champs et valeurs par défaut

| Section | Champ | Défaut |
|---------|-------|--------|
| **APP** | Nom de l'app | nom du dossier courant |
| | GitHub owner | `Jeffreyapi` |
| | Python version | `python3.14` |
| | Frappe branch | `version-16` |
| **MÉTADONNÉES** | Title | nom du dossier |
| | Description | nom du dossier |
| | Publisher | `EasyTalents` |
| | Email | `admin@easytalents.fr` |
| | Licence | `apache-2.0` |
| **DEV** | Site name | `development.localhost` |
| | Admin password | `admin` |
| | DB root password | `123` |

- **▶ Initialiser** : génère les 4 fichiers dans le répertoire courant
- **Étapes suivantes** : affiche le récapitulatif des actions post-init
- **Échap** : quitter

---

## Environnement de développement (Codespace / Dev Container)

### Comment ça fonctionne

Le `devcontainer.json` généré par le TUI définit deux hooks :

```json
"initializeCommand": "git submodule update --init --recursive",
"postCreateCommand": "bash frappe_deploy/scripts/devcontainer-setup.sh"
```

- **`initializeCommand`** — s'exécute avant la construction du conteneur, avec les credentials git du Codespace → initialise le submodule `frappe_deploy`
- **`postCreateCommand`** — s'exécute dans le conteneur après sa création → lance `devcontainer-setup.sh`

### Ce que fait `devcontainer-setup.sh` (idempotent)

```
1.  MariaDB 10.6 + Redis (services système dans le conteneur)
2.  Installation de uv + frappe-bench CLI
3.  bench init ~/frappe-bench --python python3.14 --frappe-branch version-16
4.  Config Redis + MariaDB dans common_site_config.json
5.  Apps publiques depuis apps.json (skip si ${GH_PAT} détecté dans l'URL)
6.  bench new-app (non-interactif via printf) — si pyproject.toml absent
7.  Copie de l'app vers /workspaces/APP (cp -rn, sans écraser l'existant)
8.  Symlink ~/frappe-bench/apps/APP → /workspaces/APP
9.  pip install -e (mode éditable — hot-reload Python)
10. bench new-site development.localhost
11. bench install-app
```

Le script lit `.env` (ou `.env.example` si `.env` absent) depuis la racine du projet.

### Ouvrir le devcontainer

**VS Code local :**
```
F1 → "Dev Containers: Reopen in Container"
```

**GitHub Codespaces :**
```
Code → Codespaces → Create codespace on main
```

### Utilisation après ouverture

```bash
# Démarrer le serveur de développement
cd ~/frappe-bench && bench start

# Accéder au site
# http://development.localhost:8000
# Login : Administrator / <ADMIN_PASSWORD>
```

### Première création — committer l'app scaffoldée

Après le premier Codespace, `devcontainer-setup.sh` a scaffoldé l'app dans `/workspaces/mon_app/`.
Il faut la committer :

```bash
git add mon_app/ pyproject.toml
git commit -m "init: scaffold mon_app"
git push
```

### Tableau comparatif

| | Devcontainer | `docker compose up` |
|--|:--:|:--:|
| But | Coder | Déployer |
| MariaDB/Redis | Dans le conteneur | Conteneurs séparés |
| App Frappe | Symlink éditable | Image baked |
| Hot-reload | ✓ | ✗ |
| Debug Python | ✓ | ✗ |
| Traefik | ✗ | ✓ |

---

## CI/CD — Build d'image Docker

### Workflow réutilisable (`build-image.yml`)

`frappe_deploy/.github/workflows/build-image.yml` est un `workflow_call` utilisable par tout
repo sous l'organisation `Jeffreyapi`.

Le TUI génère automatiquement `.github/workflows/publish.yml` dans le repo app :

```yaml
jobs:
  build:
    uses: Jeffreyapi/frappe_dokploy/.github/workflows/build-image.yml@main
    with:
      image-name: ghcr.io/Jeffreyapi/mon_app
      frappe-version: version-16
    secrets: inherit
```

### Déclencheurs

- Push sur `main` → tag `main-<sha7>` + `latest`
- Push de tag `v*` → tag correspondant + `latest`
- `workflow_dispatch` → tag saisi manuellement

### Secret requis

| Secret | Scopes nécessaires |
|--------|--------------------|
| `GH_PAT` | `repo` + `write:packages` |

À configurer dans **Settings → Secrets → Actions** du repo app.

### Image produite

```
ghcr.io/Jeffreyapi/mon_app:main-abc1234
ghcr.io/Jeffreyapi/mon_app:latest
```

---

## Déploiement en production

La stack de déploiement utilise directement `frappe_deploy/docker-compose.yml` via la commande
`docker compose` depuis la racine du repo app.

### `apps.json` — apps embarquées dans l'image

Placé à la **racine du repo app** (généré par le TUI, à adapter) :

**App privée seule :**
```json
[
  {
    "url": "https://${GH_PAT}:x-oauth-basic@github.com/Jeffreyapi/mon_app.git",
    "branch": "main"
  }
]
```

**Avec ERPNext (ERPNext en premier) :**
```json
[
  { "url": "https://github.com/frappe/erpnext.git", "branch": "version-16" },
  {
    "url": "https://${GH_PAT}:x-oauth-basic@github.com/Jeffreyapi/mon_app.git",
    "branch": "main"
  }
]
```

> `${GH_PAT}` est substitué par `envsubst` lors du build CI — ne jamais écrire le token directement.

### Configurer l'environnement

```bash
cp .env.example .env
# Renseigner au minimum :
#   SITE_NAME, ADMIN_PASSWORD, DB_ROOT_PASSWORD, IMAGE_NAME, APP_NAME, APPS
```

### Démarrer la stack

```bash
# Créer le réseau Traefik/Dokploy (une seule fois par machine)
docker network create dokploy-network

# Démarrer avec l'image pré-construite depuis GHCR
docker compose -f frappe_deploy/docker-compose.yml up -d

# Suivre le site-manager
docker compose -f frappe_deploy/docker-compose.yml logs -f site-manager
```

### Build local (sans CI)

```bash
export GH_PAT=ghp_xxxxxxxxxxxx
envsubst < apps.json > /tmp/apps.build.json
export APPS_JSON_BASE64=$(base64 -w 0 /tmp/apps.build.json)

docker compose \
  -f frappe_deploy/docker-compose.yml \
  -f frappe_deploy/docker-compose.build.yml \
  up --build -d
```

---

## Référence des variables d'environnement

### Image Docker

| Variable | Description | Défaut |
|----------|-------------|--------|
| `IMAGE_NAME` | Image à utiliser | `ghcr.io/jeffreyapi/frappe` |
| `APP_VERSION` | Tag de l'image | `latest` |
| `PULL_POLICY` | `always` \| `never` \| `if_not_present` | `always` |

### App / Traefik

| Variable | Req. | Description |
|----------|:----:|-------------|
| `APP_NAME` | ✓ | Nom de l'app (utilisé dans les labels Traefik) |
| `SITE_NAME` | ✓ | Nom de domaine du site Frappe + règle Traefik |

### Frappe / Dev

| Variable | Description | Défaut |
|----------|-------------|--------|
| `PYTHON_VERSION` | Version Python pour bench init | `python3.14` |
| `FRAPPE_BRANCH` | Branche Frappe | `version-16` |
| `ADMIN_PASSWORD` | Mot de passe administrateur | — |
| `DB_ROOT_PASSWORD` | Mot de passe root MariaDB | — |

### Comportement du site-manager

| Variable | Description | Défaut |
|----------|-------------|--------|
| `ENVIRONMENT` | `dev` ou `prod` | `dev` |
| `RESTORE` | `1` = restaurer depuis S3 au démarrage | `0` |
| `APPS` | Apps à installer sur le site (virgules) | vide |
| `UPDATE_APPS` | Apps ciblées pour le build/update | vide |
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

## Cycle de vie du site (site-manager)

```
démarrage
  └─→ configure    (toujours : met à jour common_site_config.json)
        ├─→ RESTORE=1  → restore   (télécharge depuis S3 et restaure)
        ├─→ site existe → update   (migrate + build assets)
        └─→ site absent → create   (nouveau site + installation des apps)
```

Actions manuelles :

```bash
docker compose -f frappe_deploy/docker-compose.yml run --rm site-manager backup
docker compose -f frappe_deploy/docker-compose.yml run --rm site-manager update
docker compose -f frappe_deploy/docker-compose.yml run --rm -e RESTORE=1 site-manager restore
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
