FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /code
RUN apt-get update && apt-get install -y --no-install-recommends \ 
    tesseract-ocr tesseract-ocr-eng ghostscript qpdf poppler-utils \ 
    libsm6 libxext6 libxrender1 build-essential curl \
    git autoconf automake libtool pkg-config gettext autopoint python3-dev libssl-dev && rm -rf /var/lib/apt/lists/*

# Build and install libpff/pypff for PST processing
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
COPY . /code
CMD ["celery","-A","worker_app.worker","worker","--loglevel=INFO","--concurrency=2"]
