#!/usr/bin/env bash
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This helper supports Ubuntu systems with apt-get." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  gir1.2-gtk-3.0 \
  gir1.2-webkit2-4.1 \
  libgtk-3-0 \
  libwebkit2gtk-4.1-0 \
  openmpi-bin \
  libopenmpi-dev \
  libhypre-dev
