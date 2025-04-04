FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN uv pip install -r requirements.txt

# Copy application code
COPY . .

# Create static directory
RUN mkdir -p static/uploads

# Expose port
EXPOSE 8000

# Create entrypoint script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Wait for PostgreSQL to be available\n\
if [ -n "$DB_HOST" ]; then\n\
    echo "Waiting for PostgreSQL to be available..."\n\
    while ! nc -z $DB_HOST $DB_PORT; do\n\
        sleep 0.1\n\
    done\n\
    echo "PostgreSQL is available"\n\
fi\n\
\n\
# Run migrations\n\
alembic upgrade head\n\
\n\
# Start application\n\
if [ "$1" = "worker" ]; then\n\
    echo "Starting Celery worker..."\n\
    celery -A celery_app worker --loglevel=info\n\
elif [ "$1" = "beat" ]; then\n\
    echo "Starting Celery beat..."\n\
    celery -A celery_app beat --loglevel=info\n\
else\n\
    echo "Starting API server..."\n\
    uvicorn app.main:app --host $APP_HOST --port $APP_PORT\n\
fi\n\
' > /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]