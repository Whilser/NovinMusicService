<!-- autopilot:start -->
# Novin Music Service

Личный FastAPI-сервис для каталога музыки на SMB-шаре NAS и управления MPD на сервере `novin`; один экземпляр в доверенной домашней сети, без авторизации.

## Команды

- Требуется Python 3.12+; Python-зависимости: `python3 -m pip install -r requirements-dev.txt`.
- Node-зависимости и Chromium: `npm ci && npm run install:browser`.
- Локальный запуск: `python3 -m uvicorn app.main:app --reload`; UI и healthcheck доступны на `http://127.0.0.1:8000/` и `/api/health`.
- Все Python-тесты: `python3 -m unittest discover -s tests -v`.
- Browser smoke отдельно: `npm run test:web`.
- Frontend не требует сборки: это статические HTML/CSS/ES-модули.
- Docker CLI в текущей среде отсутствовал, поэтому здесь не проверены: `cp .env.example .env && docker compose up -d --build`.
- Docker-диагностика и backup описаны в `README.md`; не запускай `docker compose down -v`, если нужен каталог.

## Структура

```text
app/main.py                 FastAPI factory, error handlers, routers, static SPA
app/api/                    HTTP routes for catalog, scan/share and player
app/catalog/                SQLite schema, migrations, queries and local playlists
app/scanner/                read-only filesystem scan and Mutagen metadata extraction
app/share/                  mount.cifs lifecycle and sanitized share status
app/mpd/                    MPD TCP protocol, transport whitelist and temporary queue
app/web/                    index.html plus framework-free CSS/JavaScript SPA
scripts/                    container entrypoint and online SQLite backup
tests/                      unittest suites, API/integration tests and browser smoke
Dockerfile                  Python 3.12 runtime with CIFS tools
docker-compose*.yml         persistent data, CIFS capability and AppArmor opt-in
.autopilot/                 run history, interfaces and live dashboard
```

## Ключевые файлы

- `app/main.py`: `create_app(data_dir?, music_root?) -> FastAPI`, production `app`, `/api/*` registration and SPA fallback.
- `app/dependencies.py`: `get_catalog()` dependency seam; MPD dependency lives in `app/api/player.py`.
- `app/catalog/catalog.py`: sole owner of the SQLite connection, schema, reconciliation, preferences, settings and playlist CRUD.
- `app/api/scan.py`: one-at-a-time background scan job, cover endpoint and share orchestration.
- `app/scanner/scanner.py`: supported audio discovery, normalized track rows, embedded/folder cover selection and per-file failure accounting.
- `app/share/manager.py`: fixed mount point, allowlisted SMB options, temporary credentials file and sanitized subprocess boundary.
- `app/mpd/client.py`: MPD framing/auth/escaping, status parsing, URI-prefix validation and allowed transport commands.
- `app/web/assets/app.js`: hash-routed SPA state, `/api/*` calls, safe DOM rendering and player polling.
- `docker-compose.yml`: runtime security boundary, `novin_data`, `/music`, healthcheck and host MPD gateway.
- `scripts/backup.py`: non-overwriting SQLite Online Backup API snapshot with integrity check and atomic publication.

## Архитектура и поток данных

- Browser загружает статику из `app/web/`, хранит маршрут в URL hash и обращается только к `/api/*`.
- Catalog API вызывает `Catalog`; SQLite `catalog.sqlite3` хранит индекс, несекретные настройки, оценки, избранное и локальные плейлисты.
- Share API передаёт несекретные settings в `ShareManager`; credentials берутся только из environment, а SMB монтируется read-only в `/music`.
- Scan API запускает фоновый `Scanner`; полный snapshot атомарно передаётся в `Catalog.reconcile_tracks()`, а при ошибке старый каталог сохраняется.
- Cover endpoint разрешает непрозрачный ID в безопасный файл под music root, ограничивает 5 MiB и отдаёт ETag/304 или SVG placeholder.
- Player API строит `MpdClient` из Catalog settings и `MPD_PASSWORD`; треки попадают только в текущую MPD-очередь как URI относительно `music_directory`.
- API errors use `{ "error": { "code": string, "message": string, "details"?: object } }`; MPD connection errors become a stable offline state.

