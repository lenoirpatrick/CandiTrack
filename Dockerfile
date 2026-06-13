# CandiTrack — image de production (issue #17)
# Django 6 + gunicorn, statiques servis par WhiteNoise.
FROM python:3.14-slim

# Sorties Python non bufferisées + pas de .pyc, pour des logs propres en conteneur.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=canditrack.settings

WORKDIR /app

# Dépendances d'abord : couche mise en cache tant que requirements.txt ne change pas.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Code applicatif.
COPY . .

# Utilisateur non-root + dossiers data inscriptibles (db sqlite, media, statiques).
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media /app/staticfiles /app/data \
    && chown -R app:app /app
USER app

EXPOSE 53487

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "canditrack.wsgi:application", "--bind", "0.0.0.0:53487", "--workers", "3"]
