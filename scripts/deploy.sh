#!/usr/bin/env bash
# Development helper: ship this checkout to a T2 MacBook over SSH and run install.sh there.
# The target needs passwordless sudo. Runs the local gate first.
# Usage: scripts/deploy.sh <ssh-host> [install.sh options...]
#   e.g. scripts/deploy.sh my-macbook --update-config --turkish
set -euo pipefail
cd "$(dirname "$0")/.."
host=${1:?usage: scripts/deploy.sh <ssh-host> [install.sh options...]}
shift
./scripts/check.sh
git ls-files -z | xargs -0 tar --no-xattrs --no-mac-metadata -czf - \
  | ssh "$host" 'rm -rf /tmp/better-touchbar && mkdir /tmp/better-touchbar && tar -xzf - -C /tmp/better-touchbar'
ssh "$host" "cd /tmp/better-touchbar && ./install.sh $* && rm -rf /tmp/better-touchbar"
