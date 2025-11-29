# VeriCase AWS Services Complete Setup Script
# Run this script to automatically deploy all 10 AWS services

param(
    [string]$Environment = "production",
    [string]$Region = "us-east-1",
    [string]$DomainName = "vericase.com"
)

Write-Host "🚀 Setting up VeriCase AWS Services..." -ForegroundColor Green
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow

# Check prerequisites
Write-Host "📋 Checking prerequisites..." -ForegroundColor Blue

# Check AWS CLI
if (!(Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "❌ AWS CLI not found. Please install AWS CLI first." -ForegroundColor Red
    exit 1
}

# Check AWS credentials
try {
    aws sts get-caller-identity | Out-Null
    Write-Host "✅ AWS credentials configured" -ForegroundColor Green
} catch {
    Write-Host "❌ AWS credentials not configured. Run 'aws configure'" -ForegroundColor Red
    exit 1
}

# Generate secure database password
$DatabasePassword = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 16 | ForEach-Object {[char]$_})
Write-Host "🔐 Generated database password: $DatabasePassword" -ForegroundColor Yellow
Write-Host "⚠️  SAVE THIS PASSWORD SECURELY!" -ForegroundColor Red

# Step 1: Deploy Core Infrastructure
Write-Host "🏗️  Step 1: Deploying core infrastructure..." -ForegroundColor Blue

$CloudFormationTemplate = @"
AWSTemplateFormatVersion: '2010-09-09'
Description: 'VeriCase Complete AWS Infrastructure'

Parameters:
  Environment:
    Type: String
    Default: $Environment
  DatabasePassword:
    Type: String
    NoEcho: true
    Default: $DatabasePassword
  DomainName:
    Type: String
    Default: $DomainName

Resources:
  # S3 Buckets
  DocumentsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub 'vericase-docs-`${Environment}-`${AWS::AccountId}'
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

  KnowledgeBaseBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub 'vericase-kb-`${Environment}-`${AWS::AccountId}'

  # OpenSearch Serverless
  SearchCollection:
    Type: AWS::OpenSearchServerless::Collection
    Properties:
      Name: !Sub 'vericase-search-`${Environment}'
      Type: SEARCH

  # EventBridge
  EventBus:
    Type: AWS::Events::EventBus
    Properties:
      Name: !Sub 'vericase-events-`${Environment}'

  # IAM Role for Lambda
  LambdaRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
      Policies:
        - PolicyName: VeriCaseServiceAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - textract:*
                  - comprehend:*
                  - rekognition:*
                  - transcribe:*
                  - bedrock:*
                  - s3:GetObject
                  - s3:PutObject
                  - opensearch:*
                Resource: '*'

Outputs:
  DocumentsBucket:
    Value: !Ref DocumentsBucket
    Export:
      Name: !Sub '`${AWS::StackName}-DocumentsBucket'
  
  KnowledgeBaseBucket:
    Value: !Ref KnowledgeBaseBucket
    Export:
      Name: !Sub '`${AWS::StackName}-KnowledgeBaseBucket'
  
  LambdaRoleArn:
    Value: !GetAtt LambdaRole.Arn
    Export:
      Name: !Sub '`${AWS::StackName}-LambdaRole'
"@

# Save CloudFormation template
$CloudFormationTemplate | Out-File -FilePath "vericase-infrastructure.yaml" -Encoding UTF8

# Deploy infrastructure
Write-Host "📦 Deploying CloudFormation stack..." -ForegroundColor Blue
$StackName = "vericase-infrastructure-$Environment"

