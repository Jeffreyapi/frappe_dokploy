# frappe_dokploy

Generic Frappe source/build/lifecycle toolkit, used as a Git submodule.

## Supported build contract

Two ways to supply `apps.json` and, when there is one, the local package —
whichever lands in `/opt/app-source/` first wins.

### Named build context (an application repository with CI)

The application repository supplies a standard Frappe Python package and an
ordered `apps.json`. Remote entries require `name`, `url`, and a full commit
`revision`. At most one entry may be local, naming the package with
`path: "."`; when present, it must be the last entry. Credential-bearing
URLs and floating branches are rejected.

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

### Build arg (a platform that can only pass build args)

When the build is triggered directly by a platform with no concept of named
build contexts (e.g. Dokploy's native GitHub build), leave `app_source`
unset — it defaults to an empty stage — and pass the manifest instead via
the `APPS_JSON_BASE64` build arg: the same `apps.json` array, base64-encoded.
This path is for all-remote manifests (every entry is `{name, url,
revision}`); there is no local package to bundle, since the platform is
building from `frappe_dokploy` itself rather than from an app's own
repository with a CI-prepared context.

```bash
docker buildx build --load \
  --build-arg APPS_JSON_BASE64="$(base64 -w0 apps.json)" \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  -f frappe_deploy/Dockerfile -t frappe-local:dev frappe_deploy
```

The manifest still goes through the same validation
(`scripts/app_sources.py::load_manifest`) inside the build; a malformed or
credentialed entry fails the build the same way in both paths.

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

Legacy copy/replace scaffolding is no longer supported. `APPS_JSON_BASE64` is
back as a narrower, build-arg-only alternative to the named `app_source`
context — see "Supported build contract" above — not a return of the old
copy/replace flow.
