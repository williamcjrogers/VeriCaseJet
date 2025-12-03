# AWS Services Configuration Guide

**Version:** 1.0  
**Last Updated:** January 2025  
**Purpose:** Complete configuration reference for all AWS services

---

## 1. S3 Configuration

### Bucket Setup

```bash
# Create bucket
aws s3 mb s3://vericase-docs --region us-east-1

# Enable versioning (forensic integrity)
aws s3api put-bucket-versioning \
  --bucket vericase-docs \
  --versioning-configuration Status=Enabled

# Enable encryption
aws s3api put-bucket-encryption \
  --bucket vericase-docs \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

### Lifecycle Policy

```json
{
  "Rules": [
    {
      "Id": "TransitionToIA",
      "Status": "Enabled",
      "Transitions": [
        {
          "Days": 90,
          "StorageClass": "STANDARD_IA"
        },
        {
          "Days": 180,
          "StorageClass": "GLACIER"
        }
      ]
    }
  ]
}
```

### CORS Configuration

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["https://vericase.com", "http://localhost:8010"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
      "AllowedHeaders": ["*"],
      "MaxAgeSeconds": 3600
    }
  ]
}
```

### Environment Variables

```env
# S3 Configuration
USE_AWS_SERVICES=true
AWS_REGION=us-east-1
MINIO_BUCKET=vericase-docs
AWS_ACCESS_KEY_ID=<use-iam-role>
AWS_SECRET_ACCESS_KEY=<use-iam-role>
```

---

## 2. RDS PostgreSQL Configuration

### Instance Creation

```bash
aws rds create-db-instance \
  --db-instance-identifier vericase-db \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --engine-version 15.4 \
  --master-username vericase \
  --master-user-password <secure-password> \
  --allocated-storage 100 \
  --storage-type gp3 \
  --storage-encrypted \
  --multi-az \
  --backup-retention-period 7 \
  --preferred-backup-window "03:00-04:00" \
  --preferred-maintenance-window "sun:04:00-sun:05:00" \
  --vpc-security-group-ids sg-xxxxx \
  --db-subnet-group-name vericase-subnet-group \
  --publicly-accessible false
```

### Parameter Group

```bash
# Create custom parameter group
aws rds create-db-parameter-group \
  --db-parameter-group-name vericase-postgres15 \
  --db-parameter-group-family postgres15 \
  --description "VeriCase PostgreSQL 15 parameters"

# Modify parameters
aws rds modify-db-parameter-group \
  --db-parameter-group-name vericase-postgres15 \
  --parameters \
    "ParameterName=max_connections,ParameterValue=200,ApplyMethod=immediate" \
    "ParameterName=shared_buffers,ParameterValue=256MB,ApplyMethod=pending-reboot" \
    "ParameterName=work_mem,ParameterValue=16MB,ApplyMethod=immediate"
```

### Connection String

```env
# RDS Configuration
DATABASE_URL=postgresql+psycopg2://vericase:<password>@vericase-db.xxxxx.us-east-1.rds.amazonaws.com:5432/vericase
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
```

### Backup Configuration

```bash
# Enable automated backups
aws rds modify-db-instance \
  --db-instance-identifier vericase-db \
  --backup-retention-period 7 \
  --preferred-backup-window "03:00-04:00" \
  --apply-immediately

# Create manual snapshot
aws rds create-db-snapshot \
  --db-instance-identifier vericase-db \
  --db-snapshot-identifier vericase-manual-$(date +%Y%m%d)
```

---

## 3. OpenSearch Configuration

### Domain Creation

```bash
aws opensearch create-domain \
  --domain-name vericase-search \
  --engine-version OpenSearch_2.11 \
  --cluster-config \
    InstanceType=t3.medium.search,InstanceCount=2,DedicatedMasterEnabled=false \
  --ebs-options \
    EBSEnabled=true,VolumeType=gp3,VolumeSize=100 \
  --access-policies '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::ACCOUNT:role/VeriCaseAppRunnerRole"},
      "Action": "es:*",
      "Resource": "arn:aws:es:us-east-1:ACCOUNT:domain/vericase-search/*"
    }]
  }' \
  --encryption-at-rest-options Enabled=true \
  --node-to-node-encryption-options Enabled=true \
  --domain-endpoint-options \
    EnforceHTTPS=true,TLSSecurityPolicy=Policy-Min-TLS-1-2-2019-07 \
  --vpc-options \
    SubnetIds=subnet-xxxxx,SecurityGroupIds=sg-xxxxx
```

### Index Configuration

