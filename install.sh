#!/usr/bin/env bash
#
# Установщик Video Poster.  Запуск на сервере:  bash install.sh
#
# Задаёт логин/пароль администратора панели и показывает их в консоли.
# Пароль хранится в .env (в git не попадает) и применяется при первом запуске;
# дальше его можно менять в самой панели («Настройки»).
#
# Переменные (необязательно):
#   VP_PORT=9000     — порт панели (по умолчанию 8088)
#   VP_USER=admin    — логин администратора
#   VP_PASS=...      — задать свой пароль (иначе сгенерируется случайный)
#   VP_REGEN=1       — пересоздать .env с новыми логином/паролем
#   VP_GIT_TOKEN=... — токен GitHub, если репозиторий приватный (для обновлений).
#                      Можно не задавать здесь, а вписать потом в панели.
#
set -euo pipefail
cd "$(dirname "$0")"

GRN='\033[32m'; RED='\033[31m'; YEL='\033[33m'; NC='\033[0m'
info(){ printf "${GRN}==>${NC} %s\n" "$1"; }
err(){ printf "${RED}Ошибка:${NC} %s\n" "$1" >&2; }

command -v docker >/dev/null 2>&1 || { err "Docker не установлен."; exit 1; }
if docker compose version >/dev/null 2>&1; then DC="docker compose";
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose";
else err "docker compose не найден."; exit 1; fi

VP_PORT="${VP_PORT:-8088}"
ADMIN_USER="${VP_USER:-admin}"

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${VP_PORT} "; then
  err "Порт ${VP_PORT} уже занят. Выберите другой:  VP_PORT=9000 bash install.sh"; exit 1
fi

gen_pass() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 20
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20
  fi
}

NEED_CREDS=1
ADMIN_PASS=""
if [ -f .env ] && [ "${VP_REGEN:-0}" != "1" ]; then
  NEED_CREDS=0
  ADMIN_PASS="$(grep -E '^VP_ADMIN_PASS=' .env | cut -d= -f2- || true)"
  ADMIN_USER="$(grep -E '^VP_ADMIN_USER=' .env | cut -d= -f2- || echo "$ADMIN_USER")"
else
  ADMIN_PASS="${VP_PASS:-$(gen_pass)}"
  cat > .env <<EOF
VP_PORT=${VP_PORT}
VP_ADMIN_USER=${ADMIN_USER}
VP_ADMIN_PASS=${ADMIN_PASS}
EOF
  chmod 600 .env
fi
export VP_PORT

print_creds() {
  echo
  echo "=================================================================="
  printf "  ${GRN}Данные для входа в панель:${NC}\n"
  echo "  Логин:   $ADMIN_USER"
  echo "  Пароль:  $ADMIN_PASS"
  printf "  ${YEL}Пароль хранится в .env; изменить можно в «Настройках» панели.${NC}\n"
  echo "  Пересоздать логин/пароль: VP_REGEN=1 bash install.sh (только первый запуск)"
  echo "=================================================================="
}

# Каталог флага обновления создаём ДО compose: иначе его создаст docker от root и
# хостовый updater.sh (если он работает не от root) не сможет туда писать.
mkdir -p update

info "Сборка и запуск контейнеров (первый раз — несколько минут)…"
$DC up -d --build

# --- самообновление: версия + хостовый updater ---
git rev-parse --short HEAD > update/version 2>/dev/null || echo "unknown" > update/version

# Приватный репозиторий: токен GitHub → в git credential store (не в remote-URL).
if [ -n "${VP_GIT_TOKEN:-}" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  GH_HOST="$(git remote get-url origin 2>/dev/null | sed -nE 's#^https?://([^@/]*@)?([^/]+)/.*#\2#p')"
  GH_HOST="${GH_HOST:-github.com}"
  ( umask 077; printf 'https://x-access-token:%s@%s\n' "$VP_GIT_TOKEN" "$GH_HOST" > .git-credentials )
  chmod 600 .git-credentials
  git config credential.helper "store --file=$(pwd)/.git-credentials"
  ORIG_URL="$(git remote get-url origin 2>/dev/null || true)"
  CLEAN_URL="$(printf '%s' "$ORIG_URL" | sed -E 's#^(https?://)[^@/]*@#\1#')"
  if [ -n "$ORIG_URL" ] && [ "$ORIG_URL" != "$CLEAN_URL" ]; then git remote set-url origin "$CLEAN_URL"; fi
  if GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code origin HEAD >/dev/null 2>&1; then
    info "Токен GitHub принят — обновление из приватного репозитория работает"
  else
    err "Токен GitHub не даёт доступа к репозиторию (нужно право Contents: Read)"
  fi
fi
chmod +x updater.sh 2>/dev/null || true
if command -v systemctl >/dev/null 2>&1 && [ -w /etc/systemd/system ]; then
  cat > /etc/systemd/system/vp-updater.service <<EOF
[Unit]
Description=Video Poster updater
After=docker.service
[Service]
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/env bash $(pwd)/updater.sh
Restart=always
[Install]
WantedBy=multi-user.target
EOF
  if systemctl daemon-reload && systemctl enable --now vp-updater.service 2>/dev/null; then
    info "Самообновление: установлен systemd-сервис vp-updater"
  else
    info "Самообновление: не удалось включить сервис — запустите вручную: nohup bash updater.sh &"
  fi
else
  info "Самообновление: systemd недоступен — запустите вручную: nohup bash updater.sh &"
fi

PUBIP="$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo '<IP-сервера>')"
echo
echo "=================================================================="
printf "  ${GRN}Video Poster установлен и запущен${NC}\n"
echo "  Панель:  http://$PUBIP:$VP_PORT"
echo "=================================================================="
print_creds
echo
$DC ps
