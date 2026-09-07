#!/usr/bin/env bash
# Instalador do tradutor.
#
# Via APT (recomendado, como root ou com sudo):
#   curl -fsSL https://rochasgabriela.github.io/tradutor/install.sh | sudo bash
#
# Local, sem root (não usa apt):
#   curl -fsSL https://rochasgabriela.github.io/tradutor/install.sh | bash -s -- --local
#
set -euo pipefail

OWNER="rochasgabriela"
REPO="tradutor"
PAGES="https://$OWNER.github.io/$REPO"
RAW="https://raw.githubusercontent.com/$OWNER/$REPO/main"
KEYRING="/usr/share/keyrings/tradutor-archive-keyring.gpg"
SOURCES="/etc/apt/sources.list.d/tradutor.sources"

MODE="auto"
for arg in "$@"; do
    case "$arg" in
        --local) MODE="local" ;;
        *) echo "tradutor installer: opção desconhecida: $arg" >&2; exit 1 ;;
    esac
done

say() { printf '\n\033[1mtradutor installer:\033[0m %s\n' "$*"; }
die() { printf '\n\033[1merro:\033[0m %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl é necessário (instale com o gerenciador do seu sistema)"

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else return 1
    fi
}

install_apt() {
    say "configurando repositório APT: $PAGES"
    as_root mkdir -p /usr/share/keyrings /etc/apt/sources.list.d
    KEYTMP="$(mktemp)"
    trap 'rm -f "$KEYTMP"' EXIT
    curl -fsSL "$PAGES/key.gpg" -o "$KEYTMP"
    as_root rm -f "$KEYRING"
    as_root gpg --dearmor -o "$KEYRING" "$KEYTMP"

    as_root tee "$SOURCES" >/dev/null <<EOF
Types: deb
URIs: $PAGES
Suites: stable
Components: main
Signed-By: $KEYRING
EOF

    say "atualizando índices e instalando o pacote"
    as_root apt-get update -qq
    as_root apt-get install -y tradutor
    say "instalado via apt! atualizações chegam com 'apt upgrade'"
    say "teste: tradutor :pt \"hello world\""
}

install_local() {
    say "instalação local (sem root) em ~/.local/bin"
    mkdir -p "$HOME/.local/bin" "$HOME/.local/share/man/man1"
    curl -fsSL "$RAW/tradutor.py" -o "$HOME/.local/bin/tradutor"
    chmod +x "$HOME/.local/bin/tradutor"
    curl -fsSL "$RAW/tradutor.1" | gzip -n > "$HOME/.local/share/man/man1/tradutor.1.gz"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) say "adicione ao PATH: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
    say "pronto! teste: tradutor :pt \"hello world\""
}

if [ "$MODE" = "local" ]; then
    install_local
elif command -v apt-get >/dev/null 2>&1 && as_root true 2>/dev/null; then
    install_apt
else
    say "sem apt ou sem root — usando instalação local"
    install_local
fi
