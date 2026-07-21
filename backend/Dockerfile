# Базовый образ Playwright уже содержит Chromium и все системные зависимости браузера.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# ffmpeg для наложения баннера
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium уже стоит в образе, но на всякий случай гарантируем наличие
RUN python -m playwright install chromium

# Стек интерактивного входа. Ставим ПОСЛЕ pip: пакеты noVNC/websockify тянут
# системные python3-модули (typing_extensions и др.) в dist-packages, и если
# поставить их раньше — pip не сможет обновить эти же пакеты. Здесь конфликта нет.
#   xvfb    — виртуальный дисплей (окно браузера без монитора)
#   x11vnc  — VNC-сервер поверх дисплея
#   novnc/websockify — веб-клиент VNC (экран виден в панели через iframe)
#   fluxbox — лёгкий WM, чтобы окно браузера разворачивалось
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc fluxbox novnc websockify \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Данные (видео, баннеры, куки, БД) — во внешнем томе
ENV DATA_DIR=/data \
    VIDEOS_DIR=/data/videos \
    BANNERS_DIR=/data/banners \
    OUTPUT_DIR=/data/output \
    COOKIES_DIR=/data/cookies \
    DATABASE_URL=sqlite:////data/video_poster.db \
    HEADLESS=true \
    DISPLAY=:99

# 8000 — API, 6080 — noVNC (websockify)
EXPOSE 8000 6080
CMD ["/entrypoint.sh"]
