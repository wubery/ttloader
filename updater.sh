#!/usr/bin/env bash
#
# Хостовый апдейтер Video Poster. Следит за флагом update/requested (его ставит
# кнопка «Обновить» в панели) и делает git pull + пересборку контейнеров.
# Запускается на ХОСТЕ (systemd-сервис vp-updater, ставит install.sh), поэтому
# контейнеру не нужен доступ к docker.
#
# Приватный репозиторий: токен GitHub (fine-grained PAT, Contents: Read-only)
# задаётся в панели → «Настройки» → «Обновление». Панель кладёт его в
# update/git_token, апдейтер переносит токен в git credential store (chmod 600)
# и сразу удаляет файл. В remote-URL токен не пишется, чтобы не светился в логах.
#
set -u
cd "$(dirname "$0")"

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

mkdir -p update 2>/dev/null || true

# Если каталог update/ создал docker (тогда он root:root), а апдейтер запущен от
# обычного пользователя — писать статус/версию некуда, и обновление молча не
# работает. Лучше сказать об этом явно и не крутиться впустую.
if ! ( : > update/.wtest ) 2>/dev/null; then
  echo "Video Poster updater: каталог $(pwd)/update недоступен для записи от пользователя $(id -un)." >&2
  echo "Починить:  docker compose exec -T backend chown -R $(id -u):$(id -g) /update" >&2
  echo "или запустить апдейтер от root (systemd-сервис vp-updater)." >&2
  exit 1
fi
rm -f update/.wtest

CRED_FILE="$(pwd)/.git-credentials"
# Иначе git при отсутствии токена вешается в ожидании ввода логина.
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=/bin/true

write_version() {
  git rev-parse --short HEAD > update/version 2>/dev/null || echo "unknown" > update/version
}

# «scheme://host[:port]» из remote-URL — в этом виде git ищет запись в credential store
remote_base() {
  git remote get-url origin 2>/dev/null \
    | sed -nE 's#^(https?)://([^@/]*@)?([^/]+)/.*#\1://\3#p'
}

# git с версии 2.35 отказывается работать в чужом (по владельцу) репозитории —
# ловится, если апдейтер запущен от root, а файлы принадлежат пользователю.
ensure_git_safe() {
  git rev-parse --git-dir >/dev/null 2>update/.own_err && { rm -f update/.own_err; return 0; }
  if grep -qi 'dubious ownership' update/.own_err; then
    git config --global --add safe.directory "$(pwd)" 2>/dev/null || true
  fi
  rm -f update/.own_err
}

# Пишет в update/git_status: ok | auth_required | error | no_git
check_remote() {
  git rev-parse --git-dir >/dev/null 2>&1 || { echo no_git > update/git_status; return; }
  [ -f "$CRED_FILE" ] && git config credential.helper "store --file=$CRED_FILE"
  if git ls-remote --exit-code origin HEAD >/dev/null 2>update/.git_err; then
    echo ok > update/git_status
  elif grep -qiE 'authentication failed|could not read username|terminal prompts disabled|invalid username or password|repository not found|permission denied' update/.git_err; then
    echo auth_required > update/git_status
  else
    echo error > update/git_status
  fi
  rm -f update/.git_err
}

# Принимает токен из панели и сохраняет его в git credential store.
apply_token() {
  [ -f update/git_token ] || return 0
  local tok base url stripped
  if [ ! -r update/git_token ]; then
    echo "Токен получен, но апдейтер не может прочитать файл update/git_token (он создан контейнером от root, а updater.sh запущен от $(id -un 2>/dev/null)). Запустите апдейтер через systemd (vp-updater) или от root." > update/status
    return 0
  fi
  tok="$(tr -d ' \t\r\n' < update/git_token)"
  rm -f update/git_token
  [ -n "$tok" ] || return 0

  base="$(remote_base)"; base="${base:-https://github.com}"
  ( umask 077; printf '%s\n' "${base/:\/\//://x-access-token:$tok@}" > "$CRED_FILE" )
  chmod 600 "$CRED_FILE"
  git config credential.helper "store --file=$CRED_FILE"

  # если токен когда-то вписали прямо в remote — убираем его оттуда
  url="$(git remote get-url origin 2>/dev/null || true)"
  stripped="$(printf '%s' "$url" | sed -E 's#^(https?://)[^@/]*@#\1#')"
  if [ -n "$url" ] && [ "$url" != "$stripped" ]; then git remote set-url origin "$stripped"; fi

  echo "Токен GitHub сохранён, проверяю доступ…" > update/status
  check_remote
  if [ "$(cat update/git_status 2>/dev/null)" = "ok" ]; then
    echo "Токен GitHub принят — доступ к репозиторию есть." > update/status
  else
    echo "Токен не подошёл: репозиторий недоступен. Проверьте права токена (Contents: Read) и что он выдан на нужный репозиторий." > update/status
  fi
}

# git pull, работающий и когда у ветки не настроен upstream
do_pull() {
  local up br
  up="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [ -n "$up" ]; then
    git pull --ff-only
  else
    br="$(git symbolic-ref --short HEAD 2>/dev/null || echo main)"
    git pull --ff-only origin "$br"
  fi
}

ensure_git_safe
write_version
apply_token
check_remote

tick=0
while true; do
  apply_token

  if [ -f update/requested ]; then
    rm -f update/requested
    echo "Обновление: git pull…" > update/status
    pull_out="$(do_pull 2>&1)"; pull_rc=$?
    printf '%s\n' "$pull_out" >> update/updater.log
    if [ "$pull_rc" -eq 0 ]; then
      echo "Пересборка контейнеров…" > update/status
      if $DC up -d --build >> update/updater.log 2>&1; then
        write_version
        echo "Обновлено успешно ($(cat update/version)) — $(date '+%F %T')" > update/status
      else
        echo "Ошибка пересборки (см. update/updater.log)" > update/status
      fi
    else
      check_remote
      if [ "$(cat update/git_status 2>/dev/null)" = "auth_required" ]; then
        echo "Нет доступа к репозиторию (приватный?) — задайте токен GitHub в поле ниже." > update/status
      else
        # показываем в панели саму причину, а не только «см. лог».
        # Строки error:/fatal: важнее последней строки: stdout и stderr в логе
        # перемешиваются из-за буферизации, и «полезная» строка не всегда последняя.
        reason="$(printf '%s' "$pull_out" | grep -m1 -E '^(error|fatal):' || true)"
        [ -n "$reason" ] || reason="$(printf '%s' "$pull_out" | grep -vE '^\s*$' | tail -1)"
        case "$pull_out" in
          *"local changes"*|*"локальные изменения"*)
            reason="$reason (в каталоге проекта есть правки руками — отмените их: git checkout -- .)" ;;
        esac
        echo "Ошибка git pull: $(printf '%s' "${reason:-см. update/updater.log}" | cut -c1-220)" > update/status
      fi
    fi
    check_remote
  fi

  # раз в ~2 минуты обновляем индикатор доступа к репозиторию в панели
  tick=$((tick + 1))
  if [ "$tick" -ge 8 ]; then tick=0; check_remote; fi
  sleep 15
done
