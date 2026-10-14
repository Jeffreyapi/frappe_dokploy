# Build par couches et configuration Quai

Les images de build restent dans le registry. Elles conservent toutes les dépendances
nécessaires aux builds suivants. L'image runtime est assemblée par un Dockerfile généré
par Quai, sans `RUN`, à partir de `Dockerfile.runtime` et de la dernière couche.
Le Dockerfile historique reste utilisable ; son CMD passe désormais par le wrapper
Gunicorn pour appliquer les variables d'exploitation.
Le service backend hérite du CMD de l'image : les anciennes images restent donc
compatibles avec les retours arrière. Elles prennent leurs anciens paramètres
Gunicorn fixes ; les nouvelles variables deviennent effectives après un build neuf.

## Contrat

| Build | Dockerfile | Arguments |
| --- | --- | --- |
| Frappe seul | `Dockerfile.layer` | `LAYER_APP=frappe`, `PARENT_IMAGE=<BUILD_IMAGE>@digest`, `FRAPPE_VERSION`, `FRAPPE_REVISION`, `SOURCE_REVISION` |
| App suivante | `Dockerfile.layer` | `LAYER_APP=<app>`, `PARENT_IMAGE=<couche précédente>@digest`, `APPS_JSON_BASE64=<singleton>`, `SOURCE_REVISION` |
| Base runtime | `Dockerfile.runtime` | `BASE_IMAGE=<digest>`, `S5CMD_VERSION` |
| Assemblage | généré par Quai | dernière couche et runtime-base, tous deux épinglés |

`APPS_JSON_BASE64` encode exactement une entrée distante `{name,url,revision}`. Les
révisions sont des SHA complets, les URL HTTPS n'incluent aucun identifiant. Le secret
BuildKit `git_token` reste optionnel et éphémère. Aucun cache mount n'est nécessaire.
La cible finale de `Dockerfile.layer` se nomme `layer` ; aucun `--target` n'est requis.

Frappe est cloné au SHA avant `bench init`, qui installe ses dépendances une seule fois.
`app_sources.py --only` refuse une app déjà présente dans le parent, conserve `apps.txt`
et n'installe que les dépendances Python et Yarn de l'app sélectionnée.

Sources à copier depuis la dernière couche :

- `/home/frappe/frappe-bench/env/`, puis `apps/<app>/` séparément, en excluant chaque
  `node_modules` (y compris les liens `public/node_modules`) et les dossiers `.git` ;
- `/opt/runtime-slice/<app>/node_modules/` vers `apps/<app>/node_modules/` ;
- `/home/frappe/image-assets/<app>/` vers `/opt/image-assets/<app>/` ;
- `/opt/runtime-slice/<app>/assets-node_modules/` vers `/opt/image-assets/<app>/node_modules/` ;
- `/opt/runtime-slice/<app>/locale/` vers `/opt/image-assets/locale/`, une copie par app ;
- `/home/frappe/image-assets/assets.json` et `assets-rtl.json`, `sites/apps.txt`,
  `/home/frappe/apps-manifest.json` vers `/opt/apps-manifest.json`, et `source.json` vers
  `/opt/source.json`.

Les trois répertoires de slice existent même lorsqu'ils sont vides. `sites/assets` reste
le volume rempli par `site.sh`. L'image ne garde qu'une copie des assets, dans `/opt/image-assets`.
La syntaxe Dockerfile d'assemblage doit supporter `COPY --exclude` (1.19 stable).

## Dépendances Node runtime

Le script `prune_node_modules.py` matérialise la fermeture des dépendances serveur et
des bibliothèques d'assets à la demande. Il résout les dépendances Yarn hoistées, les
versions imbriquées, les cycles, les dépendances optionnelles présentes et les peers
installés. Une racine ou dépendance obligatoire manquante arrête le build. Les
`node_modules` complets des couches de build restent intacts.

Une app peut ajouter `runtime-node-modules.txt` à sa racine :

```text
server: socket.io
assets: photoswipe
# Sans préfixe : incluse dans les deux tranches.
shared-library
```

Les racines Frappe par défaut sont `socket.io`, `@redis/client`, `cookie` côté serveur,
et `photoswipe`, `qz-tray`, `js-sha256`, `html5-qrcode`, `frappe-gantt`, `ace-builds`
côté assets. Les autres apps doivent déclarer leurs besoins. Une recherche des chemins
`/assets/<app>/node_modules/` est nécessaire avant la bascule d'un bench tiers.

## Configuration

`FRAPPE_COMMON_CONFIG`, `FRAPPE_SITE_CONFIG` transportent des objets JSON compacts.
Vide équivaut à `{}`. `apply_config.py` valide la même liste blanche que Quai, rejette
les secrets et clés inconnues, et refuse `developer_mode` en `prod`/`production`.
Le wildcard CORS nécessite `FRAPPE_ALLOW_CORS_WILDCARD=1`, issu de la confirmation
explicite conservée par Quai. Les modifications sont protégées par `flock` puis
commises par `os.replace` et `fsync`. `_quai_managed_keys`, stockée avec les valeurs
dans la même transaction de fichier, permet de retirer seulement les clés auparavant
gérées par Quai. Les mots de passe et toutes les clés non gérées restent intacts.
Le journal `config.applied` contient des noms de clés, jamais leurs valeurs.

