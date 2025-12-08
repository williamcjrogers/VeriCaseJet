# Diagnose SSL/TLS Certificate Issues for veri-case.com
# Run this script to identify why HTTPS isn't working

$DOMAIN = "veri-case.com"
$CERT_ARN = "arn:aws:acm:eu-west-2:526015377510:certificate/fa1c323e-4062-4480-9234-b0c7476a23d0"
$REGION = "eu-west-2"
$ELB_DNS = "a61989df377ff43a5b36d956e82baee8-21465387.eu-west-2.elb.amazonaws.com"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "VeriCase SSL/TLS Diagnostic" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# 1. Check ACM Certificate Status
Write-Host "1️⃣  Checking ACM Certificate Status..." -ForegroundColor Yellow
try {
    $cert = aws acm describe-certificate --certificate-arn $CERT_ARN --region $REGION 2>&1
    if ($LASTEXITCODE -eq 0) {
        $certObj = $cert | ConvertFrom-Json
        $status = $certObj.Certificate.Status
        $domains = $certObj.Certificate.DomainValidationOptions
        
        Write-Host "   Certificate Status: " -NoNewline
        if ($status -eq "ISSUED") {
            Write-Host "$status ✅" -ForegroundColor Green
        } elseif ($status -eq "PENDING_VALIDATION") {
            Write-Host "$status ⚠️" -ForegroundColor Yellow
            Write-Host "   ⚠️  Certificate is awaiting DNS validation!" -ForegroundColor Yellow
        } else {
            Write-Host "$status ❌" -ForegroundColor Red
        }
        
        Write-Host "   Domains covered:"
        foreach ($domain in $domains) {
            Write-Host "     - $($domain.DomainName): $($domain.ValidationStatus)" -ForegroundColor White
        }
    }
} catch {
    Write-Host "   ❌ Could not retrieve certificate. It may not exist." -ForegroundColor Red
    Write-Host "   Error: $_" -ForegroundColor Gray
}

Write-Host ""

# 2. Check DNS Resolution
Write-Host "2️⃣  Checking DNS for $DOMAIN..." -ForegroundColor Yellow
try {
    $dns = Resolve-DnsName $DOMAIN -ErrorAction SilentlyContinue
    if ($dns) {
        Write-Host "   DNS resolves to:" -ForegroundColor White
        foreach ($record in $dns) {
            if ($record.Type -eq "A") {
                Write-Host "     A Record: $($record.IPAddress)" -ForegroundColor White
            } elseif ($record.Type -eq "CNAME") {
                Write-Host "     CNAME: $($record.NameHost)" -ForegroundColor White
            }
        }
        
        # Check if it points to the ELB
        $cnameMatches = $dns | Where-Object { $_.NameHost -like "*elb.amazonaws.com*" }
        if ($cnameMatches) {
            Write-Host "   ✅ DNS correctly points to AWS ELB" -ForegroundColor Green
        } else {
            Write-Host "   ⚠️  DNS may not point to the correct load balancer" -ForegroundColor Yellow
            Write-Host "   Expected: $ELB_DNS" -ForegroundColor Gray
        }
    } else {
        Write-Host "   ❌ DNS does not resolve! No DNS records found." -ForegroundColor Red
        Write-Host "   You need to add a CNAME or A record pointing to:" -ForegroundColor Yellow
        Write-Host "   $ELB_DNS" -ForegroundColor White
    }
} catch {
    Write-Host "   ❌ DNS resolution failed: $_" -ForegroundColor Red
}

Write-Host ""

# 3. Check Kubernetes Ingress
Write-Host "3️⃣  Checking Kubernetes Ingress..." -ForegroundColor Yellow
try {
    $ingress = kubectl get ingress -n vericase -o json 2>&1
    if ($LASTEXITCODE -eq 0) {
        $ingressObj = $ingress | ConvertFrom-Json
        if ($ingressObj.items.Count -gt 0) {
            Write-Host "   Ingress found ✅" -ForegroundColor Green
            foreach ($ing in $ingressObj.items) {
                Write-Host "     Name: $($ing.metadata.name)"
                Write-Host "     Hosts: $($ing.spec.rules.host -join ', ')"
                $addr = $ing.status.loadBalancer.ingress.hostname
                Write-Host "     LoadBalancer: $addr" -ForegroundColor White
            }
        } else {
            Write-Host "   ❌ No ingress found in vericase namespace!" -ForegroundColor Red
            Write-Host "   Run: kubectl apply -f vericase/k8s/k8s-ingress.yaml" -ForegroundColor Yellow
        }
    } else {
        Write-Host "   ⚠️  Could not connect to Kubernetes cluster" -ForegroundColor Yellow
        Write-Host "   Make sure kubectl is configured for vericase-cluster" -ForegroundColor Gray
    }
} catch {
    Write-Host "   ⚠️  kubectl not available or not configured: $_" -ForegroundColor Yellow
}

Write-Host ""

# 4. Test HTTPS Connection
Write-Host "4️⃣  Testing HTTPS Connection..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "https://$DOMAIN" -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    Write-Host "   ✅ HTTPS works! Status: $($response.StatusCode)" -ForegroundColor Green
} catch {
    $errMsg = $_.Exception.Message
    if ($errMsg -like "*SSL*" -or $errMsg -like "*TLS*" -or $errMsg -like "*certificate*") {
        Write-Host "   ❌ SSL/TLS Error: $errMsg" -ForegroundColor Red
    } elseif ($errMsg -like "*name or service*" -or $errMsg -like "*host*") {
        Write-Host "   ❌ DNS/Host Error: $errMsg" -ForegroundColor Red  
    } else {
        Write-Host "   ❌ Connection Error: $errMsg" -ForegroundColor Red
    }
}

Write-Host ""

# 5. Test HTTP Connection (ELB direct)
Write-Host "5️⃣  Testing HTTP to ELB directly..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://$ELB_DNS" -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    Write-Host "   ✅ ELB reachable! Status: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "   The app is running. SSL/DNS is the issue." -ForegroundColor Yellow
} catch {
    Write-Host "   ❌ ELB not reachable: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Recommended Actions:" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host @"

If certificate is PENDING_VALIDATION:
  → Add CNAME validation records to your DNS provider

If DNS doesn't resolve:
  → Add a CNAME record:
    Name: veri-case.com (or @)
    Value: $ELB_DNS

If ingress is not deployed:
  → Run: kubectl apply -f vericase/k8s/k8s-ingress.yaml

WORKAROUND - Use the direct ELB URL (HTTP):
  → http://$ELB_DNS/ui/pst-upload.html?projectId=dca0d854-1655-4498-97f3-399b47a4d65f

"@ -ForegroundColor White

