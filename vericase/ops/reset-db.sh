#!/bin/bash
# VeriCase Database Reset Script
# Usage: ./ops/reset-db.sh [local|ec2]
#
# WARNING: This will DELETE ALL DATA!

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

EC2_IP="18.175.232.87"

usage() {
    echo "VeriCase Database Reset"
    echo "======================="
    echo ""
    echo "WARNING: This will DELETE ALL DATA!"
    echo ""
    echo "Usage: $0 [target]"
    echo ""
    echo "Targets:"
    echo "  local   Reset local Docker database"
    echo "  ec2     Reset EC2 database (SSH required)"
    echo ""
    exit 1
}

confirm() {
    echo -e "${RED}WARNING: This will DELETE ALL DATA!${NC}"
    echo ""
    read -p "Type 'DELETE' to confirm: " confirm
    if [ "$confirm" != "DELETE" ]; then
        echo "Aborted."
        exit 0
    fi
}

reset_local() {
    echo "Resetting local database..."
    confirm

    echo "[1/4] Stopping services..."
    docker-compose -f docker-compose.prod.yml down 2>/dev/null || docker-compose down 2>/dev/null || true

    echo "[2/4] Removing database volume..."
    docker volume rm vericase_postgres_data 2>/dev/null || true
    docker volume rm postgres_data 2>/dev/null || true

    echo "[3/4] Starting fresh database..."
    docker-compose -f docker-compose.prod.yml up -d postgres 2>/dev/null || docker-compose up -d postgres

    echo "[4/4] Waiting for database..."
    sleep 10

    echo "[5/5] Running migrations (Alembic)..."
    docker-compose -f docker-compose.prod.yml run --rm api alembic upgrade head 2>/dev/null || \
    docker-compose run --rm api alembic upgrade head

    echo ""
    echo -e "${GREEN}Database reset complete!${NC}"
    echo ""
    echo "Start all services with:"
    echo "  docker-compose -f docker-compose.prod.yml up -d"
}

reset_ec2() {
    echo "Resetting EC2 database ($EC2_IP)..."
    confirm

    local key_path="${SSH_KEY_PATH:-$HOME/.ssh/VeriCase-Safe.pem}"

    if [ ! -f "$key_path" ]; then
        echo -e "${RED}SSH key not found: $key_path${NC}"
        exit 1
    fi

    echo "Connecting to EC2..."
    ssh -i "$key_path" -o StrictHostKeyChecking=no ec2-user@$EC2_IP << 'ENDSSH'
        cd ~/vericase || exit 1

        echo "[1/4] Stopping services..."
        sudo docker-compose down

        echo "[2/4] Removing database volume..."
        sudo docker volume rm $(sudo docker volume ls -q | grep postgres) 2>/dev/null || true

        echo "[3/4] Starting fresh database..."
        sudo docker-compose up -d postgres
        sleep 10

        echo "[4/4] Running migrations (Alembic)..."
        sudo docker-compose run --rm api alembic upgrade head

        echo ""
        echo "Starting all services..."
        sudo docker-compose up -d

        echo ""
        echo "Database reset complete!"
        sudo docker-compose ps
ENDSSH

    echo ""
    echo -e "${GREEN}EC2 database reset complete!${NC}"
}

# Main
cd "$(dirname "$0")/.."

case "${1:-}" in
    local)
        reset_local
        ;;
    ec2)
        reset_ec2
        ;;
    *)
        usage
        ;;
esac
