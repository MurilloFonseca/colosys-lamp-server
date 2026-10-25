FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user; /data holds the OAuth client credentials (a named volume)
RUN useradd --create-home app && mkdir /data && chown app /data
USER app

COPY app ./app

EXPOSE 8000
# --timeout-graceful-shutdown: open SSE streams would otherwise block a restart
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "5"]