```python
# Create index with mappings
index_body = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "email_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"]
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "subject": {"type": "text", "analyzer": "email_analyzer"},
            "from_address": {"type": "keyword"},
            "to_addresses": {"type": "keyword"},
            "date_sent": {"type": "date"},
            "keywords": {"type": "keyword"},
            "stakeholders": {"type": "keyword"},
            "attachment_names": {"type": "text"},
            "content": {"type": "text", "analyzer": "email_analyzer"}
        }
    }
}
```

### Environment Variables

```env
# OpenSearch Configuration
OPENSEARCH_HOST=search-vericase-xxxxx.us-east-1.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_INDEX=documents
OPENSEARCH_TIMEOUT=30
```

### Index Management

```python
# Python client configuration
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3

credentials = boto3.Session().get_credentials()
awsauth = AWS4Auth(
    credentials.access_key,
    credentials.secret_key,
    'us-east-1',
    'es',
    session_token=credentials.token
)

client = OpenSearch(
    hosts=[{'host': os.getenv('OPENSEARCH_HOST'), 'port': 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)
```

---

## 4. ElastiCache Redis Configuration

### Cluster Creation

```bash
aws elasticache create-replication-group \
  --replication-group-id vericase-redis \
  --replication-group-description "VeriCase Celery queue" \
  --engine redis \
  --engine-version 7.0 \
  --cache-node-type cache.t3.medium \
  --num-cache-clusters 2 \
  --automatic-failover-enabled \
  --at-rest-encryption-enabled \
  --transit-encryption-enabled \
  --auth-token <secure-token> \
  --cache-subnet-group-name vericase-subnet-group \
  --security-group-ids sg-xxxxx \
  --preferred-maintenance-window "sun:05:00-sun:06:00" \
  --snapshot-retention-limit 5 \
  --snapshot-window "03:00-04:00"
```

### Parameter Group

```bash
# Create parameter group
aws elasticache create-cache-parameter-group \
  --cache-parameter-group-name vericase-redis7 \
  --cache-parameter-group-family redis7 \
  --description "VeriCase Redis 7 parameters"

# Modify parameters
aws elasticache modify-cache-parameter-group \
  --cache-parameter-group-name vericase-redis7 \
  --parameter-name-values \
    "ParameterName=maxmemory-policy,ParameterValue=allkeys-lru" \
    "ParameterName=timeout,ParameterValue=300"
```

### Environment Variables

```env
# Redis Configuration
REDIS_URL=rediss://:auth-token@vericase-redis.xxxxx.cache.amazonaws.com:6379/0
CELERY_BROKER_URL=${REDIS_URL}
CELERY_RESULT_BACKEND=${REDIS_URL}
CELERY_BROKER_USE_SSL=true
CELERY_REDIS_BACKEND_USE_SSL=true
```

### Celery Configuration

```python
# celery_config.py
broker_url = os.getenv('CELERY_BROKER_URL')
result_backend = os.getenv('CELERY_RESULT_BACKEND')
broker_use_ssl = {'ssl_cert_reqs': 'CERT_REQUIRED'}
redis_backend_use_ssl = {'ssl_cert_reqs': 'CERT_REQUIRED'}
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True
task_track_started = True
task_time_limit = 14400  # 4 hours
task_soft_time_limit = 13800  # 3.8 hours
worker_prefetch_multiplier = 1
worker_max_tasks_per_child = 50
```

---

## 5. App Runner Configuration

### Service Creation

```bash
aws apprunner create-service \
  --service-name vericase-api \
  --source-configuration '{
    "ImageRepository": {
      "ImageIdentifier": "ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/vericase:latest",
      "ImageRepositoryType": "ECR",
      "ImageConfiguration": {
        "Port": "8000",
        "RuntimeEnvironmentVariables": {
          "DATABASE_URL": "postgresql+psycopg2://...",
          "REDIS_URL": "rediss://...",
          "OPENSEARCH_HOST": "search-vericase-xxxxx..."
        }
      }
    },
    "AutoDeploymentsEnabled": true
  }' \
  --instance-configuration \
    Cpu=2048,Memory=4096 \
  --health-check-configuration \
    Protocol=HTTP,Path=/health,Interval=10,Timeout=5,HealthyThreshold=2,UnhealthyThreshold=3 \
  --auto-scaling-configuration-arn arn:aws:apprunner:us-east-1:ACCOUNT:autoscalingconfiguration/vericase-scaling
```

### Auto-Scaling Configuration

```bash
aws apprunner create-auto-scaling-configuration \
  --auto-scaling-configuration-name vericase-scaling \
  --max-concurrency 100 \
  --min-size 1 \
  --max-size 10
```

### Environment Variables

