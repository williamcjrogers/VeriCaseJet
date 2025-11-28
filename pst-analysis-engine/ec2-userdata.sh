#!/bin/bash
set -e

# Update system
apt-get update
apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
systemctl enable docker
systemctl start docker

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create app directory
mkdir -p /opt/vericase
cd /opt/vericase

# Clone or copy your code here (replace with your repo)
# git clone https://github.com/your-org/vericase.git .

# For now, you'll need to scp your files after launch
echo "Ready for deployment. Upload code to /opt/vericase"

# Set up log rotation
cat > /etc/logrotate.d/vericase <<EOF
/opt/vericase/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
EOF
