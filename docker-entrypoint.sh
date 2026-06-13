#!/bin/sh
# Préparation au démarrage du conteneur (issue #17) :
# applique les migrations (dont le seed des sites) puis collecte les statiques,
# avant de passer la main à la commande (gunicorn par défaut).
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
