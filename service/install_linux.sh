#!/usr/bin/env bash
# Install SortSmart as a systemd service for the current user.
#   sudo ./service/install_linux.sh /path/to/rules.yaml
set -euo pipefail

CONFIG="$(realpath "${1:-rules.yaml}")"
RUN_AS="${SUDO_USER:-$USER}"
BIN="$(command -v sortsmart || true)"

if [[ -z "$BIN" ]]; then
  echo "sortsmart is not on PATH; run: pip install sortsmart" >&2
  exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "config not found: $CONFIG" >&2
  exit 1
fi

UNIT=/etc/systemd/system/sortsmart.service
cat > "$UNIT" <<EOF
[Unit]
Description=SortSmart file intake watcher
After=network.target

[Service]
Type=simple
User=$RUN_AS
Environment=SORTSMART_CONFIG=$CONFIG
ExecStart=$BIN watch
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now sortsmart.service
systemctl --no-pager status sortsmart.service
echo "Logs: journalctl -u sortsmart -f   (structured logs also in the configured logging.dir)"
