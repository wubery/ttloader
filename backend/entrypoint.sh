#!/usr/bin/env bash
# Поднимаем виртуальный дисплей + VNC + noVNC, затем API.
# Всё в одном контейнере: браузер интерактивного входа рисуется на :99,
# x11vnc отдаёт его, websockify оборачивает в websocket для noVNC-клиента.
set -e

export DISPLAY=:99

# На случай перезапуска контейнера с сохранённым /tmp
rm -f /tmp/.X99-lock 2>/dev/null || true

# Виртуальный экран 1360x900
Xvfb :99 -screen 0 1360x900x24 -nolisten tcp &
# Даём Xvfb время подняться перед запуском клиентов дисплея
sleep 2

# Оконный менеджер (чтобы окно браузера разворачивалось и получало фокус)
fluxbox >/tmp/fluxbox.log 2>&1 &

# VNC-сервер поверх :99 (без пароля — доступ только внутри LAN через панель)
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -bg -quiet -noxdamage

# noVNC: статика + websocket-мост на 6080 → VNC 5900
websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
