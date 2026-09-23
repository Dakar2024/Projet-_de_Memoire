#!/bin/sh
set -e

# Une couche du médaillon = un bucket. Idempotent : relancer la stack ne casse rien.
mc alias set local "http://minio:9000" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
for bucket in raw bronze silver gold; do
  mc mb --ignore-existing "local/${bucket}"
  echo "bucket ${bucket} pret"
done

# Compte de service pour Airflow : les tâches n'ont aucune raison de disposer des
# droits root de MinIO. La politique se limite aux quatre buckets du médaillon et
# aux actions dont Delta Lake a besoin (lire, écrire, supprimer, lister, et
# abandonner un envoi multipart interrompu). Une tâche compromise ne peut alors ni
# créer ni supprimer un bucket, ni toucher à la configuration du serveur.
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

# `|| true` sur la création : rejouer la stack retombe sur une politique déjà
# présente, ce qui n'est pas une erreur. Les deux commandes suivantes sont
# idempotentes par nature (`mc admin user add` met à jour le secret).
mc admin policy create local airflow-lake /tmp/airflow-lake.json || true
mc admin user add local "$MINIO_AIRFLOW_USER" "$MINIO_AIRFLOW_PASSWORD"
mc admin policy attach local airflow-lake --user "$MINIO_AIRFLOW_USER" || true
echo "compte de service ${MINIO_AIRFLOW_USER} pret (politique airflow-lake)"
