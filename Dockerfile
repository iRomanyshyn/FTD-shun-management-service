FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 --create-home app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY templates ./templates
COPY static ./static
USER 10001:10001
