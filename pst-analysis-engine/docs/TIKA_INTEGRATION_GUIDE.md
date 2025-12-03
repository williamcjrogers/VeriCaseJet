# Apache Tika Integration Guide

**Version:** 1.0  
**Purpose:** Complete Tika setup for document processing and OCR

---

## 1. Tika Overview

Apache Tika extracts text and metadata from 1000+ file types:
- PDF, DOCX, XLSX, PPTX
- Images (with OCR)
- Email formats (MSG, EML)
- Archives (ZIP, RAR)
- CAD files (DWG, DXF)

---

## 2. Deployment Options

### Option A: Docker Compose (Development)

```yaml
tika:
  image: apache/tika:2.9.1-full
  ports:
    - "9998:9998"
  environment:
    - TIKA_CONFIG=/tika-config.xml
  volumes:
    - ./tika-config.xml:/tika-config.xml
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9998/tika"]
    interval: 30s
    timeout: 10s
    retries: 3
```

### Option B: Kubernetes (Production)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tika
spec:
  replicas: 3
  selector:
    matchLabels:
      app: tika
  template:
    metadata:
      labels:
        app: tika
    spec:
      containers:
      - name: tika
        image: apache/tika:2.9.1-full
        ports:
        - containerPort: 9998
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        env:
        - name: TIKA_CONFIG
          value: "/config/tika-config.xml"
        volumeMounts:
        - name: config
          mountPath: /config
      volumes:
      - name: config
        configMap:
          name: tika-config
---
apiVersion: v1
kind: Service
metadata:
  name: tika
spec:
  selector:
    app: tika
  ports:
  - port: 9998
    targetPort: 9998
  type: ClusterIP
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: tika-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: tika
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

---

## 3. Configuration

### tika-config.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<properties>
  <parsers>
    <!-- Default parser for all formats -->
    <parser class="org.apache.tika.parser.DefaultParser"/>
    
    <!-- PDF with OCR -->
    <parser class="org.apache.tika.parser.pdf.PDFParser">
      <params>
        <param name="extractInlineImages" type="bool">true</param>
        <param name="ocrStrategy" type="string">auto</param>
        <param name="extractUniqueInlineImagesOnly" type="bool">true</param>
        <param name="sortByPosition" type="bool">true</param>
      </params>
    </parser>
    
    <!-- Office documents -->
    <parser class="org.apache.tika.parser.microsoft.ooxml.OOXMLParser"/>
    
    <!-- Images with OCR -->
    <parser class="org.apache.tika.parser.ocr.TesseractOCRParser">
      <params>
        <param name="language" type="string">eng</param>
        <param name="enableImageProcessing" type="bool">true</param>
        <param name="density" type="int">300</param>
      </params>
    </parser>
  </parsers>
  
  <!-- Detector -->
  <detector class="org.apache.tika.detect.DefaultDetector"/>
  
  <!-- Service loader -->
  <service-loader initializableProblemHandler="ignore"/>
