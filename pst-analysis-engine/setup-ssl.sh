#!/bin/bash
# Setup SSL with Let's Encrypt for VeriCase

DOMAIN="veri-case.com"
EMAIL="your-email@example.com"  # Change this!

echo "Installing Certbot..."
sudo yum install -y certbot python3-certbot-nginx

echo "Obtaining SSL certificate for $DOMAIN..."
sudo certbot certonly --standalone \
  --preferred-challenges http \
  --email $EMAIL \
  --agree-tos \
  --no-eff-email \
  -d $DOMAIN \
  -d www.$DOMAIN \
  -d api.$DOMAIN

echo "Creating certificate directory..."
sudo mkdir -p /etc/nginx/certs

echo "Copying certificates..."
sudo cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/nginx/certs/veri-case-fullchain.pem
sudo cp /etc/letsencrypt/live/$DOMAIN/privkey.pem /etc/nginx/certs/VeriCase-Safe.pem
sudo chmod 644 /etc/nginx/certs/*.pem

echo "Setting up auto-renewal..."
echo "0 0,12 * * * root certbot renew --quiet" | sudo tee -a /etc/crontab > /dev/null

echo "✅ SSL certificates installed!"
echo "Now update docker-compose to include nginx service"
