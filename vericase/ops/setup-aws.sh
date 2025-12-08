#!/bin/bash
# VeriCase AWS Setup Script
# Usage: ./ops/setup-aws.sh [minimal|standard|full]
#
# Modes:
#   minimal  - S3 bucket only (~$1/month)
#   standard - S3 + Secrets Manager (~$5/month)
#   full     - S3 + RDS + Redis + OpenSearch + Lambda (~$200/month)

set -euo pipefail

# Configuration - ACTUAL VALUES
AWS_ACCOUNT_ID="526015377510"
AWS_REGION="eu-west-2"
ENVIRONMENT="production"

# Resource names
S3_BUCKET="vericase-docs"
S3_KB_BUCKET="vericase-knowledge-base-${AWS_ACCOUNT_ID}"
SECRET_NAME="vericase/ai-api-keys"
LAMBDA_ROLE="VeriCaseLambdaRole"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    echo "VeriCase AWS Setup"
    echo "=================="
    echo ""
    echo "Usage: $0 [mode]"
    echo ""
    echo "Modes:"
    echo "  minimal   S3 bucket only (~\$1/month)"
    echo "  standard  S3 + Secrets Manager (~\$5/month)"
    echo "  full      Complete AWS infrastructure (~\$200/month)"
    echo "  secrets   Configure Secrets Manager only"
    echo "  status    Show current AWS resources"
    echo ""
    exit 1
}

check_aws() {
    log_info "Checking AWS credentials..."

    if ! command -v aws &>/dev/null; then
        log_error "AWS CLI not installed"
        exit 1
    fi

    if ! aws sts get-caller-identity &>/dev/null; then
        log_error "AWS credentials not configured. Run 'aws configure'"
        exit 1
    fi

    local account=$(aws sts get-caller-identity --query Account --output text)
    local region=$(aws configure get region)

    log_success "AWS Account: $account"
    log_success "Region: $region"

    if [ "$account" != "$AWS_ACCOUNT_ID" ]; then
        log_warn "Account ID mismatch. Expected: $AWS_ACCOUNT_ID, Got: $account"
    fi
}

setup_s3() {
    log_info "Setting up S3 buckets..."

    # Main documents bucket
    if aws s3 ls "s3://$S3_BUCKET" &>/dev/null; then
        log_success "S3 bucket exists: $S3_BUCKET"
    else
        log_info "Creating S3 bucket: $S3_BUCKET"
        aws s3 mb "s3://$S3_BUCKET" --region $AWS_REGION

        # Enable versioning
        aws s3api put-bucket-versioning \
            --bucket $S3_BUCKET \
            --versioning-configuration Status=Enabled

        # Block public access
        aws s3api put-public-access-block \
            --bucket $S3_BUCKET \
            --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

        # Enable EventBridge notifications
        aws s3api put-bucket-notification-configuration \
            --bucket $S3_BUCKET \
            --notification-configuration '{"EventBridgeConfiguration":{}}'

        log_success "S3 bucket created: $S3_BUCKET"
    fi

    # Knowledge base bucket
    if aws s3 ls "s3://$S3_KB_BUCKET" &>/dev/null; then
        log_success "S3 KB bucket exists: $S3_KB_BUCKET"
    else
        log_info "Creating S3 KB bucket: $S3_KB_BUCKET"
        aws s3 mb "s3://$S3_KB_BUCKET" --region $AWS_REGION
        log_success "S3 KB bucket created: $S3_KB_BUCKET"
    fi
}

setup_secrets() {
    log_info "Setting up Secrets Manager..."

    if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" &>/dev/null; then
        log_success "Secret exists: $SECRET_NAME"
        log_info "To update secret values, use AWS Console or:"
        echo "  aws secretsmanager put-secret-value --secret-id $SECRET_NAME --secret-string '{...}'"
    else
        log_info "Creating secret: $SECRET_NAME"

        # Prompt for API keys
        echo ""
        echo "Enter your API keys (press Enter to skip):"
        read -p "  OpenAI API Key: " OPENAI_KEY
        read -p "  Anthropic API Key: " CLAUDE_KEY
        read -p "  Google Gemini API Key: " GEMINI_KEY

        local secret_json=$(cat <<EOF
{
    "OPENAI_API_KEY": "${OPENAI_KEY:-}",
    "CLAUDE_API_KEY": "${CLAUDE_KEY:-}",
    "GEMINI_API_KEY": "${GEMINI_KEY:-}"
}
EOF
)
        aws secretsmanager create-secret \
            --name "$SECRET_NAME" \
            --description "VeriCase AI API Keys" \
            --secret-string "$secret_json" \
            --region $AWS_REGION

        log_success "Secret created: $SECRET_NAME"
    fi
}

setup_iam() {
    log_info "Setting up IAM roles..."

    # Check if role exists
    if aws iam get-role --role-name $LAMBDA_ROLE &>/dev/null; then
        log_success "IAM role exists: $LAMBDA_ROLE"
    else
        log_info "Creating IAM role: $LAMBDA_ROLE"

        # Trust policy
        local trust_policy=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF
)
        aws iam create-role \
            --role-name $LAMBDA_ROLE \
            --assume-role-policy-document "$trust_policy"

        # Attach basic Lambda policy
        aws iam attach-role-policy \
            --role-name $LAMBDA_ROLE \
            --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

        # Custom policy for VeriCase services
        local service_policy=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::$S3_BUCKET",
                "arn:aws:s3:::$S3_BUCKET/*",
                "arn:aws:s3:::$S3_KB_BUCKET",
                "arn:aws:s3:::$S3_KB_BUCKET/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "textract:*",
                "comprehend:*",
                "bedrock:*"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "arn:aws:secretsmanager:$AWS_REGION:$AWS_ACCOUNT_ID:secret:$SECRET_NAME*"
        }
    ]
}
EOF
)
        aws iam put-role-policy \
            --role-name $LAMBDA_ROLE \
            --policy-name VeriCaseServiceAccess \
            --policy-document "$service_policy"

        log_success "IAM role created: $LAMBDA_ROLE"
    fi
}

