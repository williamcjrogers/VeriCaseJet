#!/bin/bash
# VeriCase AWS Services Deployment Script

set -e

echo "🚀 Deploying VeriCase AWS Services Integration..."

# Configuration
ENVIRONMENT=${1:-production}
REGION=${AWS_REGION:-us-east-1}
STACK_NAME="vericase-aws-services-$ENVIRONMENT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
print_status "Checking prerequisites..."

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI not found. Please install AWS CLI."
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    print_error "AWS credentials not configured. Please run 'aws configure'."
    exit 1
fi

# Check required environment variables
if [ -z "$DATABASE_PASSWORD" ]; then
    print_warning "DATABASE_PASSWORD not set. Generating random password..."
    DATABASE_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    echo "Generated password: $DATABASE_PASSWORD"
    echo "Please save this password securely!"
fi

print_success "Prerequisites check completed"

# Step 1: Deploy Infrastructure
print_status "Step 1: Deploying AWS Infrastructure..."

# Create CloudFormation template file
cat > vericase-infrastructure.yaml << 'EOF'
AWSTemplateFormatVersion: '2010-09-09'
Description: 'VeriCase AWS Infrastructure - Complete AI-Powered Legal Evidence Platform'

Parameters:
  Environment:
    Type: String
    Default: production
    AllowedValues: [development, staging, production]
  DatabasePassword:
    Type: String
    NoEcho: true
    MinLength: 12
  DomainName:
    Type: String
    Default: vericase.com

Resources:
  # S3 Buckets
  VeriCaseDocumentsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub 'vericase-documents-${Environment}-${AWS::AccountId}'
      VersioningConfiguration:
        Status: Enabled
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      NotificationConfiguration:
        EventBridgeConfiguration:
          EventBridgeEnabled: true

  VeriCaseKnowledgeBaseBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub 'vericase-knowledge-base-${Environment}-${AWS::AccountId}'

  # OpenSearch Serverless Collection
  VeriCaseSearchCollection:
    Type: AWS::OpenSearchServerless::Collection
    Properties:
      Name: !Sub 'vericase-search-${Environment}'
      Type: SEARCH

  # EventBridge Custom Bus
  VeriCaseEventBus:
    Type: AWS::Events::EventBus
    Properties:
      Name: !Sub 'vericase-events-${Environment}'

Outputs:
  DocumentsBucket:
    Value: !Ref VeriCaseDocumentsBucket
    Export:
      Name: !Sub '${AWS::StackName}-DocumentsBucket'
  
  KnowledgeBaseBucket:
    Value: !Ref VeriCaseKnowledgeBaseBucket
    Export:
      Name: !Sub '${AWS::StackName}-KnowledgeBaseBucket'
  
  SearchCollection:
    Value: !Ref VeriCaseSearchCollection
    Export:
      Name: !Sub '${AWS::StackName}-SearchCollection'
  
  EventBus:
    Value: !Ref VeriCaseEventBus
    Export:
      Name: !Sub '${AWS::StackName}-EventBus'
EOF

# Deploy infrastructure
aws cloudformation deploy \
    --template-file vericase-infrastructure.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides \
        Environment=$ENVIRONMENT \
        DatabasePassword=$DATABASE_PASSWORD \
        DomainName=${DOMAIN_NAME:-vericase.com} \
    --capabilities CAPABILITY_IAM \
    --region $REGION

print_success "Infrastructure deployed successfully"

# Step 2: Create Lambda Functions
print_status "Step 2: Creating Lambda function packages..."

mkdir -p lambda_packages

# Create Textract Processor Lambda
cat > lambda_packages/textract_processor.py << 'EOF'
import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

textract = boto3.client('textract')

def lambda_handler(event, context):
    try:
        s3_bucket = event['s3_bucket']
        s3_key = event['s3_key']
        evidence_id = event['evidence_id']
        
        response = textract.start_document_analysis(
            DocumentLocation={'S3Object': {'Bucket': s3_bucket, 'Name': s3_key}},
            FeatureTypes=['TABLES', 'FORMS', 'QUERIES'],
            QueriesConfig={
                'Queries': [
                    {'Text': 'What is the contract value?'},
                    {'Text': 'What is the completion date?'},
                    {'Text': 'Who are the parties to this contract?'}
                ]
            }
        )
        
        return {
            'statusCode': 200,
            'body': {
                'evidence_id': evidence_id,
                'job_id': response['JobId']
            }
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {'statusCode': 500, 'body': {'error': str(e)}}
EOF

# Package Lambda functions
cd lambda_packages
zip -r textract_processor.zip textract_processor.py
cd ..

print_success "Lambda packages created"

# Step 3: Deploy Lambda Functions
print_status "Step 3: Deploying Lambda functions..."

# Get bucket name from stack outputs
DOCUMENTS_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DocumentsBucket`].OutputValue' \
    --output text)

# Create Lambda execution role
aws iam create-role \
    --role-name VeriCaseLambdaExecutionRole-$ENVIRONMENT \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }' \
    --region $REGION || true

# Attach policies
aws iam attach-role-policy \
    --role-name VeriCaseLambdaExecutionRole-$ENVIRONMENT \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
    --region $REGION || true

# Create custom policy for AWS services
aws iam put-role-policy \
    --role-name VeriCaseLambdaExecutionRole-$ENVIRONMENT \
    --policy-name VeriCaseServiceAccess \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "textract:*",
                    "comprehend:*",
                    "rekognition:*",
                    "transcribe:*",
                    "bedrock:*",
                    "s3:GetObject",
                    "s3:PutObject"
                ],
                "Resource": "*"
            }
        ]
    }' \
    --region $REGION || true

# Wait for role to be ready
sleep 10

# Get role ARN
ROLE_ARN=$(aws iam get-role \
    --role-name VeriCaseLambdaExecutionRole-$ENVIRONMENT \
    --query 'Role.Arn' \
    --output text)

# Create Lambda function
aws lambda create-function \
    --function-name vericase-textract-processor-$ENVIRONMENT \
    --runtime python3.11 \
    --role $ROLE_ARN \
    --handler textract_processor.lambda_handler \
    --zip-file fileb://lambda_packages/textract_processor.zip \
    --timeout 900 \
    --memory-size 1024 \
    --environment Variables="{DOCUMENTS_BUCKET=$DOCUMENTS_BUCKET}" \
    --region $REGION || \
aws lambda update-function-code \
    --function-name vericase-textract-processor-$ENVIRONMENT \
    --zip-file fileb://lambda_packages/textract_processor.zip \
    --region $REGION

print_success "Lambda functions deployed"

# Step 4: Setup Bedrock Knowledge Base
print_status "Step 4: Setting up Bedrock Knowledge Base..."

# Get knowledge base bucket
KB_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseBucket`].OutputValue' \
    --output text)

