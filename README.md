# tradutor

Tradutor de idiomas para o terminal, em Python 3 (apenas biblioteca padrão), inspirado no
`translate-shell` — e melhor que ele em confiabilidade e desempenho: **fallback automático
entre três motores** e **cache local instantâneo**, coisas que o `trans` não tem.

## Por que melhor que o `trans`

| Dimensão | `trans` | `tradutor` |
|---|---|---|
| Confiabilidade | Um motor por chamada; se o Google bloquear, você troca manualmente | Fallback automático Google → MyMemory → LibreTranslate |
| Desempenho | Reconsulta a rede toda vez | Cache SQLite: texto repetido responde na hora, sem rede |
| Privacidade granular | — | `--no-cache` para textos sensíveis (nada gravado em disco) |
| Manutenção | ~6 mil linhas de AWK | Script Python único e legível |

## Instalação

### Debian / Ubuntu — via apt (recomendado)

```bash
curl -fsSL https://rochasgabriela.github.io/tradutor/install.sh | sudo bash
```

O instalador adiciona o repositório APT assinado do projeto e instala o pacote.
Depois disso o tradutor é gerenciado pelo apt:

```bash
apt install tradutor   # instalar (já feito pelo instalador)
apt upgrade            # receber atualizações
apt remove tradutor    # desinstalar
```

### Sem root (qualquer Linux)

```bash
curl -fsSL https://rochasgabriela.github.io/tradutor/install.sh | bash -s -- --local
```

Instala em `~/.local/bin/tradutor` + man page em `~/.local/share/man`.

### Manual

```bash
git clone https://github.com/rochasgabriela/tradutor
mkdir -p ~/.local/bin ~/.local/share/man/man1
cp tradutor/tradutor.py ~/.local/bin/tradutor && chmod +x ~/.local/bin/tradutor
cp tradutor/tradutor.1 ~/.local/share/man/man1/
```

Requisitos: Python 3.7+ e internet (os motores de tradução são serviços online).
`~/.local/bin` precisa estar no `PATH` (o `.profile` padrão do Debian/Ubuntu já o inclui quando existe).

## Uso

```bash
tradutor                                  # ajuda rápida com exemplos
tradutor en:pt "hello world"              # inglês → português
tradutor :pt "good morning"               # detecta o idioma de origem
tradutor pt "the house is big"            # um código só = destino (origem auto)
echo "hi" | tradutor -b :pt               # pipe com saída limpa
tradutor en:pt manual.txt -o manual_pt.txt  # traduz arquivo → arquivo
tradutor --history 5                      # últimas traduções
```

Idiomas: códigos ISO 639-1 (`en`, `pt`, `es`, `ja`, ...) com variante opcional (`pt-BR`, `en-GB`).
Guia completo: `tradutor --manual` ou `man tradutor`.

## Motores e fallback

1. **Google** — endpoint `dict-chrome-ex` (o mesmo do Chrome; suporta auto-detect)
2. **MyMemory** — exige origem explícita; textos de até 500 caracteres (pulado fora disso)
3. **LibreTranslate** — instância pública

Se um motor falha (rede, HTTP 429, formato inesperado), o próximo é tentado automaticamente
e um aviso aparece no stderr. Com `--engine`, só o motor escolhido é usado, sem fallback.

## Cache e privacidade

- Cache em `~/.cache/tradutor/cache.db` (SQLite), indexado por motor + idiomas + texto.
  Repetições são instantâneas e aparecem marcadas como `(em cache)`.
- `--no-cache` não lê nem grava nada — indicado para textos sensíveis.
- O texto traduzido trafega por HTTPS para o motor usado (serviço de terceiros).

## Saída

- **Padrão:** tradução + linha de status (`[google] en → pt (detectado: en) (em cache)`)
- **`-b`:** somente a tradução — ideal para scripts e pipes
- **`-o`:** tradução gravada no arquivo; terminal mostra apenas o resumo

## Códigos de saída

| Código | Significado |
|---|---|
| 0 | sucesso |
| 1 | argumentos/texto inválidos ou arquivo inexistente |
| 2 | todos os motores falharam |
| 3 | limite de requisições (429) em todos os motores |
| 4 | falha ao gravar o arquivo de saída (`-o`) |

## Estrutura

```
tradutor.py                       script único (CLI, motores, fallback, cache, chunking, manual)
tradutor.1                        man page
install.sh                        instalador de 1 comando (apt ou local)
packaging/build-deb.sh            gera o pacote .deb
packaging/build-apt-repo.sh       monta e assina o repositório APT
packaging/keyring.asc             chave pública de assinatura do repositório
.github/workflows/release.yml     publica .deb + repo APT a cada tag v*
LICENSE                           MIT
README.md                         este arquivo
```

## Publicando uma nova versão (mantenedor)

1. Ajuste o que precisar e suba na `main`.
2. Crie a tag: `git tag v1.1 && git push origin v1.1`.
3. O GitHub Actions empacota o `.deb`, assina o repositório APT com a chave
   `GPG_PRIVATE_KEY` (GitHub Secrets) e publica em `gh-pages` + GitHub Release.
4. Usuários recebem a nova versão no próximo `apt upgrade`.

A chave privada de assinatura vive em dois lugares: no chaveiro GPG local do
mantenedor e no secret `GPG_PRIVATE_KEY` do repositório. Ela assina os
metadados do repositório APT — trate como segredo sensível e rotacione se
vazar.

## Limitações conhecidas

- Os motores dependem de serviços online; sem internet, nenhum funciona (um motor offline
  neural, no estilo Argos Translate, é candidato natural para a v2).
- O endpoint do Google é não oficial e pode mudar; o fallback mitiga isso.
- Múltiplas linhas em branco consecutivas são normalizadas para uma na saída de textos longos.