## Соглашения кода

- Python modules expose test seams through constructor injection (`runner`, `env`) and FastAPI dependency overrides; preserve these seams when adding integrations.
- `Catalog` owns its SQLite connection and transaction boundaries; a successful scan publishes only through `reconcile_tracks()`.
- Persist only keys from `ALLOWED_SETTINGS`; names containing password/secret/token/credential/API-key markers are rejected.
- Track JSON keeps fields `id,path,title,artist,album,album_artist,track_no,disc_no,year,genre,duration,cover_url,rating,favorite` stable.
- SMB remains read-only and option-allowlisted; never place username/password in argv, status JSON or logs.
- MPD commands remain allowlisted and operate on the current queue; saved-playlist commands are deliberately unsupported.
- Frontend uses DOM nodes and `textContent` for user data, ES modules without bundling, hash routes and responsive desktop/mobile layouts.
- Unknown non-API paths return `index.html`; unknown `/api/*` paths must remain JSON 404 responses.

## Окружение

- `NOVIN_DATA_DIR`: directory containing `catalog.sqlite3`; defaults to local `data`, container sets `/data`.
- `NOVIN_MUSIC_ROOT`: scanner/cover root; defaults to `/music` and is fixed to it in the container.
- `SMB_USERNAME`, `SMB_PASSWORD`: optional pair for authenticated SMB; leave both empty for guest access.
- `MPD_PASSWORD`: optional MPD authentication secret; never store it in Catalog settings.
- `NOVIN_BIND_ADDRESS`, `NOVIN_PORT`: host bind and published port consumed by Compose interpolation.
- `TMPDIR`: writable temporary directory; the container sets `/run/novin` on tmpfs.
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`: optional browser-test override for an existing Chromium binary.
- `.env.example` contains names with empty values; local `.env` is ignored and must never be committed.

## Тесты

- Tests use stdlib `unittest`; API coverage uses FastAPI/HTTPX and module seams, integration delivery tests cover Compose structure and SQLite backup.
- Run one module as `python3 -m unittest tests.catalog.test_catalog -v`; replace the dotted module with another path under `tests/`.
- `tests/web/test_web.py` shells out to the same browser contract as `npm run test:web`; the full Python suite therefore includes browser smoke.
- `tests/web/browser_smoke.mjs` starts a local fixture server and headless Chromium, then checks routes, CRUD, states, player, injection safety, responsive layouts and accessibility.
- Browser and MPD tests bind loopback sockets; restricted sandboxes must permit local listeners.
- Docker integration tests skip build/config/start/health checks when Docker CLI is unavailable.

## Подводные камни

- `python3 -m uvicorn` without `NOVIN_DATA_DIR` creates `data/catalog.sqlite3` inside the checkout.
- Production SMB mounting requires Linux CIFS support plus container `SYS_ADMIN`; the image intentionally runs as root but drops all other capabilities and never uses `privileged: true`.
- `docker-compose.apparmor-unconfined.yml` weakens isolation for the whole service; use it only after a confirmed AppArmor denial of `mount.cifs`.
- MPD must see the same file tree as `/music`; set only a relative `mpd_uri_prefix` when its `music_directory` contains the collection in a subfolder.
- No authentication exists; bind to localhost or a trusted LAN and never expose this service directly to the internet.
- `docker compose down -v` deletes the persistent `novin_data` catalog; use `scripts/backup.py` and copy backups outside the volume.
- FastAPI currently emits deprecation warnings for `app.on_event("shutdown")`; tests pass, but a framework upgrade should migrate this to lifespan handling.

## Как здесь работает Autopilot

Сборка ведётся навыком `/autopilot`. Требования, спецификация и таски — в `.autopilot/`.
Прогресс — `.autopilot/dashboard.html`. Правило: требование из `manifest.md`
может снять только пользователь.

Если работа продолжается — скажи «продолжи автопилот»: состояние поднимется
из `.autopilot/state.js`, переспрашивать ничего не нужно.
<!-- autopilot:end -->
