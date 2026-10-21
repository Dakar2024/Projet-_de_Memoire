# MinIO et mc compilés depuis les sources : les images communautaires ne se tirent plus
# (Docker Hub : dépôts supprimés, quay.io : 401 sans compte, constaté le 20/10/2026).
# Dépôts minio/minio et minio/mc archivés : commits épinglés, un tag peut être déplacé.
# CVE de 2026 corrigées seulement dans AIStor : atténuées par docker/minio/nginx.conf.

FROM golang:1.26.10-alpine3.24@sha256:9ce231b28998b32e116927c61aa5c406183061d4f3f2d61b292c88e7f6bdf7ca AS build
RUN apk add --no-cache git
# Binaires statiques ; GOTOOLCHAIN=local interdit à go.mod de télécharger un autre compilateur.
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
WORKDIR /src

# Dernière version publique (corrige CVE-2025-62506).
ARG MINIO_COMMIT=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
ARG MINIO_VERSION=2025-10-15T17:29:55Z
RUN git init -q minio && cd minio \
 && git fetch -q --depth 1 https://github.com/minio/minio.git "${MINIO_COMMIT}" \
 && git checkout -q FETCH_HEAD \
 && go build -tags kqueue -trimpath \
      -ldflags "$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go "${MINIO_VERSION}")" -o /out/minio

# Dernière version publique de mc.
ARG MC_COMMIT=7394ce0dd2a80935aded936b09fa12cbb3cb8096
ARG MC_VERSION=2025-08-13T08:35:41Z
RUN git init -q mc && cd mc \
 && git fetch -q --depth 1 https://github.com/minio/mc.git "${MC_COMMIT}" \
 && git checkout -q FETCH_HEAD \
 && go build -tags kqueue -trimpath \
      -ldflags "$(MC_RELEASE=RELEASE go run buildscripts/gen-ldflags.go "${MC_VERSION}")" -o /out/mc

# Client seul : minio-init et les scripts de sauvegarde (shell requis par create-buckets.sh).
FROM alpine:3.24.2@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6 AS mc
COPY --from=build /out/mc /usr/bin/mc
ENTRYPOINT ["mc"]

# Serveur ; mc embarqué pour le healthcheck `mc ready local`, comme dans l'image officielle.
FROM mc AS server
COPY --from=build /out/minio /usr/bin/minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