```yaml
# apprunner.yaml
version: 1.0
runtime: python311
build:
  commands:
    pre-build:
      - pip install --upgrade pip
    build:
      - pip install -r requirements.txt
    post-build:
      - python api/apply_migrations.py
run:
  runtime-version: 3.11
  command: uvicorn api.app.main:app --host 0.0.0.0 --port 8000
  network:
    port: 8000
    env:
      - name: DATABASE_URL
        value: postgresql+psycopg2://...
      - name: REDIS_URL
        value: rediss://...
      - name: OPENSEARCH_HOST
        value: search-vericase-xxxxx...
```

### Custom Domain

```bash
# Associate custom domain
aws apprunner associate-custom-domain \
  --service-arn arn:aws:apprunner:us-east-1:ACCOUNT:service/vericase-api/xxxxx \
  --domain-name api.vericase.com \
  --enable-www-subdomain false
```

---

## 6. Celery Workers Configuration

### Worker Deployment (ECS Fargate)

```json
{
  "family": "vericase-worker",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "2048",
  "memory": "8192",
  "containerDefinitions": [
    {
      "name": "worker",
      "image": "ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/vericase-worker:latest",
      "essential": true,
      "command": ["celery", "-A", "worker_app.worker", "worker", "--loglevel=info", "--concurrency=4"],
      "environment": [
        {"name": "DATABASE_URL", "value": "postgresql+psycopg2://..."},
        {"name": "REDIS_URL", "value": "rediss://..."},
        {"name": "OPENSEARCH_HOST", "value": "search-vericase-xxxxx..."},
        {"name": "MINIO_BUCKET", "value": "vericase-docs"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/vericase-worker",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "worker"
        }
      }
    }
  ]
}
```

### Worker Configuration

```python
# worker_app/config.py
import os

class WorkerConfig:
    # Celery
    broker_url = os.getenv('CELERY_BROKER_URL')
    result_backend = os.getenv('CELERY_RESULT_BACKEND')
    
    # Database
    database_url = os.getenv('DATABASE_URL')
    
    # S3
    s3_bucket = os.getenv('MINIO_BUCKET')
    aws_region = os.getenv('AWS_REGION', 'us-east-1')
    
    # OpenSearch
    opensearch_host = os.getenv('OPENSEARCH_HOST')
    opensearch_port = int(os.getenv('OPENSEARCH_PORT', 443))
    opensearch_index = os.getenv('OPENSEARCH_INDEX', 'documents')
    
    # Tika
    tika_url = os.getenv('TIKA_URL', 'http://tika:9998')
    
    # Processing
    max_pst_size = 50 * 1024 * 1024 * 1024  # 50GB
    chunk_size = 10 * 1024 * 1024  # 10MB
    max_retries = 3
    retry_delay = 60  # seconds
```

### Task Definitions

```python
# worker_app/tasks.py
from celery import Task
from .worker import celery_app

@celery_app.task(
    bind=True,
    max_retries=3,
    time_limit=14400,
    soft_time_limit=13800
)
def process_pst_file(self, pst_file_id: str):
    """Process PST file and extract emails/attachments"""
    try:
        # Processing logic
        pass
    except Exception as exc:
        self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def extract_attachment(self, attachment_id: str):
    """Extract and index attachment"""
    pass

@celery_app.task(bind=True, max_retries=3)
def index_to_opensearch(self, document_id: str):
    """Index document to OpenSearch"""
    pass
```

---

## 7. Apache Tika Configuration

### Kubernetes Deployment

```yaml
# k8s/tika-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tika
  namespace: vericase
spec:
  replicas: 2
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
          value: "/tika-config.xml"
        livenessProbe:
          httpGet:
            path: /tika
            port: 9998
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /tika
            port: 9998
          initialDelaySeconds: 10
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: tika
  namespace: vericase
spec:
  selector:
    app: tika
  ports:
  - port: 9998
    targetPort: 9998
  type: ClusterIP
```

### Tika Configuration

```xml
<!-- tika-config.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<properties>
  <parsers>
    <parser class="org.apache.tika.parser.DefaultParser"/>
    <parser class="org.apache.tika.parser.pdf.PDFParser">
      <params>
        <param name="extractInlineImages" type="bool">true</param>
        <param name="ocrStrategy" type="string">auto</param>
      </params>
    </parser>
  </parsers>
  <service-loader initializableProblemHandler="ignore"/>
</properties>
```

### Environment Variables

```env
# Tika Configuration
TIKA_URL=http://tika.vericase.svc.cluster.local:9998
TIKA_TIMEOUT=300
TIKA_MAX_FILE_SIZE=104857600  # 100MB
TIKA_OCR_ENABLED=true
```

