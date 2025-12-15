# VeriCase Diagnostics Script (PowerShell)
# Usage: .\ops\diagnose.ps1 [local|ec2|aws|all]

param(
    [Parameter(Position=0)]
    [ValidateSet("local", "ec2", "aws", "all")]
    [string]$Command = "all"
)

$ErrorActionPreference = "Continue"

# Configuration - ACTUAL VALUES
$AWS_ACCOUNT_ID = "526015377510"
$AWS_REGION = "eu-west-2"
$EC2_IP = "18.175.232.87"
$EKS_CLUSTER = "vericase-cluster"
$RDS_HOST = "database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com"
$REDIS_HOST = "master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com"
$S3_BUCKET = "vericase-docs"
$OPENSEARCH_DOMAIN = "vericase-opensearch"

function Ok { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Fail { param($msg) Write-Host "  [X] $msg" -ForegroundColor Red }
function Warn { param($msg) Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Info { param($msg) Write-Host "  --> $msg" -ForegroundColor Gray }

function Diagnose-Local {
    Write-Host ""
    Write-Host "=== Local Docker Diagnostics ===" -ForegroundColor Cyan
    Write-Host ""

    # Docker running?
    try {
        docker info 2>$null | Out-Null
        Ok "Docker daemon running"
    } catch {
        Fail "Docker daemon not running"
        return
    }

    # Containers
    Write-Host ""
    Write-Host "Containers:" -ForegroundColor Yellow
    try {
        docker-compose -f docker-compose.prod.yml ps 2>$null
    } catch {
        Warn "docker-compose.prod.yml not found or not running"
    }

    # API health
    Write-Host ""
    Write-Host "API Health:" -ForegroundColor Yellow
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8010/health" -TimeoutSec 3 -ErrorAction Stop
        Ok "API responding: $($health | ConvertTo-Json -Compress)"
    } catch {
        Fail "API not responding on localhost:8010"
    }

    # .env file
    Write-Host ""
    Write-Host "Environment:" -ForegroundColor Yellow
    if (Test-Path ".env") {
        Ok ".env file exists"
        $envContent = Get-Content ".env" -Raw
        if ($envContent -match "JWT_SECRET") {
            Ok "JWT_SECRET configured"
        } else {
            Fail "JWT_SECRET missing"
        }
        if ($envContent -match "DATABASE_URL") {
            Ok "DATABASE_URL configured"
        } else {
            Warn "DATABASE_URL not set (using default)"
        }
    } else {
        Fail ".env file not found"
    }
}

function Diagnose-EC2 {
    Write-Host ""
    Write-Host "=== EC2 Diagnostics ($EC2_IP) ===" -ForegroundColor Cyan
    Write-Host ""

    # Ping EC2
    Write-Host "Connectivity:" -ForegroundColor Yellow
    $ping = Test-Connection -ComputerName $EC2_IP -Count 1 -Quiet -TimeoutSeconds 3
    if ($ping) {
        Ok "EC2 reachable (ping)"
    } else {
        Warn "EC2 not responding to ping (may be blocked)"
    }

    # API health
    try {
        $health = Invoke-RestMethod -Uri "http://$EC2_IP`:8010/health" -TimeoutSec 5 -ErrorAction Stop
        Ok "API healthy: $($health | ConvertTo-Json -Compress)"
    } catch {
        Fail "API not responding on $EC2_IP`:8010"
    }

    # SSH check
    $keyPath = if ($env:SSH_KEY_PATH) { $env:SSH_KEY_PATH } else { "$env:USERPROFILE\.ssh\VeriCase-Safe.pem" }
    if (Test-Path $keyPath) {
        Write-Host ""
        Write-Host "SSH Access:" -ForegroundColor Yellow
        try {
            $knownHosts = "$env:USERPROFILE\.ssh\known_hosts"
            if (-not (Test-Path $knownHosts)) {
                Warn "known_hosts not found: $knownHosts"
                Info "Run: powershell -ExecutionPolicy Bypass -File .\\vericase\\ops\\setup-ssh.ps1"
                return
            }
            $result = ssh -i "$keyPath" -o ConnectTimeout=5 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$knownHosts" ec2-user@$EC2_IP "echo connected" 2>$null
            if ($result -eq "connected") {
                Ok "SSH connection successful"

                Write-Host ""
                Write-Host "Remote Docker Status:" -ForegroundColor Yellow
                ssh -i "$keyPath" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$knownHosts" ec2-user@$EC2_IP "sudo docker ps --format 'table {{.Names}}\t{{.Status}}'" 2>$null
            } else {
                Fail "SSH connection failed"
                Info "If this is the first connection or the instance host key changed, prime known_hosts:"
                Info "  powershell -ExecutionPolicy Bypass -File .\\vericase\\ops\\setup-ssh.ps1"
            }
        } catch {
            Fail "SSH connection failed"
        }
    } else {
        Warn "SSH key not found: $keyPath"
    }
}

function Diagnose-AWS {
    Write-Host ""
    Write-Host "=== AWS Services Diagnostics ===" -ForegroundColor Cyan
    Write-Host ""

    # AWS CLI configured?
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
        Fail "AWS CLI not installed"
        return
    }

    try {
        $identity = aws sts get-caller-identity 2>$null | ConvertFrom-Json
        Ok "AWS Account: $($identity.Account)"
    } catch {
        Fail "AWS credentials not configured"
        return
    }

    # S3
    Write-Host ""
    Write-Host "S3 Buckets:" -ForegroundColor Yellow
    try {
        $null = aws s3 ls "s3://$S3_BUCKET" 2>$null
        Ok "$S3_BUCKET accessible"
    } catch {
        Fail "$S3_BUCKET not accessible"
    }

    # RDS
    Write-Host ""
    Write-Host "RDS Database:" -ForegroundColor Yellow
    try {
        $rds = aws rds describe-db-instances --query "DBInstances[0].[DBInstanceStatus,Endpoint.Address]" --output text 2>$null
        $parts = $rds -split "`t"
        if ($parts[0] -eq "available") {
            Ok "RDS: $($parts[0])"
            Info "Endpoint: $($parts[1])"
        } else {
            Fail "RDS status: $($parts[0])"
        }
    } catch {
        Fail "Could not check RDS"
    }

    # ElastiCache Redis
    Write-Host ""
    Write-Host "ElastiCache Redis:" -ForegroundColor Yellow
    try {
        $redis = aws elasticache describe-cache-clusters --query "CacheClusters[?contains(CacheClusterId, 'vericase')].[CacheClusterId,CacheClusterStatus]" --output text 2>$null
        $count = ($redis -split "`n").Count
        Ok "Redis clusters: $count"
        Info "Endpoint: $REDIS_HOST"
    } catch {
        Fail "Could not check Redis"
    }

    # OpenSearch
    Write-Host ""
    Write-Host "OpenSearch:" -ForegroundColor Yellow
    try {
        $os = aws opensearch describe-domain --domain-name $OPENSEARCH_DOMAIN --query "DomainStatus.Processing" --output text 2>$null
        if ($os -eq "False") {
            Ok "OpenSearch: active"
        } else {
            Warn "OpenSearch: processing"
        }
    } catch {
        Warn "OpenSearch: not found or error"
    }

    # EKS
    Write-Host ""
    Write-Host "EKS Cluster:" -ForegroundColor Yellow
    try {
        $eks = aws eks describe-cluster --name $EKS_CLUSTER --query "cluster.status" --output text 2>$null
        if ($eks -eq "ACTIVE") {
            Ok "EKS: $eks"
            $nodegroups = aws eks list-nodegroups --cluster-name $EKS_CLUSTER --query "length(nodegroups)" --output text 2>$null
            Info "Node groups: $nodegroups"
        } else {
            Fail "EKS status: $eks"
        }
    } catch {
        Fail "Could not check EKS"
    }

    # Secrets Manager
    Write-Host ""
    Write-Host "Secrets Manager:" -ForegroundColor Yellow
    try {
        $null = aws secretsmanager describe-secret --secret-id "vericase/ai-api-keys" 2>$null
        Ok "vericase/ai-api-keys exists"
    } catch {
        Warn "vericase/ai-api-keys not found"
    }

    # Running EC2 instances
    Write-Host ""
    Write-Host "EC2 Instances:" -ForegroundColor Yellow
    try {
        $instances = aws ec2 describe-instances `
            --filters "Name=instance-state-name,Values=running" `
            --query "Reservations[*].Instances[*].[Tags[?Key=='Name'].Value|[0],PublicIpAddress,InstanceType]" `
            --output text 2>$null
        foreach ($line in ($instances -split "`n")) {
            if ($line.Trim()) {
                $parts = $line -split "`t"
                Info "$($parts[0]): $($parts[1]) ($($parts[2]))"
            }
        }
    } catch {
        Warn "Could not list EC2 instances"
    }
}

# Main
Push-Location "$PSScriptRoot\.."

try {
    switch ($Command) {
        "local" { Diagnose-Local }
        "ec2" { Diagnose-EC2 }
        "aws" { Diagnose-AWS }
        "all" {
            Diagnose-Local
            Diagnose-EC2
            Diagnose-AWS
        }
    }

    Write-Host ""
    Write-Host "=== Diagnostics Complete ===" -ForegroundColor Cyan
    Write-Host ""
} finally {
    Pop-Location
}
