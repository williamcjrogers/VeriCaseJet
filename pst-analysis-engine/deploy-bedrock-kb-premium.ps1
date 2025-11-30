#!/usr/bin/env pwsh
# VeriCase Premium Bedrock Knowledge Base Deployment
# Deploys: OpenSearch Serverless + Bedrock KB + Vector Embeddings
# Cost: ~£200/month

$ErrorActionPreference = "Stop"

Write-Host "=== VeriCase Premium Bedrock Knowledge Base Deployment ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚠️  WARNING: This will incur ~£200/month in AWS costs" -ForegroundColor Yellow
Write-Host ""

# Configuration
$REGION = "us-east-1"
$ACCOUNT_ID = "526015377510"
$PROJECT = "vericase"
$KB_BUCKET = "vericase-knowledge-base-526015377510"
$COLLECTION_NAME = "vericase-kb"
$KB_NAME = "VeriCase-Premium-KB"

Write-Host "Region: $REGION" -ForegroundColor Yellow
Write-Host "Account: $ACCOUNT_ID" -ForegroundColor Yellow
Write-Host ""

# Step 1: Create OpenSearch Serverless Collection
Write-Host "[1/7] Creating OpenSearch Serverless Collection..." -ForegroundColor Green

# Create encryption policy
$encryptionPolicy = @"
{
  "Rules": [{
    "ResourceType": "collection",
    "Resource": ["collection/$COLLECTION_NAME"]
  }],
  "AWSOwnedKey": true
}
"@ | ConvertTo-Json -Compress

aws opensearchserverless create-security-policy `
    --name "${COLLECTION_NAME}-encryption" `
    --type encryption `
    --policy $encryptionPolicy `
    --region $REGION 2>$null

Write-Host "  ✓ Created encryption policy" -ForegroundColor Green

# Create network policy (public access for now)
$networkPolicy = @"
[{
  "Rules": [{
    "ResourceType": "collection",
    "Resource": ["collection/$COLLECTION_NAME"]
  }],
  "AllowFromPublic": true
}]
"@

aws opensearchserverless create-security-policy `
    --name "${COLLECTION_NAME}-network" `
    --type network `
    --policy $networkPolicy `
    --region $REGION 2>$null

Write-Host "  ✓ Created network policy" -ForegroundColor Green

# Create data access policy
$dataPolicy = @"
[{
  "Rules": [{
    "ResourceType": "collection",
    "Resource": ["collection/$COLLECTION_NAME"],
    "Permission": ["aoss:*"]
  }, {
    "ResourceType": "index",
    "Resource": ["index/$COLLECTION_NAME/*"],
    "Permission": ["aoss:*"]
  }],
  "Principal": [
    "arn:aws:iam::${ACCOUNT_ID}:role/VeriCaseBedrockKBRole",
    "arn:aws:sts::${ACCOUNT_ID}:assumed-role/Admin/*"
  ]
}]
"@

aws opensearchserverless create-access-policy `
    --name "${COLLECTION_NAME}-access" `
    --type data `
    --policy $dataPolicy `
    --region $REGION 2>$null

Write-Host "  ✓ Created data access policy" -ForegroundColor Green

# Create collection
Write-Host "  ⏳ Creating collection (this takes 5-10 minutes)..." -ForegroundColor Yellow

$collectionResult = aws opensearchserverless create-collection `
    --name $COLLECTION_NAME `
    --type VECTORSEARCH `
    --description "VeriCase Legal Evidence Vector Store" `
    --region $REGION | ConvertFrom-Json

$COLLECTION_ID = $collectionResult.createCollectionDetail.id
Write-Host "  ✓ Collection created: $COLLECTION_ID" -ForegroundColor Green

# Wait for collection to be active
Write-Host "  ⏳ Waiting for collection to become active..." -ForegroundColor Yellow
$maxWait = 600 # 10 minutes
$waited = 0
$status = "CREATING"

while ($status -ne "ACTIVE" -and $waited -lt $maxWait) {
    Start-Sleep -Seconds 10
    $waited += 10
    
    $collectionStatus = aws opensearchserverless batch-get-collection `
        --ids $COLLECTION_ID `
        --region $REGION | ConvertFrom-Json
    
    $status = $collectionStatus.collectionDetails[0].status
    Write-Host "    Status: $status (${waited}s elapsed)" -ForegroundColor Yellow
}

if ($status -ne "ACTIVE") {
    Write-Host "  ⚠️  Collection creation timeout. Check AWS console." -ForegroundColor Red
    exit 1
}

$COLLECTION_ENDPOINT = $collectionStatus.collectionDetails[0].collectionEndpoint
Write-Host "  ✓ Collection active: $COLLECTION_ENDPOINT" -ForegroundColor Green