`CONFIG_REVISION` est transmis aux huit services Frappe pour leur recréation.
`GUNICORN_WORKERS=2`, `GUNICORN_THREADS=4`, `GUNICORN_TIMEOUT=120`,
`GUNICORN_MAX_REQUESTS=0` pilotent le wrapper de démarrage. Les réplicas des files
sont `QUEUE_DEFAULT_REPLICAS`, `QUEUE_SHORT_REPLICAS`, `QUEUE_LONG_REPLICAS` (défaut 1).
Les réglages Chromium et frontend figurent dans `.env.example`.

## Validation et spikes

```sh
python -m pytest -q scripts/test_app_sources.py scripts/test_layer_build.py scripts/test_runtime_config.py
python scripts/test_secret_fetch.py
python scripts/test_fd.py  # nécessite textual
bash -n deploy/scripts/site.sh deploy/scripts/gunicorn.sh
docker build --check -f Dockerfile.layer .
docker build --check -f Dockerfile.runtime .
```

Avant toute bascule, exécuter les quatre spikes sur un bench de test. Les mesures
de durée, taille registry et transferts ne peuvent pas être déduites des tests unitaires.

1. **S1** : construire Frappe, puis une app. Comparer les JSON de bundles avant et
   après : toutes les clés de Frappe doivent subsister, avec leurs fichiers sur disque.
   Le code Frappe `version-16` lit et fusionne les assets dans
   `esbuild/esbuild.js::write_assets_json` (`Object.assign({}, assets_json, out)`),
   et `frappe/commands/utils.py::build` compile les traductions seulement des apps
   sélectionnées. Le script de finalisation conserve également les entrées du parent
   et copie les catalogues `.mo` par app. Cette lecture du code et les tests simulés
   ne remplacent pas un build réel multi-app.
2. **S2** : comparer les répertoires `node_modules` du build et du runtime ; contrôler
   qu'il n'existe qu'une copie des assets. Dans l'image runtime, charger
   `socket.io`, `@redis/client`, `cookie` avec Node depuis `apps/frappe`, puis vérifier
   les six bibliothèques d'assets. Sur un site de test, contrôler websocket healthy,
   Gantt, éditeur, scanner et impression QZ. Vérifier les références des apps tierces.
3. **S3** : registry de test avec authentification, push interne puis pull du `FROM`
   par le nom public. Consigner les durées réelles. La bascule production reste celle
   décrite dans le cahier Quai : garde-fou déployé avant arrêt de l'ancien registry.
4. **S4** : mesurer une construction à froid, une modification de la dernière app,
   une modification intermédiaire, et un rejeu sans modification. Garder la durée,
   `build.pushed.size_bytes`, les digests et les octets transférés au serveur test.
   L'objectif de réduction de 40 % est un critère à mesurer, pas un résultat acquis.

Dans l'environnement cloud géré, fournir le CA public sans l'intégrer à l'image :

```sh
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -f Dockerfile.layer -t quai-spike-frappe:local .
```

Les images de test sont locales et n'impliquent aucun changement de production.

### Observations locales du 2026-10-14

Sur le daemon Docker du workspace (stockage VFS), une couche Frappe réelle a été
construite avec les digests par défaut et le SHA `988e54f3c4c291e2077a83809663f123731abe76`.
`bench init` a installé Frappe une seule fois à ce SHA. Le build ciblé a compilé ses
bundles et ses traductions, puis matérialisé les slices. Depuis la slice seule, Node
a chargé `socket.io`, `@redis/client` et `cookie`. Les six bibliothèques d'assets et
le catalogue français étaient présents. La base runtime a également été construite.

| Mesure réelle | Octets |
| --- | ---: |
| `apps/frappe/node_modules` du build | 276 762 208 |
| Slice Node serveur Frappe | 8 450 602 |
| Slice bibliothèques d'assets Frappe | 56 611 834 |
| Assets Frappe matérialisés sans Node | 60 918 386 |
| Image outils Frappe, taille Docker non compressée | 3 462 301 199 |
| Image runtime-base, taille Docker non compressée | 1 404 412 508 |

Ces tailles locales ne sont pas les métriques `build.pushed.size_bytes` d'un registry.
Elles ne démontrent ni le gain total de 40 %, ni les temps de transfert, ni le
fonctionnement des écrans sur un site déployé. Le test multi-app et les vérifications
sur site de S1–S4 restent à distinguer de ces premiers résultats locaux.
Une tentative d'assemblage réel, générée par Quai en syntaxe 1.19 avec `COPY --link`,
a été interrompue volontairement avant épuisement du disque de 32 Go du workspace
(VFS). Aucun résultat de taille runtime finale ou de santé du websocket sur site ne
peut donc être annoncé à partir de cette tentative. Les images outils et runtime-base
locales sont conservées ; aucun registry ni site de production n'a été modifié.
