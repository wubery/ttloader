#!/usr/bin/env bash
#
# Установщик Video Poster.
# Запуск на сервере:  ./install.sh
#
# Генерирует логин/пароль для входа в панель (Basic Auth) и показывает их
# ОДИН РАЗ в консоли. Пароль нигде больше не отображается.
#
# Переменные (необязательно):
#   VP_PORT=9000     — порт панели (по умолчанию 8088)
#   VP_USER=admin    — логин (по умолчанию admin)
#   VP_PASS=...      — задать свой пароль (иначе сгенерируется случайный)
#   VP_REGEN=1       — пересоздать логин/пароль, даже если уже настроены
#
set -euo pipefail
cd "$(dirname "$0")"

GRN='\033[32m'; RED='\033[31m'; YEL='\033[33m'; NC='\033[0m'
info(){ printf "${GRN}==>${NC} %s\n" "$1"; }
err(){ printf "${RED}Ошибка:${NC} %s\n" "$1" >&2; }

# --- проверки окружения ---
command -v docker >/dev/null 2>&1 || { err "Docker не установлен. Установите Docker и повторите."; exit 1; }
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  err "docker compose не найден. Установите плагин docker compose."; exit 1
fi
command -v openssl >/dev/null 2>&1 || { err "openssl не установлен (нужен для генерации пароля)."; exit 1; }

export VP_PORT="${VP_PORT:-8088}"
ADMIN_USER="${VP_USER:-admin}"

# --- логин/пароль (Basic Auth) ---
mkdir -p secrets
NEED_CREDS=1
if [ -f secrets/.htpasswd ] && [ "${VP_REGEN:-0}" != "1" ]; then
  NEED_CREDS=0
fi

ADMIN_PASS=""
if [ "$NEED_CREDS" = "1" ]; then
  ADMIN_PASS="${VP_PASS:-$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 20)}"
  HASH="$(openssl passwd -apr1 "$ADMIN_PASS")"
  printf '%s:%s\n' "$ADMIN_USER" "$HASH" > secrets/.htpasswd
  chmod 600 secrets/.htpasswd
fi

# --- сборка и запуск ---
info "Сборка и запуск контейнеров (первый раз — несколько минут, тянется образ Playwright)…"
$DC up -d --build

# публичный IP для подсказки (необязательно)
PUBIP="$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo '<IP-сервера>')"

echo
echo "=================================================================="
printf "  ${GRN}Video Poster установлен и запущен${NC}\n"
echo "  Панель:  http://$PUBIP:$VP_PORT"
if [ "$NEED_CREDS" = "1" ]; then
  echo "  Логин:   $ADMIN_USER"
  echo "  Пароль:  $ADMIN_PASS"
  echo
  printf "  ${YEL}СОХРАНИТЕ пароль — он больше не будет показан.${NC}\n"
  printf "  ${YEL}Сброс пароля:  VP_REGEN=1 ./install.sh${NC}\n"
else
  echo "  Логин/пароль: заданы ранее (secrets/.htpasswd)."
  echo "  Сброс пароля:  VP_REGEN=1 ./install.sh"
fi
echo "=================================================================="
echo
$DC ps
