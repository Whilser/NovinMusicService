# Novin Music Service

Личный веб-интерфейс для каталога музыки на SMB-шаре и управления MPD. Сервис рассчитан на один экземпляр в доверенной домашней сети.

## Запуск через Docker Compose

Требуется Linux-хост с Docker Engine, Docker Compose v2 и поддержкой CIFS в ядре. На сервере `novin` выполните:

```sh
cp .env.example .env
docker compose up -d --build
```

По умолчанию интерфейс доступен на `http://127.0.0.1:8000`. Чтобы слушать адрес домашней сети, впишите в `.env` значения `NOVIN_BIND_ADDRESS` и, при необходимости, `NOVIN_PORT`, затем пересоздайте контейнер командой `docker compose up -d`.

При первом запуске откройте «Настройки», укажите адрес NAS и имя SMB-шары, сохраните подключение, затем запустите сканирование. Каталог создаётся в `/data/catalog.sqlite3`; named volume `novin_data` сохраняет его при перезапуске и пересоздании контейнера. Команда `docker compose down -v` намеренно удаляет этот volume и данные.

## SMB: гостевой и авторизованный доступ

Для гостевой шары оставьте `SMB_USERNAME` и `SMB_PASSWORD` пустыми. Для авторизованной заполните обе переменные в локальном `.env`; домен, если он нужен, задаётся в веб-настройках. Не коммитьте `.env` и не вставляйте пароль в настройки браузера.

Шара всегда монтируется read-only в `/music`. Дополнительные SMB-опции ограничены безопасным списком интерфейса (`vers`, `iocharset=utf8`, `noserverino`, `nounix`, `soft`). Контейнер работает как root, поскольку текущий `ShareManager` напрямую вызывает `mount.cifs`: непривилегированный Unix-пользователь не получает надёжного effective `SYS_ADMIN` для динамического mount. При этом Compose удаляет все capabilities, возвращает только `SYS_ADMIN`, запрещает новые привилегии, оставляет корневую файловую систему read-only и не использует `privileged: true`.

Основной Compose сохраняет стандартное AppArmor-ограничение Docker. Если только на Linux журнал ядра или `dmesg` явно показывает, что AppArmor блокирует `mount.cifs`, доступен осознанный opt-in:

```sh
docker compose -f docker-compose.yml -f docker-compose.apparmor-unconfined.yml up -d --build
```

Этот override снимает AppArmor-профиль со всего application-контейнера и тем самым уменьшает защиту. Используйте его лишь после подтверждённого AppArmor deny; `cap_drop: ALL`, единственный `SYS_ADMIN`, read-only rootfs и запрет `privileged` при этом сохраняются.

## MPD на сервере novin

В настройках MPD используйте host `host.docker.internal` и порт MPD (обычно `6600`). Compose отображает это имя на gateway хоста. MPD должен слушать адрес, доступный с Docker bridge, и разрешать соединение в локальном firewall. Пароль MPD, если он включён, задавайте только переменной `MPD_PASSWORD` в `.env`.

Novin отправляет MPD URI относительно его `music_directory`. MPD должен видеть те же файлы, что контейнер видит в `/music`. Если корень SMB-шары совпадает с `music_directory`, оставьте URI-префикс пустым. Если эта коллекция находится у MPD в подпапке, например `music_directory/nas`, задайте префикс `nas` — абсолютный путь указывать нельзя.

## Резервная копия

Встроенная команда использует SQLite Online Backup API и безопасна при работающем сервисе. Копия сначала синхронизируется во временный файл в каталоге назначения, затем публикуется атомарно без перезаписи. Имя назначения должно быть новым:

```sh
docker compose exec novin-music python scripts/backup.py /data/catalog.sqlite3 /data/catalog-backup.sqlite3
docker compose cp novin-music:/data/catalog-backup.sqlite3 ./catalog-backup.sqlite3
```

Храните копию вне Docker volume. Перед ручным восстановлением остановите сервис и сохраните отдельную копию текущей базы.

## Диагностика

Проверить контейнер и healthcheck:

```sh
docker compose ps
docker compose logs --tail=200 novin-music
curl http://127.0.0.1:8000/api/health
```

Если SMB не подключается, проверьте имя NAS и шары, доступность TCP 445 с хоста, наличие поддержки CIFS в ядре Linux и пару `SMB_USERNAME`/`SMB_PASSWORD`. Сообщение `operation not permitted` обычно означает, что у контейнера убран `SYS_ADMIN` или на хосте принудительно блокируется mount профилем безопасности. Не включайте `privileged`; верните настройки Compose из репозитория.

Если MPD отображается offline, проверьте его bind-адрес, порт/firewall, `MPD_PASSWORD` и доступность `host.docker.internal` из контейнера. Если трек есть в каталоге, но MPD не воспроизводит его, сверяйте именно относительный URI и URI-префикс с `music_directory` MPD.

На Linux-сервере `novin` полный config/build/up/health прогон выполняется одной командой:

```sh
docker compose config && docker compose build && docker compose up -d && docker compose exec novin-music python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read().decode())"
```

После подключения шары через интерфейс реальный CIFS mount можно проверить без вывода source, username или password:

```sh
docker compose exec novin-music findmnt --noheadings --types cifs --target /music >/dev/null && echo "CIFS mount: OK"
```

## Безопасность

В приложении намеренно нет авторизации. **Не публикуйте его порт в интернет и не ставьте за публичный reverse proxy без отдельной аутентификации.** Ограничьте доступ домашней сетью и firewall. Секреты хранятся только в `.env`; пример окружения содержит лишь пустые значения.

## Локальные проверки

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
npm ci
npm run test:web
docker compose config
```
