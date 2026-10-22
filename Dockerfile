FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt && groupadd --gid 10001 shiftrelay && useradd --uid 10001 --gid 10001 --no-create-home shiftrelay && mkdir /ca /public /status && chown -R 10001:10001 /ca /public /status
COPY --chown=10001:10001 shiftrelay/ /app/shiftrelay/
USER 10001:10001
EXPOSE 8080 8787
CMD ["python", "-m", "shiftrelay.launch"]
