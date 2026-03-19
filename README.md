# frappe_dokploy

Repo générique de **build et déploiement** pour toute application Frappe.

Fusionne `pharmtek_docker` + `pharmtek_dokploy` en un seul repo réutilisable :
- Construction de l'image Docker (`apps.json` + `Dockerfile`)
- Déploiement via Docker Compose (dev et prod)
- Gestion du cycle de vie du site Frappe (create / restore / update / backup)

> L'image buildée est **identique** en dev et en prod. Seule la source diffère : build local vs GHCR.

---

## Structure

```
frappe_dokploy/
├── apps.json                          # apps Frappe à embarquer dans l'image
├── Dockerfile                         # build Frappe + apps + s5cmd (autonome)
├── docker-compose.yml                 # stack dev et prod
├── docker-compose.build.yml           # override : build local à la volée
├── .env.example                       # template de configuration (sans secrets)
├── resources/
│   ├── nginx-entrypoint.sh            # entrypoint nginx custom
│   └── nginx-template.conf            # config nginx avec headers sécurité
├── deploy/
│   ├── scripts/
│   │   ├── init.sh                    # orchestrateur du site-manager
│   │   └── site.sh                    # create / restore / update / backup / configure
│   └── config/
│       └── skip_fixtures.list         # fixtures à neutraliser au migrate (vide = aucune)
└── .github/workflows/
    ├── publish.yml                    # build + push GHCR
    └── notify-frappe-dokploy.yml      # template à copier dans les repos d'apps
```

---

## Démarrage rapide

### 1. Configurer

```bash
cp .env.example .env
# Renseigner au minimum : SITE_NAME, ADMIN_PASSWORD, DB_ROOT_PASSWORD, IMAGE_NAME
```

### 2. Lancer (image pré-construite depuis GHCR)

```bash
docker compose up -d
```

### 3. Lancer en mode build local (sans passer par GHCR)

```bash
# Préparer apps.json avec le token GitHub
export GH_PAT=ghp_xxx
envsubst < apps.json > apps.build.json
export APPS_JSON_BASE64=$(base64 -w 0 apps.build.json)

docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
```

---

## Adapter pour un autre projet

### 1. Modifier `apps.json`

```json
[
  { "url": "https://${GH_PAT}:x-oauth-basic@github.com/OWNER/mon_app.git", "branch": "main" },
  { "url": "https://github.com/frappe/erpnext.git", "branch": "version-15" }
]
```

### 2. Adapter le `.env`

```bash
IMAGE_NAME=ghcr.io/jeffreyapi/mon_app
SITE_NAME=monapp.example.com
APPS=mon_app
```

### 3. Personnaliser les fixtures à neutraliser (optionnel)

Éditer `deploy/config/skip_fixtures.list` :
```
# Un pattern par ligne (nom de fichier sans .json, insensible à la casse)
MonDoctype
AutreFixture
```

---

## Déclencher un build depuis un repo d'app

Copier `.github/workflows/notify-frappe-dokploy.yml` dans le repo de l'application.  
Adapter le champ `app` et le nom du repo cible.

**Prérequis** : créer un secret `FRAPPE_DOKPLOY_PAT` dans le repo d'app  
(token GitHub avec scope `repo` sur `Jeffreyapi/frappe_dokploy`).

```
Repo d'app (push/tag)
  └─→ notify-frappe-dokploy.yml
        └─→ repository_dispatch → frappe_dokploy
              └─→ publish.yml → build + push ghcr.io/.../frappe:app-branch-sha
```

---

## Variables d'environnement

| Variable | Description | Défaut |
|---|---|---|
| `IMAGE_NAME` | Image Docker | `ghcr.io/jeffreyapi/frappe` |
| `APP_VERSION` | Tag de l'image | `latest` |
| `SITE_NAME` | Nom du site Frappe | (requis) |
| `ADMIN_PASSWORD` | Mot de passe admin | (requis) |
| `DB_ROOT_PASSWORD` | Mot de passe root MariaDB | (requis) |
| `ENVIRONMENT` | `dev` ou `prod` | `dev` |
| `ENABLE_DB` | `1` = DB incluse, `0` = DB externe | `1` |
| `APPS` | Apps à installer sur le site | (vide) |
| `RESTORE` | `1` = restaurer depuis S3 | `0` |
| `S3_BACKUP_BUCKET` | Bucket S3 | (vide) |
| `S3_ENDPOINT_URL` | Endpoint S3 compatible | (vide) |
| `NEUTRALIZE_MODE` | `rm` ou `empty` | `rm` |
| `FRAPPE_DEBUG` | `1` = mode verbose dans les scripts | `0` |

Voir `.env.example` pour la liste complète.

---

## Secrets GitHub requis

| Secret | Scope | Description |
|---|---|---|
| `GH_PAT` | `frappe_dokploy` | Token pour cloner les apps privées + push GHCR |
| `FRAPPE_DOKPLOY_PAT` | repos d'apps | Token pour déclencher le build (scope `repo` sur `frappe_dokploy`) |

---

## Actions disponibles du site-manager

| Action | Déclenchement | Description |
|---|---|---|
| `auto` (défaut) | toujours | configure → create ou restore ou update selon l'état |
| `create` | `ACTION=create` | Crée le site, installe les apps, migrate |
| `restore` | `RESTORE=1` ou `ACTION=restore` | Restaure depuis S3, migrate |
| `update` | `ACTION=update` | Maintenance ON, migrate, build, OFF |
| `backup` | `ACTION=backup` | Backup local + upload S3 |
| `configure` | `ACTION=configure` | Met à jour common_site_config.json uniquement |
