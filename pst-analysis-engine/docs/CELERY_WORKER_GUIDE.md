# Celery Worker Configuration Guide

**Version:** 1.0  
**Purpose:** Complete Celery worker setup and task management

---

## 1. Worker Architecture

```
Redis (ElastiCache) ← Celery Broker
    ↓
Celery Workers (ECS Fargate)
    ↓
Tasks: PST Processing, OCR, Indexing
    ↓
Results → PostgreSQL + OpenSearch + S3
```

---

## 2. Worker Configuration

### worker_app/config.py

```python
import os
from kombu import Queue, Exchange

class CeleryConfig:
    # Broker
    broker_url = os.getenv('CELERY_BROKER_URL')
    result_backend = os.getenv('CELERY_RESULT_BACKEND')
    
    # SSL
    broker_use_ssl = {'ssl_cert_reqs': 'CERT_REQUIRED'}
    redis_backend_use_ssl = {'ssl_cert_reqs': 'CERT_REQUIRED'}
    
    # Serialization
    task_serializer = 'json'
    result_serializer = 'json'
    accept_content = ['json']
    
    # Timezone
    timezone = 'UTC'
    enable_utc = True
    
    # Task execution
    task_track_started = True
    task_time_limit = 14400  # 4 hours
    task_soft_time_limit = 13800  # 3.8 hours
    task_acks_late = True
    task_reject_on_worker_lost = True
    
    # Worker
    worker_prefetch_multiplier = 1
    worker_max_tasks_per_child = 50
    worker_disable_rate_limits = False
    
    # Queues
    task_default_queue = 'default'
    task_queues = (
        Queue('default', Exchange('default'), routing_key='default'),
        Queue('pst_processing', Exchange('pst'), routing_key='pst.process'),
        Queue('ocr', Exchange('ocr'), routing_key='ocr.extract'),
        Queue('indexing', Exchange('index'), routing_key='index.document'),
    )
    
    # Routes
    task_routes = {
        'worker_app.tasks.process_pst_file': {'queue': 'pst_processing'},
        'worker_app.tasks.extract_attachment': {'queue': 'ocr'},
        'worker_app.tasks.index_to_opensearch': {'queue': 'indexing'},
    }
```

---

## 3. Worker Initialization

### worker_app/worker.py

```python
from celery import Celery
from .config import CeleryConfig

celery_app = Celery('vericase')
celery_app.config_from_object(CeleryConfig)

# Auto-discover tasks
celery_app.autodiscover_tasks(['worker_app'])

@celery_app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
```

---

## 4. Task Definitions

### worker_app/tasks.py

```python
from celery import Task
from celery.utils.log import get_task_logger
from .worker import celery_app
import os

logger = get_task_logger(__name__)

class CallbackTask(Task):
    """Base task with callbacks"""
    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f'Task {task_id} succeeded')
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f'Task {task_id} failed: {exc}')
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(f'Task {task_id} retrying: {exc}')

@celery_app.task(
    base=CallbackTask,
    bind=True,
    max_retries=3,
    time_limit=14400,
    soft_time_limit=13800,
    queue='pst_processing'
)
def process_pst_file(self, pst_file_id: str):
    """Process PST file: extract emails and attachments"""
    from src.ingestion.pst_ingestion_engine import PSTIngestionEngine
    
    try:
        logger.info(f'Processing PST file: {pst_file_id}')
        engine = PSTIngestionEngine()
        result = engine.process_pst(pst_file_id)
        logger.info(f'PST processing complete: {result}')
        return result
    except Exception as exc:
        logger.error(f'PST processing failed: {exc}')
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(
    base=CallbackTask,
    bind=True,
    max_retries=3,
    time_limit=600,
    queue='ocr'
)
def extract_attachment(self, attachment_id: str):
    """Extract text from attachment using Tika"""
    from utils.tika_client import TikaClient
    
    try:
        logger.info(f'Extracting attachment: {attachment_id}')
        tika = TikaClient()
        result = tika.extract_text(attachment_id)
        logger.info(f'Extraction complete: {attachment_id}')
        return result
    except Exception as exc:
        logger.error(f'Extraction failed: {exc}')
        raise self.retry(exc=exc, countdown=30)

@celery_app.task(
    base=CallbackTask,
    bind=True,
    max_retries=3,
    time_limit=300,
    queue='indexing'
)
def index_to_opensearch(self, document_id: str):
    """Index document to OpenSearch"""
    from utils.opensearch_client import OpenSearchClient
    
    try:
        logger.info(f'Indexing document: {document_id}')
        client = OpenSearchClient()
        result = client.index_document(document_id)
        logger.info(f'Indexing complete: {document_id}')
        return result
    except Exception as exc:
        logger.error(f'Indexing failed: {exc}')
        raise self.retry(exc=exc, countdown=30)

@celery_app.task(bind=True, queue='default')
def cleanup_temp_files(self, older_than_hours: int = 24):
    """Clean up temporary files"""
    import shutil
    from datetime import datetime, timedelta
    
    temp_dir = '/tmp/vericase'
    cutoff = datetime.now() - timedelta(hours=older_than_hours)
    
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            path = os.path.join(root, file)
            if os.path.getmtime(path) < cutoff.timestamp():
                os.remove(path)
                logger.info(f'Removed temp file: {path}')
```

