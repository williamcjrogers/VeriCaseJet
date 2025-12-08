#!/bin/bash
# VeriCase Diagnostics Script
# Usage: ./ops/diagnose.sh [local|ec2|aws|all]

set -euo pipefail

# Configuration - ACTUAL VALUES
AWS_ACCOUNT_ID="526015377510"
AWS_REGION="eu-west-2"
EC2_IP="18.175.232.87"
EKS_CLUSTER="vericase-cluster"
RDS_HOST="database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com"
REDIS_HOST="master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com"
S3_BUCKET="vericase-docs"
OPENSEARCH_DOMAIN="vericase-opensearch"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
info() { echo -e "  ${BLUE}→${NC} $1"; }

usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  local   Check local Docker deployment"
    echo "  ec2     Check EC2 instance status"
    echo "  aws     Check AWS services"
    echo "  all     Run all diagnostics"
    echo ""
    exit 1
}

diagnose_local() {
    echo ""
    echo "=== Local Docker Diagnostics ==="
    echo ""

    # Docker running?
    if docker info &>/dev/null; then
        ok "Docker daemon running"
    else
        fail "Docker daemon not running"
        return 1
    fi

    # Containers
    echo ""
    echo "Containers:"
    if docker-compose -f docker-compose.prod.yml ps &>/dev/null; then
        docker-compose -f docker-compose.prod.yml ps --format "table {{.Name}}\t{{.Status}}"
    else
        warn "docker-compose.prod.yml not found or not running"
    fi

    # API health
    echo ""
    echo "API Health:"
    if curl -s --connect-timeout 3 http://localhost:8010/health &>/dev/null; then
        local health=$(curl -s http://localhost:8010/health)
        ok "API responding: $health"
    else
        fail "API not responding on localhost:8010"
    fi

    # .env file
    echo ""
    echo "Environment:"
    if [ -f .env ]; then
        ok ".env file exists"
        if grep -q "JWT_SECRET" .env; then
            ok "JWT_SECRET configured"
        else
            fail "JWT_SECRET missing"
        fi
        if grep -q "DATABASE_URL" .env; then
            ok "DATABASE_URL configured"
        else
            warn "DATABASE_URL not set (using default)"
        fi
    else
        fail ".env file not found"
    fi
}

diagnose_ec2() {
    echo ""
    echo "=== EC2 Diagnostics ($EC2_IP) ==="
    echo ""

    # Ping EC2
    echo "Connectivity:"
    if ping -c 1 -W 3 $EC2_IP &>/dev/null; then
        ok "EC2 reachable (ping)"
    else
        warn "EC2 not responding to ping (may be blocked)"
    fi

    # API health
    if curl -s --connect-timeout 5 "http://$EC2_IP:8010/health" &>/dev/null; then
        local health=$(curl -s "http://$EC2_IP:8010/health")
        ok "API healthy: $health"
    else
        fail "API not responding on $EC2_IP:8010"
    fi

    # SSH check (if key available)
    local key_path="${SSH_KEY_PATH:-$HOME/.ssh/VeriCase-Safe.pem}"
    if [ -f "$key_path" ]; then
        echo ""
        echo "SSH Access:"
        if ssh -i "$key_path" -o ConnectTimeout=5 -o StrictHostKeyChecking=no ec2-user@$EC2_IP "echo connected" &>/dev/null; then
            ok "SSH connection successful"

            echo ""
            echo "Remote Docker Status:"
            ssh -i "$key_path" -o StrictHostKeyChecking=no ec2-user@$EC2_IP "sudo docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null" || warn "Could not get docker status"
        else
            fail "SSH connection failed"
        fi
    else
        warn "SSH key not found: $key_path"
    fi
}

diagnose_aws() {
    echo ""
    echo "=== AWS Services Diagnostics ==="
    echo ""

    # AWS CLI configured?
    if ! command -v aws &>/dev/null; then
        fail "AWS CLI not installed"
        return 1
    fi

    if ! aws sts get-caller-identity &>/dev/null; then
        fail "AWS credentials not configured"
        return 1
    fi

    local account=$(aws sts get-caller-identity --query Account --output text)
    ok "AWS Account: $account"

    # S3
    echo ""
    echo "S3 Buckets:"
    if aws s3 ls "s3://$S3_BUCKET" &>/dev/null; then
        ok "$S3_BUCKET accessible"
        local count=$(aws s3 ls "s3://$S3_BUCKET" --recursive --summarize 2>/dev/null | grep "Total Objects" | awk '{print $3}')
        info "Objects: ${count:-0}"
    else
        fail "$S3_BUCKET not accessible"
    fi

    # RDS
    echo ""
    echo "RDS Database:"
    local rds_status=$(aws rds describe-db-instances --query "DBInstances[?Endpoint.Address=='$RDS_HOST'].DBInstanceStatus" --output text 2>/dev/null)
    if [ "$rds_status" = "available" ]; then
        ok "RDS: $rds_status"
        info "Endpoint: $RDS_HOST"
    else
        fail "RDS status: ${rds_status:-not found}"
    fi

    # ElastiCache Redis
    echo ""
    echo "ElastiCache Redis:"
    local redis_count=$(aws elasticache describe-cache-clusters --query "length(CacheClusters[?contains(CacheClusterId, 'vericase')])" --output text 2>/dev/null)
    if [ "$redis_count" -gt 0 ]; then
        ok "Redis clusters: $redis_count"
        info "Endpoint: $REDIS_HOST"
    else
        fail "No Redis clusters found"
    fi

    # OpenSearch
    echo ""
    echo "OpenSearch:"
    local os_status=$(aws opensearch describe-domain --domain-name $OPENSEARCH_DOMAIN --query "DomainStatus.Processing" --output text 2>/dev/null)
    if [ "$os_status" = "False" ]; then
        ok "OpenSearch: active"
    else
        warn "OpenSearch: ${os_status:-not found}"
    fi

    # EKS
    echo ""
    echo "EKS Cluster:"
    local eks_status=$(aws eks describe-cluster --name $EKS_CLUSTER --query "cluster.status" --output text 2>/dev/null)
    if [ "$eks_status" = "ACTIVE" ]; then
        ok "EKS: $eks_status"
        local node_count=$(aws eks list-nodegroups --cluster-name $EKS_CLUSTER --query "length(nodegroups)" --output text 2>/dev/null)
        info "Node groups: $node_count"
    else
        fail "EKS status: ${eks_status:-not found}"
    fi

    # Secrets Manager
    echo ""
    echo "Secrets Manager:"
    if aws secretsmanager describe-secret --secret-id "vericase/ai-api-keys" &>/dev/null; then
        ok "vericase/ai-api-keys exists"
    else
        warn "vericase/ai-api-keys not found"
    fi

    # Running EC2 instances
    echo ""
    echo "EC2 Instances:"
    aws ec2 describe-instances \
        --filters "Name=instance-state-name,Values=running" \
        --query "Reservations[*].Instances[*].[Tags[?Key=='Name'].Value|[0],PublicIpAddress,InstanceType]" \
        --output text 2>/dev/null | while read name ip type; do
            info "$name: $ip ($type)"
        done
}

diagnose_all() {
    diagnose_local
    diagnose_ec2
    diagnose_aws
}

# Main
cd "$(dirname "$0")/.."

case "${1:-all}" in
    local)
        diagnose_local
        ;;
    ec2)
        diagnose_ec2
        ;;
    aws)
        diagnose_aws
        ;;
    all)
        diagnose_all
        ;;
    *)
        usage
        ;;
esac

echo ""
echo "=== Diagnostics Complete ==="
echo ""
