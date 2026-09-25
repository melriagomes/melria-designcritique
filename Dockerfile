# Railway (and any other Docker-based host) needs Chromium's actual browser
# binary + OS libraries present in the same image that runs the app —
# `pip install playwright` alone only installs the Python driver, not the
# browser, which is what caused "Executable doesn't exist at
# /root/.cache/ms-playwright/..." in production. Installing it here, in the
# same build, means it lands exactly where the Playwright driver looks for
# it at runtime.
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY . .

CMD gunicorn --bind 0.0.0.0:$PORT --worker-class gthread --threads 4 --timeout 300 server:app
