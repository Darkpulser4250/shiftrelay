FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt && groupadd --gid 10001 shiftrelay && useradd --uid 10001 --gid 10001 --no-create-home shiftrelay && mkdir /state /status && chown 10001:10001 /state /status
COPY --chown=10001:10001 ytbridge/ /app/ytbridge/
COPY LICENSE NOTICE.md /app/
USER 10001:10001
ENTRYPOINT ["python", "-m", "ytbridge.cli"]
CMD ["run"]
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 CMD ["python", "-c", "import json,time; from pathlib import Path; p=Path('/status/youtube-tv.json'); d=json.loads(p.read_text()); assert d['schema']==1 and time.time()-d['updated_at']<45"]