### Python Client

```python
# utils/tika_client.py
import requests
import os

class TikaClient:
    def __init__(self):
        self.url = os.getenv('TIKA_URL')
        self.timeout = int(os.getenv('TIKA_TIMEOUT', 300))
    
    def extract_text(self, file_path: str) -> str:
        """Extract text from document"""
        with open(file_path, 'rb') as f:
            response = requests.put(
                f"{self.url}/tika",
                data=f,
                headers={'Accept': 'text/plain'},
                timeout=self.timeout
            )
        return response.text
    
    def extract_metadata(self, file_path: str) -> dict:
        """Extract metadata from document"""
        with open(file_path, 'rb') as f:
            response = requests.put(
                f"{self.url}/meta",
                data=f,
                headers={'Accept': 'application/json'},
                timeout=self.timeout
            )
        return response.json()
```

---

## 8. IAM Roles & Policies

### App Runner Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::vericase-docs",
        "arn:aws:s3:::vericase-docs/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "es:ESHttpGet",
        "es:ESHttpPost",
        "es:ESHttpPut",
        "es:ESHttpDelete"
      ],
      "Resource": "arn:aws:es:us-east-1:ACCOUNT:domain/vericase-search/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:vericase/*"
    }
  ]
}
```

### Worker Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::vericase-docs",
        "arn:aws:s3:::vericase-docs/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "es:ESHttpPost",
        "es:ESHttpPut"
      ],
      "Resource": "arn:aws:es:us-east-1:ACCOUNT:domain/vericase-search/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:ACCOUNT:log-group:/ecs/vericase-worker:*"
    }
  ]
}
```

---

## 9. Monitoring & Logging

### CloudWatch Log Groups

```bash
# Create log groups
aws logs create-log-group --log-group-name /apprunner/vericase-api
aws logs create-log-group --log-group-name /ecs/vericase-worker
aws logs create-log-group --log-group-name /aws/rds/instance/vericase-db/postgresql

# Set retention
aws logs put-retention-policy \
  --log-group-name /apprunner/vericase-api \
  --retention-in-days 30
```

### CloudWatch Alarms

```bash
# High CPU alarm
aws cloudwatch put-metric-alarm \
  --alarm-name vericase-api-high-cpu \
  --alarm-description "API CPU > 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/AppRunner \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2

# Database connections alarm
aws cloudwatch put-metric-alarm \
  --alarm-name vericase-db-connections \
  --alarm-description "DB connections > 180" \
  --metric-name DatabaseConnections \
  --namespace AWS/RDS \
  --statistic Average \
  --period 300 \
  --threshold 180 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2
```

---

## 10. Deployment Checklist

### Pre-Deployment

- [ ] Create VPC and subnets
- [ ] Configure security groups
- [ ] Create IAM roles and policies
- [ ] Set up Secrets Manager
- [ ] Create S3 bucket
- [ ] Deploy RDS instance
- [ ] Deploy ElastiCache cluster
- [ ] Deploy OpenSearch domain
- [ ] Deploy Tika service

### Deployment

- [ ] Build and push Docker images
- [ ] Deploy App Runner service
- [ ] Deploy ECS worker tasks
- [ ] Run database migrations
- [ ] Configure auto-scaling
- [ ] Set up custom domain
- [ ] Configure SSL certificates

### Post-Deployment

- [ ] Verify all services healthy
- [ ] Test PST upload
- [ ] Test search functionality
- [ ] Configure CloudWatch alarms
- [ ] Set up log retention
- [ ] Enable AWS Backup
- [ ] Document endpoints

---

## 11. Cost Optimization

### Estimated Monthly Costs

| Service | Configuration | Monthly Cost |
|---------|--------------|--------------|
| App Runner | 2 vCPU, 4GB RAM | $50-100 |
| RDS PostgreSQL | db.t3.medium, Multi-AZ | $150-200 |
| ElastiCache Redis | cache.t3.medium x2 | $100-150 |
| OpenSearch | t3.medium.search x2 | $150-200 |
| S3 | 1TB storage | $25-50 |
| ECS Fargate | 2 vCPU, 8GB RAM x2 | $100-150 |
| Data Transfer | 500GB/month | $50-75 |
| **TOTAL** | | **$625-925/month** |

### Optimization Tips

1. Use Reserved Instances for RDS (save 40%)
2. Enable S3 Intelligent-Tiering
3. Use Spot Instances for workers (save 70%)
4. Configure auto-scaling properly
5. Set up lifecycle policies
6. Monitor and right-size instances

---

**END OF DOCUMENT**
