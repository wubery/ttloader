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

COPY app ./app

# Данные (видео, баннеры, куки, БД) — во внешнем томе
ENV DATA_DIR=/data \
    VIDEOS_DIR=/data/videos \
    BANNERS_DIR=/data/banners \
    OUTPUT_DIR=/data/output \
    COOKIES_DIR=/data/cookies \
    DATABASE_URL=sqlite:////data/video_poster.db \
    HEADLESS=true

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
