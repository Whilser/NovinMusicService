# 04 — Apple Music-подобный веб-интерфейс

**Требования:** R04, R12, R13, R14, R15, R16, R17, R18, R19, R21i, R23i, G02
**Blocked by:** 02, 03
**Зона:** `app/web/` · `tests/web/` · `app/main.py` (только static/SPА hosting seam) · `package.json` (test-only Playwright contract)
**Волна:** 3
**Status:** ready

## Что должно заработать

Полноценное адаптивное SPA без сборщика: домашняя медиатека, альбомы, исполнители, песни, локальные плейлисты, избранное, настройки, сканирование и закреплённый MPD-плеер. Визуальный язык максимально близок к Apple Music, но без копирования товарных знаков и чужих ассетов.

## Из брифа, дословно

> «с веб интерфейсом»
> «Интерфейс должен быть максимально похож на apple Music»
> «возможность создания плейлистов, выставления оценок, папка избарнного, обложка»
> «прослушивание подряд или в случайном порядке»

## Разделы спецификации

Истории 9–13, 16–24, 26; Интерфейс; HTTP API; эталон `reference.md`.

## Критерии приёмки

- [ ] Desktop имеет sidebar, каталог карточек/строк и fixed mini-player; mobile — bottom nav и компактный плеер без overflow
- [ ] Главная, Albums, Artists, Songs, Playlists, Favorites, Settings работают через реальные API, включая empty/loading/error состояния
- [ ] Поиск и пагинация, выбор альбома/исполнителя/плейлиста, play и shuffle работают end-to-end
- [ ] Создание/переименование/удаление плейлистов, добавление/удаление/перестановка, rating и favorite доступны в UI
- [ ] Настройки SMB/MPD, test connection и scan progress доступны без ввода секретов
- [ ] Player polling показывает обложку, track, elapsed/duration и volume; transport/seek корректно блокируются offline
- [ ] Интерфейс клавиатурный, с focus-visible, контрастом и reduced-motion; smoke-тесты проверяют DOM hooks и отсутствие unsafe HTML rendering
- [ ] `app.main` раздаёт SPA и assets на не-API маршрутах, не перехватывая `/api/*`
