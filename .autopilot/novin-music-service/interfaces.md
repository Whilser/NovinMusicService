# Интерфейсы проекта

## Правила проекта

- Python 3.12, FastAPI, стандартный `sqlite3`, Mutagen; frontend — HTML/CSS/ES-модули без Node-сборки.
- Установка для разработки: `python -m pip install -r requirements-dev.txt`.
- Тесты: `python -m unittest discover -s tests -v`.
- Запуск: `uvicorn app.main:app --reload`.
- Не сохранять и не логировать секреты; `.env` не коммитить. Недостающую зависимость не устанавливать самовольно: вернуть `BLOCKED`.
- SMB всегда read-only; сервис не изменяет файлы NAS.
- MPD используется только для текущей очереди и транспорта; сохранённые playlist-команды запрещены.
- Каждый исполнитель меняет только свою зону и возвращает блок CONTRACT с реализованными интерфейсами, файлами, тестами и ограничениями.

## Границы, решённые в спецификации

| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `catalog` | SQLite-схема, запросы библиотеки, предпочтения, плейлисты | `Catalog` с операциями поиска, scan reconciliation, preferences и playlist CRUD | SQL, транзакции, миграции |
| `scanner` | обход `/music`, чтение тегов и поиск обложек | `scan(root) -> ScanSnapshot` | Mutagen, ошибки отдельных файлов, нормализацию путей |
| `share` | состояние SMB mount | `ShareManager.apply(settings)`, `.status()` | mount/umount, credentials file, subprocess |
| `mpd` | протокол и отображение текущей очереди | `MpdClient.status()`, `.command()`, `.play_uris()` | TCP framing, auth, escaping и запрещённые команды |
| `api` | HTTP-контракты и фоновые scan jobs | FastAPI routes | преобразование ошибок и оркестрацию модулей |
| `web` | Apple Music-подобное SPA-состояние и представление | статические assets, обращения только к `/api/*` | DOM rendering, responsive layout, polling |

Главные тестовые швы: публичные `Catalog`, `Scanner`/`ShareManager` и `MpdClient`; HTTP проверяется через FastAPI test client, браузерная логика — через чистые функции состояния и smoke-проверку DOM.

## Контракты между тасками

- `app.main:create_app(data_dir?, music_root?) -> FastAPI`; production-экземпляр экспортируется как `app`.
- `app.main` раздаёт `app/web/` на `/` после регистрации `/api/*`; неизвестный не-API маршрут возвращает SPA `index.html`, assets отдаются как статические файлы.
- `app.dependencies:get_catalog() -> Catalog`; FastAPI dependency можно переопределить в тестах.
- Каждый feature router экспортирует `router`; `app.main` подключает catalog, scan и player routers под `/api`.
- Настройки хранятся как строковые ключи через `Catalog.get_settings()` / `Catalog.update_settings(mapping)`; секреты туда не передаются.
- Track JSON имеет стабильные поля: `id,path,title,artist,album,album_artist,track_no,disc_no,year,genre,duration,cover_url,rating,favorite`.
- Ошибка API: `{ "error": { "code": string, "message": string, "details"?: object } }`.

## Из таска 01 — основа и каталог

- `Catalog(db_path)`; `initialize()`; `close()` — единственная точка владения SQLite-соединением и миграциями.
- `list_tracks(search?, favorite?, limit?, offset?)`, `list_albums()`, `list_artists()` — чтение каталога.
- `reconcile_tracks(rows)` — атомарное добавление/обновление и удаление исчезнувших путей.
- `create_playlist(name)`, `update_playlist(id, name)`, `delete_playlist(id)`, `set_playlist_tracks(id, track_ids)`, `list_playlists()`, `get_playlist(id)` — локальные плейлисты.
- `set_preference(track_id, rating?, favorite?)` — оценка 0–5 и избранное.
- `get_settings()`, `update_settings(mapping)` — только allowlist несекретных ключей.
- `create_app(data_dir?, music_root?) -> FastAPI`; `get_catalog()` — dependency override seam; catalog router подключён к `/api`.
- Тесты: `python -m unittest discover -s tests -v`; один файл: `python -m unittest tests.catalog.test_catalog -v`.

## Из таска 03 — MPD и плеер

- `MpdClient(host, port, password?, timeout?, uri_prefix?)`; `status()`, `command(name, **params)`, `play_uris(uris, shuffle=False)`.
- `get_mpd_client()` — FastAPI dependency override seam, строит клиент из несекретных Catalog settings и `MPD_PASSWORD`.
- Player router: `GET /api/player/status`, `POST /api/player/command`, `POST /api/player/play`, `POST /api/settings/test-mpd`.
- Ошибки соединения MPD преобразуются в стабильное offline-состояние; whitelist не включает сохранённые playlist-команды.
- Тест одного модуля: `/tmp/novin-music-venv/bin/python -m unittest tests.mpd.test_mpd_client -v`.

## Из таска 02 — SMB и сканирование

- `ShareManager(mount_point="/music", runner?, env?)`; `apply(settings) -> status`, `status() -> status` — guest либо env credentials, mount только read-only.
- `Scanner.scan(root) -> ScanSnapshot`; `scanner.scan(root)` — нормализованные Track rows, cover references и counters без изменения Catalog.
- Scan router: `POST /api/scan`, `GET /api/scan/status`, `POST /api/share`, `GET /api/share/status`, `GET /api/covers/{opaque_id}`.
- Scan job использует `Catalog.reconcile_tracks()` только после успешного полного снимка и запрещает параллельный запуск.
- Cover ID непрозрачен для клиента; endpoint ограничивает файл 5 MiB, даёт MIME, ETag/304 и безопасную SVG-заглушку.
- Тест одного модуля: `/tmp/novin-music-venv/bin/python -m unittest tests.scanner.test_scanner -v`.

## Из таска 04 — веб-интерфейс

- `GET /`, неизвестные non-API routes → SPA `index.html`; `/assets/*` → статические assets; неизвестные `/api/*` сохраняют JSON 404.
- SPA обращается только к реальным `/api/*` контрактам и строит пользовательские данные через DOM nodes/`textContent`, без HTML-инъекции.
- Desktop: sidebar + catalog + fixed player; mobile: bottom navigation + compact player; обе раскладки без горизонтального overflow.
- Routes приложения: home, albums, artists, songs, playlists, favorites, settings; состояние хранится в URL hash.
- Web smoke: `/tmp/novin-music-venv/bin/python -m unittest tests.web.test_web -v`; JS syntax: `node --check app/web/assets/app.js`.

## Из таска 05 — Docker-поставка

- Compose service `novin-music`: persistent `novin_data:/data`, tmpfs `/run`, mount target `/music`, `host.docker.internal:host-gateway`, healthcheck `/api/health`.
- Контейнер запускается без `privileged`, с `cap_drop: ALL` и только `SYS_ADMIN`; root filesystem read-only, writable `/data`, `/music`, `/run`.
- Runtime secrets: `SMB_USERNAME`, `SMB_PASSWORD`, `MPD_PASSWORD`; bind settings: `NOVIN_BIND_ADDRESS`, `NOVIN_PORT`.
- `scripts/entrypoint.sh` создаёт runtime dirs и запускает uvicorn; `scripts/backup.py SOURCE DESTINATION` делает SQLite-safe backup.
- Полный test: `/tmp/novin-music-venv/bin/python -m unittest discover -s tests -v`; browser: `npm run test:web`.
