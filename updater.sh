#!/usr/bin/env bash
#
# Хостовый апдейтер Video Poster. Следит за флагом update/requested (его ставит
# кнопка «Обновить» в панели) и делает git pull + пересборку контейнеров.
# Запускается на ХОСТЕ (systemd-сервис vp-updater, ставит install.sh), поэтому
# контейнеру не нужен доступ к docker.
#
set -u
cd "$(dirname "$0")"

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

mkdir -p update

write_version() {
  git rev-parse --short HEAD > update/version 2>/dev/null || echo "unknown" > update/version
}
write_version

while true; do
  if [ -f update/requested ]; then
    rm -f update/requested
    echo "Обновление: git pull…" > update/status
    if git pull --ff-only >> update/updater.log 2>&1; then
      echo "Пересборка контейнеров…" > update/status
      if $DC up -d --build >> update/updater.log 2>&1; then
        write_version
        echo "Обновлено успешно ($(cat update/version)) — $(date '+%F %T')" > update/status
      else
        echo "Ошибка пересборки (см. update/updater.log)" > update/status
      fi
    else
      echo "Ошибка git pull (см. update/updater.log)" > update/status
    fi
  fi
  sleep 15
done