# Step 2: Create vector index in OpenSearch
Write-Host ""
Write-Host "[2/7] Creating vector index..." -ForegroundColor Green

$indexMapping = @"
{
  "settings": {
    "index.knn": true
  },
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 1536,
        "method": {
          "name": "hnsw",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16
          }
        }
      },
      "text": {
        "type": "text"
      },
      "metadata": {
        "type": "object"
      }
    }
  }
}
"@

$indexMapping | Out-File -FilePath "index-mapping.json" -Encoding utf8

# Create index using curl (AWS CLI doesn't support OpenSearch index creation)
$curlCommand = "curl -X PUT `"$COLLECTION_ENDPOINT/vericase-index`" -H `"Content-Type: application/json`" -d @index-mapping.json --aws-sigv4 `"aws:amz:${REGION}:aoss`""
Invoke-Expression $curlCommand

Write-Host "  ✓ Created vector index: vericase-index" -ForegroundColor Green

# Step 3: Ensure IAM role exists
Write-Host ""
Write-Host "[3/7] Verifying IAM roles..." -ForegroundColor Green

$BEDROCK_ROLE_NAME = "VeriCaseBedrockKBRole"
$roleExists = aws iam get-role --role-name $BEDROCK_ROLE_NAME 2>$null

if (-not $roleExists) {
    Write-Host "  ⚠️  Bedrock role not found. Run deploy-aws-ai-services.ps1 first" -ForegroundColor Red
    exit 1
}

$BEDROCK_ROLE_ARN = "arn:aws:iam::${ACCOUNT_ID}:role/$BEDROCK_ROLE_NAME"

# Add OpenSearch permissions to role
$aossPolicy = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "aoss:APIAccessAll"
    ],
    "Resource": "arn:aws:aoss:${REGION}:${ACCOUNT_ID}:collection/$COLLECTION_ID"
  }]
}
"@

$aossPolicy | Out-File -FilePath "aoss-policy.json" -Encoding utf8

aws iam put-role-policy `
    --role-name $BEDROCK_ROLE_NAME `
    --policy-name OpenSearchServerlessAccess `
    --policy-document file://aoss-policy.json `
    --region $REGION

Write-Host "  ✓ Added OpenSearch permissions to Bedrock role" -ForegroundColor Green

# Step 4: Create Bedrock Knowledge Base
Write-Host ""
Write-Host "[4/7] Creating Bedrock Knowledge Base..." -ForegroundColor Green

$kbConfig = @"
{
  "name": "$KB_NAME",
  "description": "VeriCase Premium Legal Evidence Knowledge Base with Vector Search",
  "roleArn": "$BEDROCK_ROLE_ARN",
  "knowledgeBaseConfiguration": {
    "type": "VECTOR",
    "vectorKnowledgeBaseConfiguration": {
      "embeddingModelArn": "arn:aws:bedrock:${REGION}::foundation-model/amazon.titan-embed-text-v1"
    }
  },
  "storageConfiguration": {
    "type": "OPENSEARCH_SERVERLESS",
    "opensearchServerlessConfiguration": {
      "collectionArn": "arn:aws:aoss:${REGION}:${ACCOUNT_ID}:collection/$COLLECTION_ID",
      "vectorIndexName": "vericase-index",
      "fieldMapping": {
        "vectorField": "embedding",
        "textField": "text",
        "metadataField": "metadata"
      }
    }
  }
}
"@

$kbConfig | Out-File -FilePath "kb-config.json" -Encoding utf8

$kbResult = aws bedrock-agent create-knowledge-base `
    --cli-input-json file://kb-config.json `
    --region $REGION | ConvertFrom-Json

$KB_ID = $kbResult.knowledgeBase.knowledgeBaseId
Write-Host "  ✓ Created Knowledge Base: $KB_ID" -ForegroundColor Green

# Step 5: Create S3 Data Source
Write-Host ""
Write-Host "[5/7] Creating S3 Data Source..." -ForegroundColor Green

$dsConfig = @"
{
  "knowledgeBaseId": "$KB_ID",
  "name": "VeriCase-S3-DataSource",
  "description": "S3 data source for VeriCase legal documents",
  "dataSourceConfiguration": {
    "type": "S3",
    "s3Configuration": {
      "bucketArn": "arn:aws:s3:::$KB_BUCKET",
      "inclusionPrefixes": ["documents/", "evidence/", "pst-exports/"]
    }
  },
  "vectorIngestionConfiguration": {
    "chunkingConfiguration": {
      "chunkingStrategy": "FIXED_SIZE",
      "fixedSizeChunkingConfiguration": {
        "maxTokens": 512,
        "overlapPercentage": 20
      }
    }
  }
}
"@

$dsConfig | Out-File -FilePath "ds-config.json" -Encoding utf8

