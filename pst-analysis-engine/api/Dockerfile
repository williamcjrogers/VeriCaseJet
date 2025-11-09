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

COPY app /code/app

EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
