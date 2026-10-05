FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN DJANGO_SECRET_KEY=build-only-placeholder-key-never-used-at-runtime-0000000000000000 python manage.py collectstatic --noinput \
    && groupadd -g 10001 app && useradd -u 10001 -g app -M app \
    && mkdir -p /app/data /app/backups && chown -R app:app /app/data /app/backups \
    && chmod 700 /app/data /app/backups && chmod +x /app/scripts/entrypoint.sh
USER app
EXPOSE 8000
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
