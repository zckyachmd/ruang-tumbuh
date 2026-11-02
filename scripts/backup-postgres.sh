#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${BACKUP_AGE_RECIPIENT:?Set BACKUP_AGE_RECIPIENT to an age public recipient}"
command -v docker >/dev/null
command -v age >/dev/null

backup_dir=${BACKUP_DIR:-backups}
mkdir -p "$backup_dir"
temp_dir=$(mktemp -d "$backup_dir/.ruang-backup.XXXXXXXX")
temp_file="$temp_dir/backup.dump.age"
cleanup() {
  rm -f "$temp_file"
  rmdir "$temp_dir"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

stamp=$(date -u +%Y%m%dT%H%M%SZ)
suffix=${temp_dir##*.}
destination="$backup_dir/ruang-$stamp-$suffix.dump.age"

docker compose exec -T db pg_dump -U ruang -d ruang -Fc --no-owner --no-acl \
  | age -r "$BACKUP_AGE_RECIPIENT" > "$temp_file"
ln "$temp_file" "$destination"
printf 'Encrypted backup written: %s\n' "$destination"
