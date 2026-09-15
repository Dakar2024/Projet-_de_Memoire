#!/bin/sh
set -e

# Une couche du médaillon = un bucket. Idempotent : relancer la stack ne casse rien.
mc alias set local "http://minio:9000" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
for bucket in raw bronze silver gold; do
  mc mb --ignore-existing "local/${bucket}"
  echo "bucket ${bucket} pret"
done
