# Group chat deployment

The normal HTTP routes can continue through the current Gunicorn service. WebSocket requests under `/ws/` must reach the ASGI service in `sortan-asgi.service`.

1. Pull the code and install the updated `requirements.txt` in `/var/www/sortan/venv`.
2. Make sure `/etc/sortan.env` sets `DJANGO_SETTINGS_MODULE=config.production` and `CHANNEL_REDIS_URL` points at the site's Redis instance. The default is `redis://127.0.0.1:6379/1`.
3. Apply migrations and collect static files:

   ```sh
   cd /var/www/sortan
   /var/www/sortan/venv/bin/python manage.py migrate --noinput
   /var/www/sortan/venv/bin/python manage.py collectstatic --noinput
   ```

4. Install `sortan-asgi.service` as `/etc/systemd/system/sortan-asgi.service` and add `nginx-chat-websocket.conf` inside the existing HTTPS server block.
5. Check and restart the services:

   ```sh
   systemctl daemon-reload
   systemctl enable --now sortan-asgi
   systemctl restart sortan-asgi
   # Restart the existing Gunicorn, Celery worker, and Celery Beat units by their configured names.
   nginx -t && systemctl reload nginx
   systemctl is-active sortan-asgi nginx
   ```

Also confirm the existing Gunicorn, Celery worker, and Celery Beat units are active. Only staff administrators can configure automatic demo growth per message; the one-second Celery Beat task advances only those explicitly enabled counters. Delayed ticks expire quickly so a stopped worker does not accumulate a large backlog. Actual group membership and member reactions remain stored separately.