---

## 5. Task Chains & Groups

### Chaining Tasks

```python
from celery import chain, group, chord

# Sequential processing
result = chain(
    process_pst_file.s(pst_id),
    extract_attachment.s(),
    index_to_opensearch.s()
).apply_async()

# Parallel processing
result = group(
    extract_attachment.s(att_id_1),
    extract_attachment.s(att_id_2),
    extract_attachment.s(att_id_3)
).apply_async()

# Chord: parallel then callback
result = chord(
    group(extract_attachment.s(att_id) for att_id in attachment_ids)
)(index_to_opensearch.s())
```

---

## 6. Monitoring & Management

### Flower (Web UI)

```bash
# Install Flower
pip install flower

# Start Flower
celery -A worker_app.worker flower --port=5555

# Access: http://localhost:5555
```

### CLI Commands

```bash
# Inspect active tasks
celery -A worker_app.worker inspect active

# Inspect scheduled tasks
celery -A worker_app.worker inspect scheduled

# Inspect registered tasks
celery -A worker_app.worker inspect registered

# Purge all tasks
celery -A worker_app.worker purge

# Revoke task
celery -A worker_app.worker revoke <task-id>

# Worker stats
celery -A worker_app.worker inspect stats
```

---

## 7. Deployment

### Docker Compose

```yaml
worker:
  build:
    context: .
    dockerfile: worker/Dockerfile
  command: celery -A worker_app.worker worker --loglevel=info --concurrency=4
  environment:
    - DATABASE_URL=${DATABASE_URL}
    - REDIS_URL=${REDIS_URL}
    - OPENSEARCH_HOST=${OPENSEARCH_HOST}
  depends_on:
    - redis
    - postgres
  volumes:
    - ./uploads:/app/uploads
    - ./evidence:/app/evidence
```

### ECS Task Definition

```json
{
  "family": "vericase-worker",
  "containerDefinitions": [
    {
      "name": "worker",
      "image": "vericase-worker:latest",
      "command": [
        "celery",
        "-A",
        "worker_app.worker",
        "worker",
        "--loglevel=info",
        "--concurrency=4"
      ],
      "memory": 8192,
      "cpu": 2048,
      "essential": true
    }
  ]
}
```

---

## 8. Performance Tuning

### Concurrency

```bash
# CPU-bound tasks
celery -A worker_app.worker worker --concurrency=4

# I/O-bound tasks
celery -A worker_app.worker worker --concurrency=20

# Auto-scale
celery -A worker_app.worker worker --autoscale=10,3
```

### Prefetch

```python
# Low prefetch for long tasks
worker_prefetch_multiplier = 1

# Higher prefetch for short tasks
worker_prefetch_multiplier = 4
```

---

## 9. Error Handling

### Retry Logic

```python
@celery_app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def robust_task(self, data):
    # Task logic
    pass
```

### Dead Letter Queue

```python
from kombu import Queue

task_queues = (
    Queue('default', routing_key='default'),
    Queue('failed', routing_key='failed'),
)

@celery_app.task(bind=True)
def handle_failed_task(self, task_id, exc, traceback):
    logger.error(f'Task {task_id} failed permanently: {exc}')
    # Send to monitoring/alerting
```

---

## 10. Testing

### Unit Tests

```python
import pytest
from worker_app.tasks import process_pst_file

@pytest.fixture
def celery_config():
    return {
        'broker_url': 'memory://',
        'result_backend': 'cache+memory://'
    }

def test_process_pst_file(celery_worker):
    result = process_pst_file.delay('test-pst-id')
    assert result.get(timeout=10) is not None
```

---

**END OF DOCUMENT**
