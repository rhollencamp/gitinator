FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies in their own layer to maximize cache reuse
COPY pyproject.toml .
RUN pip install --no-cache-dir --break-system-packages -e .

# Copy the rest of the application code
COPY . .

# Collect static files, fly.io will serve them
RUN python3 manage.py collectstatic --noinput

EXPOSE 8000
USER nobody
CMD ["python3", "-m", "gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
