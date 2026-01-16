#!/bin/bash

# Generate self-signed SSL certificate for HTTPS
echo "Generating self-signed SSL certificate..."

CERT_DIR="$HOME/.homedrive/certs"
mkdir -p "$CERT_DIR"

openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -days 365 \
    -subj "/CN=homedrive.local"

echo "Certificate generated at:"
echo "  Cert: $CERT_DIR/cert.pem"
echo "  Key:  $CERT_DIR/key.pem"
echo ""
echo "To enable HTTPS, set these environment variables:"
echo "  export HOMEDRIVE_CERT=$CERT_DIR/cert.pem"
echo "  export HOMEDRIVE_KEY=$CERT_DIR/key.pem"
echo ""
echo "Then restart HomeDrive"
