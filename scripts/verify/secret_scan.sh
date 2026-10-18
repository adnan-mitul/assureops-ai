#!/usr/bin/env bash
# Fails if tracked files contain credential-shaped values. Local test values live only in git-ignored files.
set -euo pipefail
cd "$(dirname "$0")/../.."
pattern='(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-[A-Za-z0-9-]{10,})'
if git ls-files -z | xargs -0 grep -I -n -E "$pattern" -- 2>/dev/null; then
  echo "credential-shaped value found in tracked files" >&2
  exit 1
fi
for f in infra/compose/dev.env apps/customer-web/.env.local apps/staff-web/.env.local var/demo-actors; do
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then echo "local secret file is tracked: $f" >&2; exit 1; fi
done
echo "secret scan: clean"
