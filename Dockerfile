FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    TSPB_DATA_DIR=/data

RUN mkdir -p /data

EXPOSE 8000

# 2 workers; long timeout so multi-GB whole-site bundle uploads / restores
# in a single request aren't killed mid-stream.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "600", "--access-logfile", "-", "run:app"]
