# Установка Video Poster на сервер

Панель автопостинга в TikTok/YouTube Shorts. Разворачивается в Docker одной командой.
Так как сервер доступен из интернета, панель закрыта логином/паролем (HTTP Basic Auth) —
защита распространяется на всё: саму панель, API и окно интерактивного входа (noVNC).

## Требования

- Linux-сервер с **Docker** и **docker compose** (плагин v2).
- `openssl` (обычно уже стоит) — для генерации пароля.
- Открытый порт панели (по умолчанию **8088**).

## Установка

1. Загрузите папку `video-poster` на сервер (scp / rsync / панель хостинга). Пример:
   ```bash
   scp -r video-poster root@ВАШ_СЕРВЕР:/root/
   ```
2. Зайдите на сервер и запустите установщик:
   ```bash
   cd /root/video-poster
   bash install.sh
   ```
3. По завершении установщик **один раз** покажет в консоли:
   ```
   Панель:  http://<IP-сервера>:8088
   Логин:   admin
   Пароль:  <случайный пароль>
   ```
   **Сохраните пароль** — больше он не показывается.

Первая сборка занимает несколько минут (тянется образ Playwright ~2 ГБ и ставится Chromium).

## Ручная установка (без install.sh)

Если хочешь поставить руками из git:

```bash
# 1. Клонировать
git clone https://github.com/wubery/ttloader.git
cd ttloader

# 2. Создать логин/пароль для панели (Basic Auth).
#    Замените ВАШ_ПАРОЛЬ на свой.
mkdir -p secrets
echo "admin:$(openssl passwd -apr1 'ВАШ_ПАРОЛЬ')" > secrets/.htpasswd
chmod 644 secrets/.htpasswd      # ВАЖНО: 644, иначе nginx не прочитает файл → ошибка 500

# 3. Запустить (порт можно поменять через VP_PORT)
VP_PORT=8088 docker compose up -d --build

# 4. Проверить
docker compose ps
```

Панель будет на `http://<IP-сервера>:8088`, вход — `admin` / ВАШ_ПАРОЛЬ.

> **Частая ошибка 500 после установки** — неправильные права на `secrets/.htpasswd`.
> Файл читает процесс nginx (не root), поэтому нужен доступ на чтение: `chmod 644 secrets/.htpasswd`,
> затем `docker compose restart frontend`.

## Параметры установки (необязательно)

```bash
VP_PORT=9000 bash install.sh      # другой порт панели
VP_USER=boss bash install.sh      # другой логин
VP_PASS='МойПароль' bash install.sh   # задать свой пароль
VP_REGEN=1 bash install.sh        # сбросить/пересоздать логин-пароль
```

## Управление

```bash
cd video-poster
docker compose ps              # статус
docker compose logs -f backend # логи
docker compose restart         # перезапуск
docker compose down            # остановить
```

## Обновление

Загрузите новую версию файлов поверх и снова запустите `bash install.sh` —
логин/пароль и данные (тома `vp_data`) сохранятся.

## Важно

- **Всегда** запускайте через `install.sh` (он создаёт файл пароля `secrets/.htpasswd`).
  Если стартовать `docker compose up` напрямую без этого файла — nginx не запустится.
- Файл `secrets/.htpasswd` содержит хэш пароля. Не удаляйте его; для смены пароля —
  `VP_REGEN=1 bash install.sh`.
- Прокси и куки аккаунтов настраиваются уже в самой панели (вкладка «Аккаунты»).
- Если панель на том же VPS, что и прокси (gost на порту 8899), в поле прокси аккаунта
  используйте адрес этого сервера — IP входа и постинга совпадут.
