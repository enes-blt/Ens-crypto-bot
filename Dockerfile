FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 bot && chown -R bot:bot /app
USER bot

CMD ["crypto-trend", "paper-daemon", "--interval-seconds", "300"]

