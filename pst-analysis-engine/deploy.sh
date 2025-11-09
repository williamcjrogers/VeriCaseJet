#!/bin/bash
# VeriCase Production Deployment Script

set -e  # Exit on error

echo "🚀 VeriCase Production Deployment"
echo "================================"

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "   Please copy .env.example to .env and configure it"
    exit 1
fi

# Function to check if service is healthy
check_health() {
    local service=$1
    local max_attempts=30
    local attempt=1
    
    echo -n "   Waiting for $service to be healthy"
    while [ $attempt -le $max_attempts ]; do
        if docker-compose -f docker-compose.prod.yml ps 2>/dev/null | grep -q "$service.*healthy"; then
            echo " ✅"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    echo " ❌"
    return 1
}

# Build images
echo "📦 Building Docker images..."
if ! docker-compose -f docker-compose.prod.yml build --no-cache; then
    echo "❌ Failed to build Docker images"
    exit 1
fi

# Tag images for registry (if using)
if [ ! -z "$DOCKER_REGISTRY" ]; then
    echo "🏷️  Tagging images for registry: $DOCKER_REGISTRY"
    docker tag vericase/api:latest $DOCKER_REGISTRY/vericase/api:latest
    docker tag vericase/worker:latest $DOCKER_REGISTRY/vericase/worker:latest
fi

# Start infrastructure services first
echo "🏗️  Starting infrastructure services..."
docker-compose -f docker-compose.prod.yml up -d postgres redis minio opensearch tika

# Wait for services to be healthy
echo "⏳ Waiting for services to be ready..."
check_health "postgres"
check_health "redis"
check_health "minio"
check_health "opensearch"
check_health "tika"

# Create MinIO bucket if it doesn't exist
echo "📤 Setting up MinIO bucket..."
if ! docker-compose -f docker-compose.prod.yml exec -T minio mc alias set local http://localhost:9000 ${MINIO_ACCESS_KEY} ${MINIO_SECRET_KEY} 2>/dev/null; then
    echo "⚠️  Warning: Failed to set MinIO alias (may already exist)"
fi
if ! docker-compose -f docker-compose.prod.yml exec -T minio mc mb local/${MINIO_BUCKET} --ignore-existing 2>/dev/null; then
    echo "⚠️  Warning: Failed to create MinIO bucket (may already exist)"
fi

# Run database migrations
echo "🗄️  Running database migrations..."
if ! docker-compose -f docker-compose.prod.yml run --rm api python -m app.apply_migrations; then
    echo "❌ Failed to run database migrations"
    exit 1
fi

# Start application services
echo "🚀 Starting application services..."
docker-compose -f docker-compose.prod.yml up -d api worker beat flower

# Wait for API to be healthy
check_health "api"

# Show status
echo ""
echo "✨ Deployment complete!"
echo ""
echo "📍 Service URLs:"
echo "   - API:        http://localhost:8010"
echo "   - MinIO:      http://localhost:9001 (user: ${MINIO_ACCESS_KEY})"
echo "   - Flower:     http://localhost:5555"
echo "   - OpenSearch: http://localhost:9200"
echo ""
echo "📊 Check status with: docker-compose -f docker-compose.prod.yml ps"
echo "📋 View logs with:    docker-compose -f docker-compose.prod.yml logs -f [service]"
echo "🛑 Stop with:        docker-compose -f docker-compose.prod.yml down"
