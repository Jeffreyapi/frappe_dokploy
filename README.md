# frappe_dokploy

Generic Frappe source/build/lifecycle toolkit, used as a Git submodule.

## Supported build contract

The application repository supplies a standard Frappe Python package and an
ordered `apps.json`. Remote entries require `name`, `url`, and a full commit
`revision`. The last entry names the local package with `path: "."`.
Credential-bearing URLs and floating branches are rejected.

```bash
python frappe_deploy/scripts/prepare_build.py --output .build/source --revision "$(git rev-parse HEAD)"
docker buildx build --load --build-context app_source=.build/source -f frappe_deploy/Dockerfile -t frappe-local:dev frappe_deploy
```

Use a fresh output directory for each build. The context allowlists package
files and metadata; it does not copy the repository's Git configuration or
root dotenv files. The image initializes Frappe in a build stage, verifies
its revision, installs named app sources and builds assets. The runtime gets
the completed bench, manifest, source identity, assets and lifecycle scripts.

The application owns its CI gate and release promotion. The platform's
`.github/workflows/ci.yml` builds/tests once and publishes that exact image.
It does not call a floating toolkit workflow.

## Development

The devcontainer image supplies the Frappe build tools. MariaDB 11.8 and Redis 7
must run as separate Compose services named `db`, `redis-cache`, `redis-queue`.
Run `bash frappe_deploy/scripts/devcontainer-setup.sh` from the application root.
The script requires an existing app package, validates all steps, links the
local app, and preserves a conflicting copy in `archived/apps`.

## Runtime

Set `DEPLOYMENT_ID`, `SITE_NAME`, `ADMIN_PASSWORD`, `DB_ROOT_PASSWORD`,
`IMAGE_NAME` and `APP_VERSION`. Use a distinct deployment ID per
tenant/environment. Configure the trusted proxy CIDR explicitly.

```bash
docker compose --env-file .env -f frappe_deploy/docker-compose.yml up -d
docker compose --env-file .env -f frappe_deploy/docker-compose.yml run --rm site-manager backup
docker compose --env-file .env -f frappe_deploy/docker-compose.yml run --rm -e BACKUP_ID=<id> site-manager restore
```

The hosting environment owns the external `dokploy-network`. Scripts are
baked into the image. Assets are built once, not during migrations.
Errors preserve maintenance. A site lock serializes lifecycle operations.

Backups contain a single complete set with checksums and tenant/environment
identity. S3 upload uses `S3_BACKUP_ENABLED`, `S3_BACKUP_BUCKET`, optional
`S3_ENDPOINT_URL`/`S3_BACKUP_REGION` and optional static credentials.
The manifest is uploaded last. Restoration refuses incomplete, corrupt or
foreign sets and restores the encryption key without replacing target DB
credentials. Backup scheduling, retention and cross-environment sanitization
remain hosting responsibilities.

Legacy copy/replace scaffolding and the old `APPS_JSON_BASE64` build interface
are no longer supported. Existing consumers must migrate their manifests and
CI before adopting this toolkit revision.
