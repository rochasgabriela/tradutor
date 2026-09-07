#!/usr/bin/env bash
# Empacota o tradutor como .deb: packaging/build-deb.sh <versão>
# Saída: tradutor_<versão>_all.deb no diretório raiz do projeto.
set -euo pipefail

VERSION="${1:?uso: build-deb.sh <versão> (ex.: 1.0)}"
if [[ ! "$VERSION" =~ ^[0-9][0-9A-Za-z.+~-]*$ ]]; then
    echo "erro: versão inválida para dpkg: $VERSION" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

install -Dm755 "$ROOT/tradutor.py" "$STAGE/usr/bin/tradutor"
install -Dm644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/tradutor/copyright"
install -d -m755 "$STAGE/usr/share/man/man1" "$STAGE/usr/share/doc/tradutor"
gzip -n -9 -c "$ROOT/tradutor.1" > "$STAGE/usr/share/man/man1/tradutor.1.gz"

mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: tradutor
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.7)
Installed-Size: $(du -sk "$STAGE/usr" | cut -f1)
Maintainer: rochasgabriela <gslogger00@gmail.com>
Homepage: https://github.com/rochasgabriela/tradutor
Description: tradutor de idiomas para o terminal
 Traduz textos, arquivos e a entrada padrão entre idiomas direto do
 terminal, com fallback automático entre Google, MyMemory e
 LibreTranslate e cache local instantâneo (SQLite).
 .
 Motores e fallback automáticos garantem tradução mesmo quando um
 serviço falha; --no-cache permite uso sem gravar nada em disco.
EOF

cat > "$STAGE/DEBIAN/changelog" <<EOF
tradutor ($VERSION) stable; urgency=medium

  * Release $VERSION.

 -- rochasgabriela <gslogger00@gmail.com>  $(date -R)
EOF
install -Dm644 "$STAGE/DEBIAN/changelog" "$STAGE/usr/share/doc/tradutor/changelog"
gzip -n -9 "$STAGE/usr/share/doc/tradutor/changelog"
rm "$STAGE/DEBIAN/changelog"

dpkg-deb --root-owner-group --build "$STAGE" "$ROOT/tradutor_${VERSION}_all.deb"
echo "ok: $(ls "$ROOT"/tradutor_${VERSION}_all.deb)"