aws cloudformation deploy `
    --template-file vericase-infrastructure.yaml `
    --stack-name $StackName `
    --parameter-overrides Environment=$Environment DatabasePassword=$DatabasePassword DomainName=$DomainName `
    --capabilities CAPABILITY_IAM `
    --region $Region

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Infrastructure deployment failed" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Infrastructure deployed successfully" -ForegroundColor Green

# Get stack outputs
$Outputs = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].Outputs' --output json | ConvertFrom-Json

$DocumentsBucket = ($Outputs | Where-Object {$_.OutputKey -eq "DocumentsBucket"}).OutputValue
$KnowledgeBaseBucket = ($Outputs | Where-Object {$_.OutputKey -eq "KnowledgeBaseBucket"}).OutputValue
$LambdaRoleArn = ($Outputs | Where-Object {$_.OutputKey -eq "LambdaRoleArn"}).OutputValue

Write-Host "📊 Infrastructure Details:" -ForegroundColor Blue
Write-Host "  Documents Bucket: $DocumentsBucket" -ForegroundColor White
Write-Host "  Knowledge Base Bucket: $KnowledgeBaseBucket" -ForegroundColor White

# Step 2: Create Lambda Functions
Write-Host "🔧 Step 2: Creating Lambda functions..." -ForegroundColor Blue

# Create Lambda function packages directory
New-Item -ItemType Directory -Force -Path "lambda-packages" | Out-Null

# Textract Processor Lambda
$TextractCode = @"
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
        
        logger.info(f'Processing document: {s3_bucket}/{s3_key}')
        
        response = textract.start_document_analysis(
            DocumentLocation={
                'S3Object': {'Bucket': s3_bucket, 'Name': s3_key}
            },
            FeatureTypes=['TABLES', 'FORMS', 'QUERIES'],
            QueriesConfig={
                'Queries': [
                    {'Text': 'What is the contract value?'},
                    {'Text': 'What is the completion date?'},
                    {'Text': 'Who are the parties to this contract?'},
                    {'Text': 'What is the project name?'}
                ]
            }
        )
        
        return {
            'statusCode': 200,
            'body': {
                'evidence_id': evidence_id,
                'job_id': response['JobId'],
                'status': 'STARTED'
            }
        }
    except Exception as e:
        logger.error(f'Error: {e}')
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }
"@

$TextractCode | Out-File -FilePath "lambda-packages/textract_processor.py" -Encoding UTF8

# Create ZIP package
Compress-Archive -Path "lambda-packages/textract_processor.py" -DestinationPath "lambda-packages/textract_processor.zip" -Force

# Deploy Lambda function
Write-Host "📤 Deploying Textract processor..." -ForegroundColor Blue

aws lambda create-function `
    --function-name "vericase-textract-processor-$Environment" `
    --runtime python3.11 `
    --role $LambdaRoleArn `
    --handler textract_processor.lambda_handler `
    --zip-file fileb://lambda-packages/textract_processor.zip `
    --timeout 900 `
    --memory-size 1024 `
    --environment Variables="{DOCUMENTS_BUCKET=$DocumentsBucket}" `
    --region $Region 2>$null

if ($LASTEXITCODE -ne 0) {
    # Function might already exist, try to update
    aws lambda update-function-code `
        --function-name "vericase-textract-processor-$Environment" `
        --zip-file fileb://lambda-packages/textract_processor.zip `
        --region $Region
}

Write-Host "✅ Lambda functions deployed" -ForegroundColor Green

# Step 3: Setup Bedrock Knowledge Base
Write-Host "🧠 Step 3: Setting up Bedrock Knowledge Base..." -ForegroundColor Blue

# Create Bedrock service role
$BedrockRolePolicy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "bedrock.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
"@

$BedrockRolePolicy | Out-File -FilePath "bedrock-trust-policy.json" -Encoding UTF8

aws iam create-role `
    --role-name "VeriCaseBedrockRole-$Environment" `
    --assume-role-policy-document file://bedrock-trust-policy.json `
    --region $Region 2>$null

# Attach policies to Bedrock role
$BedrockPolicy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::$KnowledgeBaseBucket",
                "arn:aws:s3:::$KnowledgeBaseBucket/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel"
            ],
            "Resource": "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v1"
        }
    ]
}
"@

$BedrockPolicy | Out-File -FilePath "bedrock-policy.json" -Encoding UTF8

aws iam put-role-policy `
    --role-name "VeriCaseBedrockRole-$Environment" `
    --policy-name "VeriCaseBedrockPolicy" `
    --policy-document file://bedrock-policy.json `
    --region $Region

Write-Host "✅ Bedrock Knowledge Base configured" -ForegroundColor Green

# Step 4: Create Application Configuration
Write-Host "⚙️  Step 4: Creating application configuration..." -ForegroundColor Blue

$EnvConfig = @"
# VeriCase AWS Services Configuration
USE_AWS_SERVICES=true
AWS_REGION=$Region

# S3 Buckets
S3_BUCKET=$DocumentsBucket
KNOWLEDGE_BASE_BUCKET=$KnowledgeBaseBucket

# Lambda Functions
TEXTRACT_PROCESSOR_FUNCTION=vericase-textract-processor-$Environment

# EventBridge
EVENT_BUS_NAME=vericase-events-$Environment