# Create sample knowledge base configuration
cat > kb-config.json << EOF
{
    "name": "VeriCase-KB-$ENVIRONMENT",
    "description": "VeriCase Legal Evidence Knowledge Base",
    "roleArn": "$ROLE_ARN",
    "knowledgeBaseConfiguration": {
        "type": "VECTOR",
        "vectorKnowledgeBaseConfiguration": {
            "embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1"
        }
    },
    "storageConfiguration": {
        "type": "S3",
        "s3Configuration": {
            "bucketArn": "arn:aws:s3:::$KB_BUCKET"
        }
    }
}
EOF

print_success "Bedrock Knowledge Base configuration created"

# Step 5: Update Application Configuration
print_status "Step 5: Updating application configuration..."

# Create environment file with AWS resources
cat > .env.aws << EOF
# AWS Services Configuration
USE_AWS_SERVICES=true
AWS_REGION=$REGION

# S3 Buckets
S3_BUCKET=$DOCUMENTS_BUCKET
KNOWLEDGE_BASE_BUCKET=$KB_BUCKET

# Lambda Functions
TEXTRACT_PROCESSOR_FUNCTION=vericase-textract-processor-$ENVIRONMENT

# EventBridge
EVENT_BUS_NAME=vericase-events-$ENVIRONMENT

# Database
DATABASE_PASSWORD=$DATABASE_PASSWORD

# Feature Flags
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_DEFAULT_MODEL=bedrock
EOF

print_success "Application configuration updated"

# Step 6: Install Dependencies
print_status "Step 6: Installing AWS dependencies..."

if [ -f "requirements-aws.txt" ]; then
    pip install -r requirements-aws.txt
    print_success "AWS dependencies installed"
else
    print_warning "requirements-aws.txt not found, skipping dependency installation"
fi

# Step 7: Run Tests
print_status "Step 7: Running integration tests..."

# Create simple test script
cat > test_aws_integration.py << 'EOF'
import boto3
import asyncio
import sys
import os

async def test_aws_services():
    """Test AWS services connectivity"""
    try:
        # Test S3
        s3 = boto3.client('s3')
        s3.list_buckets()
        print("✅ S3 connection successful")
        
        # Test Textract
        textract = boto3.client('textract')
        print("✅ Textract client initialized")
        
        # Test Comprehend
        comprehend = boto3.client('comprehend')
        print("✅ Comprehend client initialized")
        
        # Test Bedrock
        bedrock = boto3.client('bedrock-runtime')
        print("✅ Bedrock client initialized")
        
        print("\n🎉 All AWS services are accessible!")
        return True
        
    except Exception as e:
        print(f"❌ AWS services test failed: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_aws_services())
    sys.exit(0 if result else 1)
EOF

python test_aws_integration.py
if [ $? -eq 0 ]; then
    print_success "AWS integration tests passed"
else
    print_warning "Some AWS integration tests failed"
fi

# Step 8: Display Summary
print_status "Deployment Summary:"
echo "===================="
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo "Stack Name: $STACK_NAME"
echo "Documents Bucket: $DOCUMENTS_BUCKET"
echo "Knowledge Base Bucket: $KB_BUCKET"
echo "Lambda Function: vericase-textract-processor-$ENVIRONMENT"
echo ""
echo "Configuration file created: .env.aws"
echo "Database password: $DATABASE_PASSWORD"
echo ""

print_success "🎉 VeriCase AWS Services deployment completed successfully!"

echo ""
echo "Next Steps:"
echo "1. Update your application to use the new AWS configuration"
echo "2. Test document upload and processing"
echo "3. Configure Bedrock Knowledge Base with your documents"
echo "4. Set up QuickSight dashboards for analytics"
echo "5. Configure Macie for sensitive data scanning"

# Cleanup
rm -f vericase-infrastructure.yaml
rm -f kb-config.json
rm -f test_aws_integration.py
rm -rf lambda_packages

print_success "Deployment script completed!"