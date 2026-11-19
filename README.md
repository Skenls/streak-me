# StreakMe

Telegram Mini App для общих огоньков с друзьями. На главном экране можно перелистывать серии свайпом, стрелками или кнопками под каруселью. Нажатие на аватарку открывает полноэкранную карточку. Цвет огонька меняется на отметках 3, 10, 30, 100 и 200 дней.

## Как считается серия

После приглашения у пары появляется общий огонёк. Первый день засчитывается, когда оба участника отметятся. Продлить серию можно в Mini App или через inline-кнопку в чате. Повторные отметки за тот же день счётчик не меняют. Дни считаются по UTC. Если пара пропустила день, при следующих двух отметках счёт начнётся с 1.

Чтобы открыть inline-меню, введи `@имя_бота` и пробел в поле сообщения Telegram. Меню предлагает пригласить друга, продлить серию и поделиться её текущим статусом. Можно дописать имя или ник, чтобы отфильтровать серии. Статус в отправленном сообщении отражает момент публикации. Кнопка под сообщением показывает участникам актуальный статус.

Приглашение действует семь дней и рассчитано на одного друга. Для аватарок используется фото из профиля Telegram, когда Telegram передаёт его Mini App. До этого и при отсутствии фото отображаются инициалы.

## Запуск в Docker

StreakMe открывается с мобильной кнопки бота. В обычном браузере страница предлагает открыть Telegram.

1. В каталоге репозитория создай `.env`, если файла ещё нет.

   ```sh
   umask 077
   test -f .env || cp .env.example .env
   chmod 600 .env
   ```

2. Укажи `BOT_TOKEN` от [@BotFather](https://t.me/BotFather) и включи inline-режим командой `/setinline`. В `APP_URL` укажи адрес Mini App, например `https://streakme.185.240.121.158.sslip.io/`.
3. Задай разные случайные пароли `POSTGRES_PASSWORD` и `APP_DB_PASSWORD`. Для новой базы каждый можно сгенерировать командой `openssl rand -hex 32`. При обновлении существующей установки используй прежний `POSTGRES_PASSWORD` от её тома.
4. Создай общую сеть, подключи Caddy и запусти Compose по инструкции ниже. После запуска отправь боту `/start` и нажми **Открыть StreakMe**.

`db-role` создаёт таблицы и выдаёт приложению отдельную PostgreSQL-роль для работы с данными. У сервиса приложения и базы нет опубликованных хостовых портов. Данные хранятся в томе `streakme-data`.

Бот настраивает кнопку меню при старте и получает обновления через long polling. Запускай один экземпляр сервиса `app` на токен. Если для него уже настроен webhook, удали его перед первым запуском polling. Данные запуска Telegram принимаются в течение часа. После истечения срока открой Mini App заново.

## Caddy в Docker

Добавь в существующий Caddyfile отдельный блок.

```caddyfile
streakme.185.240.121.158.sslip.io {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		-Server
	}
	reverse_proxy streakme-app:8080
}
```

Создай сеть и подключи работающий контейнер Caddy один раз. При другом имени сети укажи то же значение в `CADDY_NETWORK`.

```sh
docker network inspect streakme_proxy >/dev/null 2>&1 || docker network create streakme_proxy
docker network connect streakme_proxy shlyapgrader_caddy
docker compose up -d --build --wait
docker exec shlyapgrader_caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec shlyapgrader_caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Чтобы подключение сохранялось после пересоздания Caddy, добавь `streakme_proxy` как external-сеть в Compose того проекта и подключи к ней сервис Caddy вместе с его текущими сетями. Внешние порты 80 и 443 нужны Caddy для HTTPS. Проверка `/healthz` доступна внутри контейнера приложения.

```sh
docker compose ps
docker compose logs --tail=100 app
```

## Разработка

Образ использует Python 3.15.2, aiogram 3.32.0 и PostgreSQL 18.7. Фронтенд собирается на Node.js 26.13.1 с React 19.3.1, TypeScript 7.0.2 и Vite 8.3.8.

```sh
npm --prefix web ci
npm --prefix web run dev
npm --prefix web run build
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
```

Для интеграционного теста укажи `TEST_DATABASE_URL` с адресом отдельной тестовой базы и заранее примени к ней `streakme/schema.sql`. Тест создаёт профили и серии и имитирует обновления Telegram через aiogram.

Документация по интеграции и жестам. [Telegram Mini Apps](https://core.telegram.org/bots/webapps), [Telegram Inline Bots](https://core.telegram.org/bots/inline), [CSS Scroll Snap и карусели](https://developer.chrome.com/blog/carousels-with-css), [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
