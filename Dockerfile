FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN useradd --create-home --uid 10001 placement && mkdir -p /app/staticfiles && chown -R placement:placement /app
USER placement
EXPOSE 8000
CMD ["waitress-serve", "--listen=0.0.0.0:8000", "--threads=8", "config.wsgi:application"]
