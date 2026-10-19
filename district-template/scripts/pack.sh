#!/usr/bin/env bash
# Упаковывает репозиторий района для сдачи и обмена (пока нет Git-сервера, Р7).
# Использование (из корня репозитория района): scripts/pack.sh
# Результат: out/dN-код-ДАТА.zip (снимок main) и out/dN-код-ДАТА.bundle (вся история).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
NAME="$(sed -n 's/^name:[[:space:]]*//p' compose.yaml | head -1)"
NAME="${NAME:-$(basename "$PWD")}"
STAMP="$(date +%Y%m%d)"

if [ -n "$(git status --porcelain)" ]; then
  echo "Есть незафиксированные изменения — сначала git add и git commit:" >&2
  git status --short >&2
  exit 1
fi
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "СТОП: файл .env попал в Git. Удалите его из истории и смените пароли." >&2
  exit 1
fi
# Грубая проверка на секреты в отслеживаемых файлах
if git grep -nIE -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' -e '(password|secret|token)[[:space:]]*[:=][[:space:]]*[^[:space:]<$]{8,}' -- . ':!*.example' ':!scripts/pack.sh' >/dev/null; then
  echo "Внимание: похоже на секрет в файлах (проверьте и исправьте, если это не так):" >&2
  git grep -nIE -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' -e '(password|secret|token)[[:space:]]*[:=][[:space:]]*[^[:space:]<$]{8,}' -- . ':!*.example' ':!scripts/pack.sh' >&2 || true
fi

mkdir -p out
git archive --format=zip -o "out/${NAME}-${STAMP}.zip" main
git bundle create -q "out/${NAME}-${STAMP}.bundle" --all
git bundle verify -q "out/${NAME}-${STAMP}.bundle"
ls -l out/"${NAME}-${STAMP}".*
echo "Отправьте оба файла ассистенту (Данилова Мария) — см. ЛР1, раздел «Сдача»."
