# Эксплуатация Novin Music

## Первичная установка

На сервере Debian/Ubuntu перейдите в checkout и запустите установщик:

```sh
cd /home/whilser/NovinMusicService
./scripts/install-novin-music.sh
```

Он сохраняет существующий `.env`, устанавливает системные зависимости, запускает Compose, проверяет `/api/health` и включает watchdog MPD. Перед монтированием защищённой SMB-шары заполните `SMB_USERNAME` и `SMB_PASSWORD` в `.env`, затем запустите:

```sh
./scripts/install-novin-music.sh --nas-host novincloud.local --nas-share music
```

Для гостевой шары оставьте обе переменные SMB пустыми и настройте её через веб-интерфейс. Не добавляйте `.env` в Git.

## Обновление сервиса

После обновления checkout пересоберите контейнер без удаления тома с каталогом:

```sh
docker compose -f docker-compose.yml -f docker-compose.apparmor-unconfined.yml up -d --build --force-recreate
curl http://127.0.0.1:8000/api/health
```

Не выполняйте `docker compose down -v`: он удалит SQLite-каталог вместе с оценками, избранным, плейлистами и сохранёнными снимками радио.

## MPD и восстановление

MPD и контейнер должны видеть одну и ту же музыкальную коллекцию. Для системного MPD NAS монтируется скриптом `scripts/configure-mpd-nas.sh`; его собственные плейлисты при этом не меняются.

Watchdog проверяет MPD каждую минуту и перезапускает его, если протокольный сокет не отвечает. Проверка состояния и лога:

```sh
systemctl status novin-mpd-watchdog.timer
journalctl -u novin-mpd-watchdog.service -n 50 --no-pager
```

## Радио

Страница радио открывается из сохранённого SQLite-снимка; каталог поставщика обновляется в фоне. С `SHOUTCAST_API_KEY` используется Shoutcast, без ключа — Radio Browser. Избранные станции, чёрный список и снимки независимы от текущего ответа каталога.

Станция, после которой MPD потерял ответ, попадает в локальный чёрный список и не возвращается в интерфейс. Watchdog сбрасывает зависшее состояние MPD при следующей проверке.
