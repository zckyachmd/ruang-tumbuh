FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY migrations /app/migrations
COPY ruang_tumbuh /app/ruang_tumbuh
COPY web /app/web
COPY docs/who-assets.json /app/docs/who-assets.json
USER 10001
EXPOSE 8000
CMD ["uvicorn", "ruang_tumbuh.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

