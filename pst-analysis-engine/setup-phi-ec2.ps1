# Setup Phi-4 on EC2 with Ollama
param(
    [string]$InstanceType = "g5.xlarge",
    [string]$KeyName = "vericase-key"
)

Write-Host "🚀 Setting up Phi-4 on EC2..." -ForegroundColor Green

# Create security group for Ollama
Write-Host "🔐 Creating security group..." -ForegroundColor Blue

$SecurityGroupId = aws ec2 create-security-group `
    --group-name "vericase-phi-sg" `
    --description "VeriCase Phi-4 Ollama access" `
    --query 'GroupId' --output text

# Allow SSH and Ollama port
aws ec2 authorize-security-group-ingress `
    --group-id $SecurityGroupId `
    --protocol tcp --port 22 --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress `
    --group-id $SecurityGroupId `
    --protocol tcp --port 11434 --cidr 0.0.0.0/0

Write-Host "✅ Security group created: $SecurityGroupId" -ForegroundColor Green

# User data script for EC2
$UserData = @"
#!/bin/bash
yum update -y
yum install -y docker

# Start Docker
systemctl start docker
systemctl enable docker
usermod -a -G docker ec2-user

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
systemctl start ollama
systemctl enable ollama

# Wait for Ollama to start
sleep 10

# Pull Phi-4 model
ollama pull phi4:latest

# Configure Ollama to accept external connections
echo 'OLLAMA_HOST=0.0.0.0:11434' >> /etc/environment
systemctl restart ollama

# Create health check endpoint
cat > /home/ec2-user/health.sh << 'EOF'
#!/bin/bash
curl -s http://localhost:11434/api/tags | jq -r '.models[].name' | grep -q phi4 && echo "Phi-4 Ready" || echo "Phi-4 Loading"
EOF
chmod +x /home/ec2-user/health.sh
"@

$UserDataEncoded = [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($UserData))

# Launch EC2 instance
Write-Host "🖥️ Launching EC2 instance..." -ForegroundColor Blue

$InstanceId = aws ec2 run-instances `
    --image-id ami-0c02fb55956c7d316 `
    --instance-type $InstanceType `
    --key-name $KeyName `
    --security-group-ids $SecurityGroupId `
    --user-data $UserDataEncoded `
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=VeriCase-Phi4},{Key=Purpose,Value=AI-Model}]" `
    --query 'Instances[0].InstanceId' --output text

Write-Host "✅ Instance launched: $InstanceId" -ForegroundColor Green
Write-Host "⏳ Waiting for instance to be ready..." -ForegroundColor Yellow

# Wait for instance to be running
aws ec2 wait instance-running --instance-ids $InstanceId

# Get public IP
$PublicIP = aws ec2 describe-instances `
    --instance-ids $InstanceId `
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text

Write-Host "🎉 Phi-4 EC2 Setup Complete!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Blue
Write-Host "Instance ID: $InstanceId" -ForegroundColor White
Write-Host "Public IP: $PublicIP" -ForegroundColor White
Write-Host "Ollama URL: http://$PublicIP:11434" -ForegroundColor White
Write-Host "Security Group: $SecurityGroupId" -ForegroundColor White

Write-Host "`n⏳ Model Loading (5-10 minutes):" -ForegroundColor Yellow
Write-Host "SSH: ssh -i $KeyName.pem ec2-user@$PublicIP" -ForegroundColor White
Write-Host "Check: curl http://$PublicIP:11434/api/tags" -ForegroundColor White

# Update VeriCase config
$PhiConfig = @"

# Phi-4 on EC2 Configuration
PHI_ENABLED=true
PHI_ENDPOINT=http://$PublicIP:11434
PHI_MODEL=phi4:latest
PHI_INSTANCE_ID=$InstanceId
"@

$PhiConfig | Out-File -FilePath ".env.phi" -Encoding UTF8 -Append

Write-Host "`n📝 Configuration saved to .env.phi" -ForegroundColor Green
Write-Host "Add these lines to your .env file when ready!" -ForegroundColor Yellow