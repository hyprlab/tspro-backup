FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .
COPY docker-entrypoint.py /usr/local/bin/docker-entrypoint.py

ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    TSPB_DATA_DIR=/data

# Unprivileged runtime user. The container still *starts* as root so the
# entrypoint can chown a root-owned bind-mounted /data, then it drops to this
# user before exec'ing gunicorn (see docker-entrypoint.py).
RUN useradd -u 10001 -r -m -s /usr/sbin/nologin app && mkdir -p /data && chown app:app /data

EXPOSE 8000

# Entrypoint drops privileges; CMD is the actual server. Threaded workers
# (gthread) so a couple of slow multi-GB transfers can't pin every worker and
# stall the console — each worker handles several concurrent requests. Long
# timeout so a single large upload/restore isn't killed mid-stream.
ENTRYPOINT ["python", "/usr/local/bin/docker-entrypoint.py"]
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "-k", "gthread", "--threads", "4", "--timeout", "600", "--access-logfile", "-", "run:app"]
