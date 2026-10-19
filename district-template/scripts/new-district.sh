#!/usr/bin/env bash
# Превращает копию шаблона в репозиторий района.
# Использование (из каталога шаблона):
#   scripts/new-district.sh 4 bank "Банк"
# Результат: каталог ../d4-bank с Git-репозиторием и первым коммитом.
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Использование: $0 <номер 1-8> <код латиницей> \"<название по-русски>\"" >&2
  echo "Пример:        $0 4 bank \"Банк\"" >&2
  exit 1
fi
N="$1"; CODE="$2"; NAME="$3"
[[ "$N" =~ ^[1-9]$ ]] || { echo "Номер района — одна цифра 1–9" >&2; exit 1; }
[[ "$CODE" =~ ^[a-z][a-z0-9-]*$ ]] || { echo "Код — строчная латиница, цифры, дефис (Р1)" >&2; exit 1; }

git config user.name >/dev/null || { echo "Сначала настройте Git (ЛР0, шаг 2): git config --global user.name \"Фамилия Имя\"" >&2; exit 1; }

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="$(dirname "$SRC")/d${N}-${CODE}"
[ -e "$DST" ] && { echo "Каталог $DST уже существует" >&2; exit 1; }

cp -r "$SRC" "$DST"
rm -rf "$DST/.git"
cd "$DST"

# Подставляем номер, код и название во все текстовые файлы
grep -rlI --exclude-dir=.git -e '__N__' -e '__CODE__' -e '__NAME__' . | while IFS= read -r f; do
  N="$N" CODE="$CODE" NAME="$NAME" perl -pi -e 's/__N__/$ENV{N}/g; s/__CODE__/$ENV{CODE}/g; s/__NAME__/$ENV{NAME}/g' "$f"
done

# Локальный .env со случайным паролем базы (в Git не попадёт)
if command -v openssl >/dev/null; then PW="$(openssl rand -hex 16)"; else PW="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"; fi
sed "s/^DB_PASSWORD=.*/DB_PASSWORD=${PW}/" .env.example > .env
chmod 600 .env

git init -q -b main
git add -A
git commit -q -m "Каркас района ${N} — ${NAME} из шаблона district-template"
echo "Готово: $DST"
echo "Дальше: cd \"$DST\" && docker compose up --build -d && curl -s http://127.0.0.1:8080/health"
