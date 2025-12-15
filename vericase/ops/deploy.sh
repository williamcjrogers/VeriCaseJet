#!/bin/bash
# VeriCase Deployment Script
# Usage: ./ops/deploy.sh [local|ec2|eks]

set -euo pipefail

# Configuration
AWS_ACCOUNT_ID="526015377510"
AWS_REGION="eu-west-2"
EC2_IP="18.175.232.87"
EKS_CLUSTER="vericase-cluster"
DOCKER_IMAGE="wcjrogers/vericase-api:latest"

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
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  local     Deploy locally with docker-compose"
    echo "  ec2       Deploy to EC2 instance ($EC2_IP)"
    echo "  eks       Deploy to EKS cluster ($EKS_CLUSTER)"
    echo "  build     Build and push Docker image"
    echo "  status    Show deployment status"
    echo ""
    exit 1
}

check_prereqs() {
    log_info "Checking prerequisites..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker not found"
        exit 1
    fi
    log_success "Docker installed"

    if ! command -v aws &> /dev/null; then
        log_warn "AWS CLI not found - EC2/EKS deploys will fail"
    else
        log_success "AWS CLI installed"
    fi
}

check_env() {
    if [ ! -f .env ]; then
        log_error ".env file not found"
        log_info "Copy .env.example to .env and configure it"
        exit 1
    fi
    log_success ".env file found"
}

wait_healthy() {
    local service=$1
    local max_attempts=30
    local attempt=1

    echo -n "  Waiting for $service"
    while [ $attempt -le $max_attempts ]; do
        if docker-compose -f docker-compose.prod.yml ps | grep -q "$service.*healthy"; then
            echo -e " ${GREEN}OK${NC}"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    echo -e " ${RED}FAILED${NC}"
    return 1
}

deploy_local() {
    log_info "Deploying locally with docker-compose..."
    check_env

    log_info "Building images..."
    docker-compose -f docker-compose.prod.yml build

    log_info "Starting infrastructure..."
    docker-compose -f docker-compose.prod.yml up -d postgres redis minio opensearch tika

    log_info "Waiting for services..."
    wait_healthy "postgres"
    wait_healthy "redis"

    log_info "Running migrations (Alembic)..."
    docker-compose -f docker-compose.prod.yml run --rm api alembic upgrade head

    log_info "Starting application..."
    docker-compose -f docker-compose.prod.yml up -d api worker

    wait_healthy "api"

    log_success "Local deployment complete!"
    echo ""
    echo "  API:        http://localhost:8010"
    echo "  MinIO:      http://localhost:9001"
    echo "  OpenSearch: http://localhost:9200"
    echo ""
    echo "Commands:"
    echo "  Logs:   docker-compose -f docker-compose.prod.yml logs -f api"
    echo "  Stop:   docker-compose -f docker-compose.prod.yml down"
}

deploy_ec2() {
    log_info "Deploying to EC2 ($EC2_IP)..."

    local key_path="${SSH_KEY_PATH:-$HOME/.ssh/VeriCase-Safe.pem}"

    if [ ! -f "$key_path" ]; then
        log_error "SSH key not found: $key_path"
        log_info "Set SSH_KEY_PATH environment variable"
        exit 1
    fi

    log_info "Connecting to EC2..."
    local known_hosts_file="$HOME/.ssh/known_hosts"
    if [ ! -f "$known_hosts_file" ]; then
        log_warn "known_hosts not found: $known_hosts_file"
        log_info "Prime it first (Windows): powershell -ExecutionPolicy Bypass -File .\\vericase\\ops\\setup-ssh.ps1"
        log_info "Then retry this deploy."
        exit 1
    fi

    ssh -i "$key_path" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$HOME/.ssh/known_hosts" ec2-user@$EC2_IP << 'ENDSSH'
        cd ~/vericase || exit 1
        echo "Pulling latest images..."
        sudo docker-compose pull
        echo "Restarting services..."
        sudo docker-compose down
        sudo docker-compose up -d
        echo "Checking status..."
        sudo docker-compose ps
ENDSSH

    if [ $? -ne 0 ]; then
        log_error "SSH failed. If this is the first connection or host key changed, prime known_hosts first."
        log_info "Windows: powershell -ExecutionPolicy Bypass -File .\\vericase\\ops\\setup-ssh.ps1"
        exit 1
    fi

    log_success "EC2 deployment complete!"
    echo ""
    echo "  API: http://$EC2_IP:8010"
    echo "  Health: curl http://$EC2_IP:8010/health"
}

deploy_eks() {
    log_info "Deploying to EKS ($EKS_CLUSTER)..."

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found"
        exit 1
    fi

    log_info "Updating kubeconfig..."
    aws eks update-kubeconfig --region $AWS_REGION --name $EKS_CLUSTER

    log_info "Applying Kubernetes manifests..."
    kubectl apply -f k8s-deployment.yaml
    kubectl apply -f k8s-ingress.yaml

    log_info "Restarting deployment..."
    kubectl rollout restart deployment/vericase-api

    log_info "Waiting for rollout..."
    kubectl rollout status deployment/vericase-api --timeout=300s

    log_success "EKS deployment complete!"
    kubectl get pods -l app=vericase-api
}

build_push() {
    log_info "Building and pushing Docker image..."

    docker build -t $DOCKER_IMAGE -f api/Dockerfile .
    docker push $DOCKER_IMAGE

    log_success "Image pushed: $DOCKER_IMAGE"
}

show_status() {
    echo ""
    echo "=== VeriCase Deployment Status ==="
    echo ""

    echo "Local Docker:"
    docker-compose -f docker-compose.prod.yml ps 2>/dev/null || echo "  Not running"
    echo ""

    echo "EC2 ($EC2_IP):"
    curl -s --connect-timeout 5 "http://$EC2_IP:8010/health" 2>/dev/null || echo "  Not reachable"
    echo ""

    echo "EKS ($EKS_CLUSTER):"
    kubectl get pods -l app=vericase-api 2>/dev/null || echo "  Not configured"
    echo ""
}

# Main
cd "$(dirname "$0")/.."

check_prereqs

case "${1:-}" in
    local)
        deploy_local
        ;;
    ec2)
        deploy_ec2
        ;;
    eks)
        deploy_eks
        ;;
    build)
        build_push
        ;;
    status)
        show_status
        ;;
    *)
        usage
        ;;
esac
