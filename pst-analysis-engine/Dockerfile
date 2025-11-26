FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf \
    automake \
    autopoint \
    build-essential \
    curl \
    gettext \
    ghostscript \
    git \
    libsm6 \
    libssl-dev \
    libtool \
    libxext6 \
    libxrender1 \
    pkg-config \
    poppler-utils \
    python3-dev \
    qpdf \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Clone and configure libpff
RUN git clone https://github.com/libyal/libpff.git /tmp/libpff && \
    cd /tmp/libpff && \
    git checkout 7c2e2e2b6e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e && \
    ./synclibs.sh && \
    ./autogen.sh

# Build and install libpff with Python bindings
RUN cd /tmp/libpff && \
    ./configure --enable-python PYTHON_VERSION=3.11 PYTHON=/usr/local/bin/python3 && \
    make -j$(nproc) && \
    make install && \
    ldconfig

# Cleanup libpff build files
RUN rm -rf /tmp/libpff

# Install Python dependencies
COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

# Copy application code
COPY . /code

CMD ["celery","-A","worker_app.worker","worker","--loglevel=INFO","--concurrency=2"]
