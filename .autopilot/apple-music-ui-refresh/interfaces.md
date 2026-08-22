# Что уже построено

## Реализованные части web presentation

- `app/web/assets/apple.css` — Apple Music-подобные токены, sidebar, hero, списки, плавающий player и responsive-компоновка.
- `app/web/assets/app.js` — единый реестр inline SVG, построение секций навигации и album/artist hero при сохранении прежних action/API-швов.
- `app/web/index.html` — подключение нового визуального слоя поверх существующих базовых и mobile-стилей.
- `tests/web/browser_smoke.mjs` и `tests/web/test_web.py` — публичные проверки нового accent, действий воспроизведения и доступности визуального слоя.

## Границы, решённые в спецификации

- Web presentation владеет визуальной системой, SVG-иконками и построением экранов.
- Наружу остаются прежние DOM-id, `data-action`, `data-command`, hash-маршруты и запросы `/api/*`.
- Детали SVG-path, CSS-токены и композиция hero/list/player остаются внутри web presentation.
- Единственный тестовый шов — публичная SPA через HTTP с перехватом существующих `/api/*`.

## Общие правила проекта

- Vanilla JavaScript, HTML и CSS; новых зависимостей не добавлять.
- Backend, API, каталог, MPD, SMB, база и Docker-контракты не менять.
- Полный browser smoke: `npm run test:web`.
- Синтаксис JS: `node --check app/web/assets/app.js`.
- API/static unit: `/tmp/novin-music-venv/bin/python -m unittest tests.web.test_web -v`.
- Если не хватает зависимости — не устанавливать, а вернуть `BLOCKED`.
