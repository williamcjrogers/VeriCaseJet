FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /code

# Install system dependencies including PST library
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    autoconf \
    automake \
    libtool \
    pkg-config \
    libssl-dev \
    gettext \
    autopoint \
    python3-dev \
    pst-utils \
    tesseract-ocr \
    ocrmypdf \
    libpff-dev \
    && rm -rf /var/lib/apt/lists/*

# Build and install libpff from source (required for pypff)
RUN git clone https://github.com/libyal/libpff.git /tmp/libpff && \
    cd /tmp/libpff && \
    ./synclibs.sh && \
    ./autogen.sh && \
    ./configure --enable-python PYTHON_VERSION=3.11 PYTHON=/usr/local/bin/python3 && \
    make && \
    make install && \
    ldconfig && \
    cd /tmp && rm -rf /tmp/libpff

# Install Python dependencies
COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

# Copy code
COPY worker_app /code/worker_app
COPY api/app /code/app

# Set working directory and pythonpath
ENV PYTHONPATH=/code
WORKDIR /code

EXPOSE 8000
# Bind to the configured Celery queue (default "celery"); adjust CELERY_QUEUE env to change
CMD ["celery", "-A", "worker_app.worker", "worker", "-Q", "celery", "--loglevel=info", "--concurrency=2"]