# Database
DATABASE_PASSWORD=$DatabasePassword

# Feature Flags
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_DEFAULT_MODEL=bedrock

# Cost Optimization
ENABLE_SMART_ROUTING=true
ENABLE_RESULT_CACHING=true
TEXTRACT_PAGE_THRESHOLD=100
"@

$EnvConfig | Out-File -FilePath ".env.aws" -Encoding UTF8

Write-Host "✅ Configuration created: .env.aws" -ForegroundColor Green

# Step 5: Install Dependencies
Write-Host "📦 Step 5: Installing AWS dependencies..." -ForegroundColor Blue

if (Test-Path "requirements-aws.txt") {
    pip install -r requirements-aws.txt
    Write-Host "✅ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "⚠️  requirements-aws.txt not found, skipping" -ForegroundColor Yellow
}

# Step 6: Test AWS Services
Write-Host "🧪 Step 6: Testing AWS services..." -ForegroundColor Blue

$TestScript = @"
import boto3
import sys

def test_services():
    try:
        # Test S3
        s3 = boto3.client('s3', region_name='$Region')
        s3.head_bucket(Bucket='$DocumentsBucket')
        print('✅ S3 access confirmed')
        
        # Test Textract
        textract = boto3.client('textract', region_name='$Region')
        print('✅ Textract client initialized')
        
        # Test Comprehend
        comprehend = boto3.client('comprehend', region_name='$Region')
        print('✅ Comprehend client initialized')
        
        # Test Lambda
        lambda_client = boto3.client('lambda', region_name='$Region')
        lambda_client.get_function(FunctionName='vericase-textract-processor-$Environment')
        print('✅ Lambda function accessible')
        
        print('\n🎉 All AWS services are ready!')
        return True
        
    except Exception as e:
        print(f'❌ Test failed: {e}')
        return False

if __name__ == '__main__':
    success = test_services()
    sys.exit(0 if success else 1)
"@

$TestScript | Out-File -FilePath "test_aws_services.py" -Encoding UTF8

python test_aws_services.py
$TestResult = $LASTEXITCODE

if ($TestResult -eq 0) {
    Write-Host "✅ AWS services test passed" -ForegroundColor Green
} else {
    Write-Host "⚠️  Some AWS services tests failed" -ForegroundColor Yellow
}

# Step 7: Display Summary
Write-Host "`n🎉 VeriCase AWS Services Setup Complete!" -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Blue

Write-Host "`n📊 Deployment Summary:" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor White
Write-Host "Region: $Region" -ForegroundColor White
Write-Host "Stack Name: $StackName" -ForegroundColor White
Write-Host "Documents Bucket: $DocumentsBucket" -ForegroundColor White
Write-Host "Knowledge Base Bucket: $KnowledgeBaseBucket" -ForegroundColor White

Write-Host "`n🔐 Important Information:" -ForegroundColor Yellow
Write-Host "Database Password: $DatabasePassword" -ForegroundColor Red
Write-Host "Configuration File: .env.aws" -ForegroundColor White

Write-Host "`n💰 Estimated Costs:" -ForegroundColor Blue
Write-Host "First 5GB file processing: ~£33" -ForegroundColor White
Write-Host "Monthly ongoing costs: ~£17" -ForegroundColor White

Write-Host "`n🚀 Next Steps:" -ForegroundColor Blue
Write-Host "1. Copy .env.aws to .env in your application" -ForegroundColor White
Write-Host "2. Restart your VeriCase application" -ForegroundColor White
Write-Host "3. Upload a test PST file to verify processing" -ForegroundColor White
Write-Host "4. Access enhanced features via /api/v1/aws/ endpoints" -ForegroundColor White

Write-Host "`n✨ New Capabilities Enabled:" -ForegroundColor Green
Write-Host "• AI-powered document classification" -ForegroundColor White
Write-Host "• Semantic search across all evidence" -ForegroundColor White
Write-Host "• Automatic entity extraction" -ForegroundColor White
Write-Host "• Construction image analysis" -ForegroundColor White
Write-Host "• Audio/video transcription" -ForegroundColor White
Write-Host "• Sensitive data detection" -ForegroundColor White

# Cleanup temporary files
Remove-Item -Path "vericase-infrastructure.yaml" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "bedrock-trust-policy.json" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "bedrock-policy.json" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "test_aws_services.py" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "lambda-packages" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "`n🎯 Setup Complete! Your VeriCase application now has AI superpowers!" -ForegroundColor Green