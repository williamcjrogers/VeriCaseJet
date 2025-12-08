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

COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

# Copy application code
COPY api/app /code/app

# Copy worker code (enables this image to run as a Celery worker too)
COPY worker_app /code/worker_app

# Copy UI files
COPY ui /code/ui

# Copy migration scripts
COPY api/migrations /code/migrations
COPY api/apply_migrations.py /code/apply_migrations.py

# Copy and setup startup script
COPY api/start.sh /code/start.sh
RUN sed -i 's/\r$//' /code/start.sh
RUN chmod +x /code/start.sh

EXPOSE 8000
CMD ["/code/start.sh"]