</properties>
```

---

## 4. Python Client

### utils/tika_client.py

```python
import requests
import os
import logging
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class TikaClient:
    def __init__(self):
        self.url = os.getenv('TIKA_URL', 'http://localhost:9998')
        self.timeout = int(os.getenv('TIKA_TIMEOUT', 300))
        self.max_file_size = int(os.getenv('TIKA_MAX_FILE_SIZE', 104857600))
    
    def extract_text(self, file_path: str) -> str:
        """Extract text from document"""
        file_size = os.path.getsize(file_path)
        if file_size > self.max_file_size:
            raise ValueError(f'File too large: {file_size} bytes')
        
        try:
            with open(file_path, 'rb') as f:
                response = requests.put(
                    f"{self.url}/tika",
                    data=f,
                    headers={'Accept': 'text/plain'},
                    timeout=self.timeout
                )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f'Tika extraction failed: {e}')
            raise
    
    def extract_metadata(self, file_path: str) -> Dict:
        """Extract metadata from document"""
        try:
            with open(file_path, 'rb') as f:
                response = requests.put(
                    f"{self.url}/meta",
                    data=f,
                    headers={'Accept': 'application/json'},
                    timeout=self.timeout
                )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f'Tika metadata extraction failed: {e}')
            raise
    
    def detect_type(self, file_path: str) -> str:
        """Detect file MIME type"""
        try:
            with open(file_path, 'rb') as f:
                response = requests.put(
                    f"{self.url}/detect/stream",
                    data=f,
                    timeout=30
                )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f'Tika type detection failed: {e}')
            raise
    
    def extract_with_metadata(self, file_path: str) -> Dict:
        """Extract both text and metadata"""
        try:
            with open(file_path, 'rb') as f:
                response = requests.put(
                    f"{self.url}/rmeta/text",
                    data=f,
                    headers={'Accept': 'application/json'},
                    timeout=self.timeout
                )
            response.raise_for_status()
            return response.json()[0]
        except requests.exceptions.RequestException as e:
            logger.error(f'Tika extraction failed: {e}')
            raise
    
    def health_check(self) -> bool:
        """Check if Tika is available"""
        try:
            response = requests.get(f"{self.url}/tika", timeout=5)
            return response.status_code == 200
        except:
            return False
```

---

## 5. Integration with Celery

### worker_app/tasks.py

```python
from celery import Task
from .worker import celery_app
from utils.tika_client import TikaClient
import logging

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    max_retries=3,
    time_limit=600,
    soft_time_limit=570
)
def extract_document_content(self, attachment_id: str):
    """Extract text and metadata from attachment"""
    from database.models import Attachment
    from database.session import get_db
    
    db = next(get_db())
    attachment = db.query(Attachment).filter_by(id=attachment_id).first()
    
    if not attachment:
        raise ValueError(f'Attachment not found: {attachment_id}')
    
    try:
        tika = TikaClient()
        
        # Extract text and metadata
        result = tika.extract_with_metadata(attachment.file_path)
        
        # Update attachment record
        attachment.extracted_text = result.get('X-TIKA:content', '')
        attachment.metadata = result
        attachment.processing_status = 'completed'
        
        db.commit()
        
        logger.info(f'Extracted content from {attachment.filename}')
        return {
            'attachment_id': attachment_id,
            'text_length': len(attachment.extracted_text),
            'mime_type': result.get('Content-Type')
        }
    
    except Exception as exc:
        logger.error(f'Content extraction failed: {exc}')
        attachment.processing_status = 'failed'
        db.commit()
        raise self.retry(exc=exc, countdown=60)
```

---

## 6. Supported File Types

### Document Formats

| Format | Extension | OCR Support |
|--------|-----------|-------------|
| PDF | .pdf | ✅ Yes |
| Word | .doc, .docx | ❌ No |
| Excel | .xls, .xlsx | ❌ No |
| PowerPoint | .ppt, .pptx | ❌ No |
| Text | .txt, .csv | ❌ No |
| RTF | .rtf | ❌ No |

### Image Formats

| Format | Extension | OCR Support |
|--------|-----------|-------------|
| JPEG | .jpg, .jpeg | ✅ Yes |
| PNG | .png | ✅ Yes |
| TIFF | .tif, .tiff | ✅ Yes |
| BMP | .bmp | ✅ Yes |
| GIF | .gif | ✅ Yes |

### Email Formats

| Format | Extension | Support |
|--------|-----------|---------|
| Outlook MSG | .msg | ✅ Yes |
| EML | .eml | ✅ Yes |
| MBOX | .mbox | ✅ Yes |

### CAD Formats

| Format | Extension | Support |
|--------|-----------|---------|
| AutoCAD | .dwg | ⚠️ Limited |
| DXF | .dxf | ✅ Yes |

---

## 7. OCR Configuration

### Tesseract Languages

```bash
# Install additional languages
apt-get install tesseract-ocr-fra  # French
apt-get install tesseract-ocr-deu  # German
apt-get install tesseract-ocr-spa  # Spanish
```

### OCR Quality Settings

```xml
<parser class="org.apache.tika.parser.ocr.TesseractOCRParser">
  <params>
    <!-- Language -->
    <param name="language" type="string">eng</param>
    
    <!-- Image preprocessing -->
    <param name="enableImageProcessing" type="bool">true</param>
    <param name="density" type="int">300</param>
    <param name="depth" type="int">8</param>
    
    <!-- OCR engine mode -->
    <param name="oem" type="string">1</param>
    
    <!-- Page segmentation mode -->
    <param name="psm" type="string">3</param>
  </params>
