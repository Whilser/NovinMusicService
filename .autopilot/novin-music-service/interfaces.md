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
