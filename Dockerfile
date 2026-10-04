# LinkedIn Content Engine — see docker-compose.yml for how it's run.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The app itself. Keys (.env), the database and generated media stay out of the
# image (.dockerignore) and are mounted at run time instead.
# Playwright is not installed here (it is ~134 MB and only the optional screen-record
# and deep-research features use it), so those two stay off in the container.
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"

# Listens on every address *inside* the container; compose publishes the port to
# 127.0.0.1 only, so the dashboard is never reachable from the network.
# settings.HOST stays 127.0.0.1, which keeps the host allowlist to localhost.
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