</parser>
```

---

## 8. Performance Optimization

### Batch Processing

```python
from concurrent.futures import ThreadPoolExecutor

def batch_extract(file_paths: list, max_workers: int = 4):
    """Extract text from multiple files in parallel"""
    tika = TikaClient()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(tika.extract_text, file_paths)
    
    return list(results)
```

### Caching

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=1000)
def extract_cached(file_hash: str, file_path: str) -> str:
    """Cache extraction results by file hash"""
    tika = TikaClient()
    return tika.extract_text(file_path)

def extract_with_cache(file_path: str) -> str:
    """Extract with caching"""
    with open(file_path, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    return extract_cached(file_hash, file_path)
```

---

## 9. Error Handling

### Retry Logic

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def extract_with_retry(file_path: str) -> str:
    """Extract with automatic retry"""
    tika = TikaClient()
    return tika.extract_text(file_path)
```

### Timeout Handling

```python
import signal
from contextlib import contextmanager

@contextmanager
def timeout(seconds):
    def timeout_handler(signum, frame):
        raise TimeoutError()
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

def extract_with_timeout(file_path: str, max_seconds: int = 300):
    """Extract with timeout"""
    tika = TikaClient()
    with timeout(max_seconds):
        return tika.extract_text(file_path)
```

---

## 10. Monitoring

### Health Check

```python
from flask import Blueprint, jsonify

health_bp = Blueprint('health', __name__)

@health_bp.route('/health/tika')
def tika_health():
    """Check Tika service health"""
    tika = TikaClient()
    is_healthy = tika.health_check()
    
    return jsonify({
        'service': 'tika',
        'status': 'healthy' if is_healthy else 'unhealthy',
        'url': tika.url
    }), 200 if is_healthy else 503
```

### Metrics

```python
from prometheus_client import Counter, Histogram

tika_requests = Counter(
    'tika_requests_total',
    'Total Tika requests',
    ['status']
)

tika_duration = Histogram(
    'tika_request_duration_seconds',
    'Tika request duration'
)

@tika_duration.time()
def extract_with_metrics(file_path: str):
    """Extract with metrics"""
    try:
        tika = TikaClient()
        result = tika.extract_text(file_path)
        tika_requests.labels(status='success').inc()
        return result
    except Exception as e:
        tika_requests.labels(status='error').inc()
        raise
```

---

## 11. Testing

### Unit Tests

```python
import pytest
from utils.tika_client import TikaClient

@pytest.fixture
def tika_client():
    return TikaClient()

def test_extract_text_pdf(tika_client, tmp_path):
    """Test PDF text extraction"""
    pdf_file = tmp_path / "test.pdf"
    # Create test PDF
    text = tika_client.extract_text(str(pdf_file))
    assert len(text) > 0

def test_extract_metadata(tika_client, tmp_path):
    """Test metadata extraction"""
    doc_file = tmp_path / "test.docx"
    # Create test document
    metadata = tika_client.extract_metadata(str(doc_file))
    assert 'Content-Type' in metadata
```

---

## 12. Troubleshooting

### Common Issues

**Issue: Tika timeout**
```python
# Increase timeout
TIKA_TIMEOUT=600  # 10 minutes
```

**Issue: Out of memory**
```yaml
# Increase container memory
resources:
  limits:
    memory: "8Gi"
```

**Issue: OCR not working**
```bash
# Verify Tesseract installation
docker exec tika tesseract --version
```

**Issue: Slow processing**
```yaml
# Scale horizontally
replicas: 5
```

---

**END OF DOCUMENT**
