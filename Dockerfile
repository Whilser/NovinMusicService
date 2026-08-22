FROM python:3.12.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NOVIN_DATA_DIR=/data \
    NOVIN_MUSIC_ROOT=/music \
    TMPDIR=/run/novin

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates cifs-utils util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/novin /data /music /run

WORKDIR /opt/novin

COPY requirements-prod.lock ./
RUN python -m pip install --no-cache-dir --requirement requirements-prod.lock

COPY app ./app
COPY scripts ./scripts

EXPOSE 8000

# CIFS mounting needs CAP_SYS_ADMIN. Compose drops every other capability and
# makes the image filesystem read-only, so the process intentionally stays root.
USER root
ENTRYPOINT ["/bin/sh", "/opt/novin/scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
