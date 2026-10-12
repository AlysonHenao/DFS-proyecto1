#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CERTS="$ROOT/certs"
mkdir -p "$CERTS"

openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout "$CERTS/ca.key" -out "$CERTS/ca.crt" \
  -subj "//CN=DFSha local CA"

openssl req -newkey rsa:2048 -nodes \
  -keyout "$CERTS/server.key" -out "$CERTS/server.csr" \
  -subj "//CN=DFSha server"

cat > "$CERTS/server.ext" <<'EOF'
subjectAltName=DNS:control-leader,DNS:control-follower,DNS:datanode1,DNS:datanode2,DNS:datanode3,DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
EOF

openssl x509 -req -days 365 \
  -in "$CERTS/server.csr" -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" \
  -CAcreateserial -out "$CERTS/server.crt" -extfile "$CERTS/server.ext"

rm -f "$CERTS/server.csr" "$CERTS/server.ext" "$CERTS/ca.srl"
echo "Certificates written to $CERTS"
