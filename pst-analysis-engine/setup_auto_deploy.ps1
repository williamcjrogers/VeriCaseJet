# Setup automatic deployment from GitHub
$EC2_IP = "18.130.216.34"
$KEY_PATH = "C:\Users\William\Documents\Projects\VeriCase Analysis\VeriCase-Safe.pem"

Write-Host "Setting up auto-deploy webhook on EC2..." -ForegroundColor Yellow

$setupScript = @'
# Install webhook listener
sudo yum install -y git

# Create webhook script
cat > ~/vericase/deploy.sh << 'EOF'
#!/bin/bash
cd ~/vericase
echo "$(date): Pulling latest image from Docker Hub..."
sudo docker-compose pull
echo "$(date): Restarting services..."
sudo docker-compose up -d
echo "$(date): Deployment complete"
EOF

chmod +x ~/vericase/deploy.sh

# Create systemd service for webhook
sudo tee /etc/systemd/system/vericase-webhook.service > /dev/null << 'EOF'
[Unit]
Description=VeriCase Auto Deploy Webhook
After=network.target

[Service]
Type=simple
User=ec2-user
ExecStart=/usr/bin/python3 /home/ec2-user/vericase/webhook_listener.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Create webhook listener
cat > ~/vericase/webhook_listener.py << 'EOF'
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess
import json

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/deploy':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            
            try:
                data = json.loads(body)
                # Verify it's from Docker Hub
                if 'push_data' in data or 'repository' in data:
                    subprocess.Popen(['/home/ec2-user/vericase/deploy.sh'])
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'Deployment triggered')
                else:
                    self.send_response(400)
                    self.end_headers()
            except:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 9000), WebhookHandler)
    print('Webhook listener running on port 9000')
    server.serve_forever()
EOF

# Enable and start webhook service
sudo systemctl daemon-reload
sudo systemctl enable vericase-webhook
sudo systemctl start vericase-webhook

# Open port 9000 for webhook
sudo firewall-cmd --permanent --add-port=9000/tcp 2>/dev/null || true
sudo firewall-cmd --reload 2>/dev/null || true

echo "Webhook listener installed and running on port 9000"
echo "Configure Docker Hub webhook: http://18.130.216.34:9000/deploy"
'@

ssh -i $KEY_PATH ec2-user@$EC2_IP $setupScript

Write-Host "`nAuto-deploy setup complete!" -ForegroundColor Green
Write-Host "Add this webhook URL to Docker Hub:" -ForegroundColor Cyan
Write-Host "http://18.130.216.34:9000/deploy" -ForegroundColor Yellow
Write-Host "`nSteps to configure Docker Hub webhook:" -ForegroundColor Cyan
Write-Host "1. Go to https://hub.docker.com/repository/docker/wcjrogers/vericase-api/webhooks"
Write-Host "2. Add webhook URL: http://18.130.216.34:9000/deploy"
Write-Host "3. Every push will auto-deploy to EC2"
