#!/bin/bash

echo "=================================="
echo "HomeDrive - Let's Encrypt Setup"
echo "=================================="
echo ""
echo "This will obtain a free SSL certificate from Let's Encrypt."
echo ""
echo "Requirements:"
echo "  1. A domain name pointing to this server"
echo "  2. Port 80 must be open to the internet"
echo "  3. Port 443 must be available"
echo ""
read -p "Domain name (e.g., homedrive.example.com): " DOMAIN
read -p "Email for renewal notifications: " EMAIL

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Error: Domain and email are required"
    exit 1
fi

echo ""
echo "Obtaining certificate for $DOMAIN..."
echo ""

# Stop HomeDrive if running on port 80
sudo systemctl stop homedrive 2>/dev/null || true

# Run certbot
sudo certbot certonly --standalone \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive

if [ $? -eq 0 ]; then
    CERT_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    KEY_PATH="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
    
    echo ""
    echo "=================================="
    echo "Certificate obtained successfully!"
    echo "=================================="
    echo ""
    echo "Certificate: $CERT_PATH"
    echo "Private Key: $KEY_PATH"
    echo ""
    echo "To use with HomeDrive, add to systemd service:"
    echo ""
    echo "  Environment=\"HOMEDRIVE_CERT=$CERT_PATH\""
    echo "  Environment=\"HOMEDRIVE_KEY=$KEY_PATH\""
    echo "  Environment=\"HOMEDRIVE_PORT=443\""
    echo ""
    echo "Or export before running:"
    echo ""
    echo "  export HOMEDRIVE_CERT=$CERT_PATH"
    echo "  export HOMEDRIVE_KEY=$KEY_PATH"
    echo "  export HOMEDRIVE_PORT=443"
    echo "  sudo ./homedrive"
    echo ""
    echo "Auto-renewal is configured via certbot timer."
    echo ""
else
    echo ""
    echo "Failed to obtain certificate."
    echo "Please check:"
    echo "  - Domain DNS is pointing to this server"
    echo "  - Port 80 is open and accessible"
    echo "  - No other service is using port 80"
    exit 1
fi
