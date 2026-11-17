#!/usr/bin/env bash
# 9 проверок ЛР4. Запускать из корня репозитория района:
#   ./scripts/check-bus.sh            — набор лежит рядом (kit/)
#   ./scripts/check-bus.sh /путь/к/набору — набор в другом месте
set -euo pipefail
KIT="${1:-$(dirname "$0")/..}"
python3 "$KIT/scripts/check-bus.py" --kit "$KIT" --district "$(pwd)"
