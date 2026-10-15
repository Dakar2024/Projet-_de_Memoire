#!/bin/sh
# Crée un bucket par couche du médaillon et le compte de service d'Airflow (idempotent).
set -e

mc alias set local "http://minio:9000" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
for bucket in raw bronze silver gold; do
  mc mb --ignore-existing "local/${bucket}"
  echo "bucket ${bucket} pret"
done

# Politique limitée aux quatre buckets et aux actions dont Delta Lake a besoin.
cat > /tmp/airflow-lake.json <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": [
        "arn:aws:s3:::raw/*",
        "arn:aws:s3:::bronze/*",
        "arn:aws:s3:::silver/*",
        "arn:aws:s3:::gold/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:GetBucketLocation"],
      "Resource": [
        "arn:aws:s3:::raw",
        "arn:aws:s3:::bronze",
        "arn:aws:s3:::silver",
        "arn:aws:s3:::gold"
      ]
    }
  ]
}
POLICY

# `|| true` : politique déjà présente lors d'un redémarrage.
mc admin policy create local airflow-lake /tmp/airflow-lake.json || true
mc admin user add local "$MINIO_AIRFLOW_USER" "$MINIO_AIRFLOW_PASSWORD"
mc admin policy attach local airflow-lake --user "$MINIO_AIRFLOW_USER" || true
echo "compte de service ${MINIO_AIRFLOW_USER} pret (politique airflow-lake)"
