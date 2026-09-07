#!/usr/bin/env bash
# Monta o repositório APT assinado:
#   packaging/build-apt-repo.sh <pacote.deb> <dir-saída> [id-da-chave-gpg]
# Estrutura gerada: pool/ com o .deb + dists/stable/ com metadados
# assinados (Release, Release.gpg, InRelease).
set -euo pipefail

DEB="${1:?uso: build-apt-repo.sh <pacote.deb> <dir-saída> [key-id]}"
OUT="${2:?uso: build-apt-repo.sh <pacote.deb> <dir-saída> [key-id]}"
KEYID="${3:-Tradutor APT Archive}"

command -v apt-ftparchive >/dev/null || { echo "erro: apt-ftparchive não encontrado (pacote apt-utils)" >&2; exit 1; }
command -v gpg >/dev/null || { echo "erro: gpg não encontrado" >&2; exit 1; }
[ -f "$DEB" ] || { echo "erro: pacote não encontrado: $DEB" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/pool/main/t/tradutor"
mkdir -p "$OUT/dists/stable/main/binary-all"
mkdir -p "$OUT/dists/stable/main/binary-amd64"
cp "$DEB" "$OUT/pool/main/t/tradutor/"

cd "$OUT"
apt-ftparchive packages pool > dists/stable/main/binary-all/Packages
gzip -n -9 < dists/stable/main/binary-all/Packages > dists/stable/main/binary-all/Packages.gz
cp dists/stable/main/binary-all/Packages dists/stable/main/binary-amd64/Packages
cp dists/stable/main/binary-all/Packages.gz dists/stable/main/binary-amd64/Packages.gz

cd dists/stable
rm -f Release InRelease Release.gpg
apt-ftparchive \
    -o APT::FTPArchive::Release::Origin="tradutor" \
    -o APT::FTPArchive::Release::Label="tradutor" \
    -o APT::FTPArchive::Release::Suite="stable" \
    -o APT::FTPArchive::Release::Codename="stable" \
    -o APT::FTPArchive::Release::Architectures="all amd64" \
    -o APT::FTPArchive::Release::Components="main" \
    -o APT::FTPArchive::Release::Description="Repositório APT do tradutor" \
    release . > Release.tmp
mv Release.tmp Release

gpg --batch --yes --pinentry-mode loopback --local-user "$KEYID" \
    --armor --detach-sign --output Release.gpg Release
gpg --batch --yes --pinentry-mode loopback --local-user "$KEYID" \
    --clearsign --output InRelease Release

echo "ok: repositório APT em $OUT"
