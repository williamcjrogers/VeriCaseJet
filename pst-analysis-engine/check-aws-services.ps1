Write-Host "Checking AWS Services in eu-west-2..." -ForegroundColor Cyan
Write-Host ""

# Check S3 Buckets
Write-Host "=== S3 Buckets ===" -ForegroundColor Yellow
$s3Buckets = aws s3 ls 2>$null | Select-String "vericase"
if ($s3Buckets) {
    $s3Buckets
} else {
    Write-Host "No 'vericase' buckets found or AWS CLI not configured." -ForegroundColor Red
}
Write-Host ""

# Check IAM Role
Write-Host "=== IAM Role (vericase-eks-pod-role) ===" -ForegroundColor Yellow
try {
    aws iam get-role --role-name vericase-eks-pod-role --query 'Role.Arn' --output text 2>$null
    
    # Check for S3 specific policy
    Write-Host "Checking for S3 policies..."
    aws iam list-attached-role-policies --role-name vericase-eks-pod-role --output table 2>$null
} catch {
    Write-Host "Role 'vericase-eks-pod-role' not found or permission denied." -ForegroundColor Red
}
Write-Host ""

# Check RDS Instances
Write-Host "=== RDS Instances ===" -ForegroundColor Yellow
aws rds describe-db-instances --region eu-west-2 --query 'DBInstances[*].[DBInstanceIdentifier,DBInstanceStatus,Endpoint.Address]' --output table 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "No RDS instances found." -ForegroundColor Red }
Write-Host ""

# Check EKS Cluster
Write-Host "=== EKS Cluster ===" -ForegroundColor Yellow
aws eks list-clusters --region eu-west-2 --output table 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "No EKS clusters found." -ForegroundColor Red }
Write-Host ""

# Check Kubernetes Nodes
Write-Host "=== Kubernetes Nodes ===" -ForegroundColor Yellow
kubectl get nodes 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "kubectl not connected or failed." -ForegroundColor Red }
Write-Host ""

Write-Host "Done! If you see errors, ensure you are logged into AWS CLI (aws configure) and kubectl is set up." -ForegroundColor Cyan