$dsResult = aws bedrock-agent create-data-source `
    --cli-input-json file://ds-config.json `
    --region $REGION | ConvertFrom-Json

$DS_ID = $dsResult.dataSource.dataSourceId
Write-Host "  ✓ Created Data Source: $DS_ID" -ForegroundColor Green

# Step 6: Start initial ingestion
Write-Host ""
Write-Host "[6/7] Starting initial data ingestion..." -ForegroundColor Green

# Upload sample document to trigger ingestion
$sampleDoc = @"
VeriCase Legal Evidence Management System

This is a sample document to initialize the knowledge base.
The system will index all documents uploaded to the S3 bucket.

Key features:
- Semantic search across all legal documents
- AI-powered evidence classification
- Natural language query interface
- Vector similarity matching
"@

$sampleDoc | Out-File -FilePath "sample-doc.txt" -Encoding utf8

aws s3 cp sample-doc.txt "s3://$KB_BUCKET/documents/sample-doc.txt" --region $REGION
Write-Host "  ✓ Uploaded sample document" -ForegroundColor Green

# Start ingestion job
$ingestionResult = aws bedrock-agent start-ingestion-job `
    --knowledge-base-id $KB_ID `
    --data-source-id $DS_ID `
    --region $REGION | ConvertFrom-Json

$INGESTION_JOB_ID = $ingestionResult.ingestionJob.ingestionJobId
Write-Host "  ✓ Started ingestion job: $INGESTION_JOB_ID" -ForegroundColor Green
Write-Host "  ⏳ Ingestion will complete in background (5-10 minutes)" -ForegroundColor Yellow

# Step 7: Update configuration
Write-Host ""
Write-Host "[7/7] Updating configuration..." -ForegroundColor Green

$envContent = @"
# AWS Premium Bedrock Knowledge Base - DEPLOYED $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
USE_AWS_SERVICES=true
AWS_REGION=$REGION
AWS_ACCOUNT_ID=$ACCOUNT_ID

# S3 Buckets
S3_BUCKET=vericase-documents-$ACCOUNT_ID
KNOWLEDGE_BASE_BUCKET=$KB_BUCKET

# Premium Bedrock Knowledge Base
BEDROCK_KB_ID=$KB_ID
BEDROCK_DS_ID=$DS_ID
BEDROCK_COLLECTION_ID=$COLLECTION_ID
BEDROCK_COLLECTION_ENDPOINT=$COLLECTION_ENDPOINT

# Lambda Functions
TEXTRACT_PROCESSOR_FUNCTION=arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:vericase-evidence-processor

# AI Features (Premium)
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
ENABLE_SEMANTIC_SEARCH=true
ENABLE_VECTOR_SIMILARITY=true

# EventBridge
EVENT_BUS_NAME=vericase-events

# Existing Redis
REDIS_ENDPOINT=clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379
"@

$envContent | Out-File -FilePath ".env.bedrock-premium" -Encoding utf8
Write-Host "  ✓ Created .env.bedrock-premium" -ForegroundColor Green

# Cleanup
Remove-Item -Path "index-mapping.json", "aoss-policy.json", "kb-config.json", "ds-config.json", "sample-doc.txt" -ErrorAction SilentlyContinue

# Summary
Write-Host ""
Write-Host "=== Premium Deployment Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Resources Created:" -ForegroundColor Yellow
Write-Host "  • OpenSearch Serverless Collection: $COLLECTION_NAME"
Write-Host "  • Collection Endpoint: $COLLECTION_ENDPOINT"
Write-Host "  • Bedrock Knowledge Base: $KB_ID"
Write-Host "  • S3 Data Source: $DS_ID"
Write-Host "  • Vector Index: vericase-index"
Write-Host ""
Write-Host "Estimated Monthly Cost:" -ForegroundColor Yellow
Write-Host "  • OpenSearch Serverless: £150-200/month (4 OCUs minimum)"
Write-Host "  • Bedrock Embeddings: £10/month"
Write-Host "  • Bedrock Queries: £5-20/month"
Write-Host "  • Total: ~£165-230/month" -ForegroundColor Red
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Copy .env.bedrock-premium to .env"
Write-Host "  2. Upload documents to s3://$KB_BUCKET/documents/"
Write-Host "  3. Monitor ingestion: aws bedrock-agent get-ingestion-job --knowledge-base-id $KB_ID --data-source-id $DS_ID --ingestion-job-id $INGESTION_JOB_ID"
Write-Host "  4. Test queries via Bedrock console or API"
Write-Host ""
Write-Host "API Integration:" -ForegroundColor Yellow
Write-Host "  Use boto3 bedrock-agent-runtime.retrieve() with KB ID: $KB_ID"
Write-Host ""
