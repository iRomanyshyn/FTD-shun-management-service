FROM python:3.12-slim AS application

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FTD_SHUN_ASSET_ROOT=/app
WORKDIR /app
RUN useradd --system --uid 10001 --create-home app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY templates ./templates
COPY static ./static
RUN python -m ftd_shun_manager.build_info --root /app
USER 10001:10001

# Native libloc stays in the optional background worker image only. Its distro
# bindings run under /usr/bin/python3, separate from the application's Python.
FROM application AS ip-context
USER root
RUN apt-get update && apt-get install -y --no-install-recommends location python3-location \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001

# Ordinary API/Web builds do not install the optional location toolchain.
FROM application AS runtime