setup_minimal() {
    log_info "Setting up MINIMAL AWS infrastructure..."
    echo ""
    echo "This will create:"
    echo "  - S3 bucket for documents"
    echo "  - Estimated cost: ~\$1/month"
    echo ""

    setup_s3
    generate_env "minimal"

    log_success "Minimal setup complete!"
}

setup_standard() {
    log_info "Setting up STANDARD AWS infrastructure..."
    echo ""
    echo "This will create:"
    echo "  - S3 buckets for documents and knowledge base"
    echo "  - Secrets Manager for API keys"
    echo "  - IAM role for Lambda"
    echo "  - Estimated cost: ~\$5/month"
    echo ""

    setup_s3
    setup_secrets
    setup_iam
    generate_env "standard"

    log_success "Standard setup complete!"
}

setup_full() {
    log_info "Setting up FULL AWS infrastructure..."
    echo ""
    echo "WARNING: This will create expensive resources!"
    echo "  - S3 buckets"
    echo "  - Secrets Manager"
    echo "  - IAM roles"
    echo "  - RDS PostgreSQL (~\$50/month)"
    echo "  - ElastiCache Redis (~\$50/month)"
    echo "  - OpenSearch (~\$100/month)"
    echo "  - Estimated cost: ~\$200/month"
    echo ""
    read -p "Continue? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 0
    fi

    setup_s3
    setup_secrets
    setup_iam

    log_warn "RDS, ElastiCache, and OpenSearch must be created via AWS Console or CloudFormation"
    log_info "See docs/deployment/AWS_SETUP_GUIDE.md for instructions"

    generate_env "full"

    log_success "Full setup complete (database services need manual setup)"
}

generate_env() {
    local mode=$1
    local env_file=".env.aws"

    log_info "Generating $env_file..."

    cat > $env_file << EOF
# VeriCase AWS Configuration
# Generated by ops/setup-aws.sh ($mode mode)
# $(date)

USE_AWS_SERVICES=true
AWS_REGION=$AWS_REGION
AWS_ACCOUNT_ID=$AWS_ACCOUNT_ID

# S3
S3_BUCKET=$S3_BUCKET
KNOWLEDGE_BASE_BUCKET=$S3_KB_BUCKET

# Secrets Manager
AWS_SECRETS_MANAGER_AI_KEYS=$SECRET_NAME

# Feature flags
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
EOF

    if [ "$mode" = "full" ]; then
        cat >> $env_file << EOF

# RDS (update with actual endpoint)
DATABASE_URL=postgresql://vericase:PASSWORD@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/vericase

# ElastiCache Redis
REDIS_URL=redis://master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com:6379

# OpenSearch
OPENSEARCH_HOST=https://vericase-opensearch.eu-west-2.es.amazonaws.com
OPENSEARCH_USE_SSL=true
EOF
    fi

    log_success "Generated: $env_file"
    echo ""
    echo "Next steps:"
    echo "  1. Review $env_file"
    echo "  2. Copy to .env: cp $env_file .env"
    echo "  3. Restart application"
}

show_status() {
    log_info "Current AWS resources for VeriCase..."
    echo ""

    echo "S3 Buckets:"
    aws s3 ls 2>/dev/null | grep -i vericase || echo "  None found"
    echo ""

    echo "Secrets Manager:"
    aws secretsmanager list-secrets --query "SecretList[?contains(Name, 'vericase')].[Name]" --output text 2>/dev/null || echo "  None found"
    echo ""

    echo "IAM Roles:"
    aws iam list-roles --query "Roles[?contains(RoleName, 'vericase') || contains(RoleName, 'VeriCase')].[RoleName]" --output text 2>/dev/null || echo "  None found"
    echo ""

    echo "RDS:"
    aws rds describe-db-instances --query "DBInstances[*].[DBInstanceIdentifier,DBInstanceStatus,Endpoint.Address]" --output text 2>/dev/null || echo "  None found"
    echo ""

    echo "ElastiCache:"
    aws elasticache describe-cache-clusters --query "CacheClusters[?contains(CacheClusterId, 'vericase')].[CacheClusterId,CacheClusterStatus]" --output text 2>/dev/null || echo "  None found"
    echo ""

    echo "OpenSearch:"
    aws opensearch list-domain-names --query "DomainNames[?contains(DomainName, 'vericase')].[DomainName]" --output text 2>/dev/null || echo "  None found"
    echo ""

    echo "EKS:"
    aws eks list-clusters --query "clusters" --output text 2>/dev/null | grep -i vericase || echo "  None found"
    echo ""
}

# Main
cd "$(dirname "$0")/.."

check_aws

case "${1:-}" in
    minimal)
        setup_minimal
        ;;
    standard)
        setup_standard
        ;;
    full)
        setup_full
        ;;
    secrets)
        setup_secrets
        ;;
    status)
        show_status
        ;;
    *)
        usage
        ;;
esac
