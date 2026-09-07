#!/usr/bin/env python3
"""tradutor — tradutor de idiomas para o terminal.

Motores: Google (dict-chrome-ex) → MyMemory → LibreTranslate, com
fallback automático e cache local em SQLite. Apenas stdlib.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

VERSION = "1.0"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 10
ENGINE_ORDER = ("google", "mymemory", "libre")
GOOGLE_URL = "https://clients5.google.com/translate_a/t"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
LIBRE_URL = "https://translate.disroot.org/translate"
MYMEMORY_MAX = 500
CHUNK_MAX = {"google": 4000, "mymemory": MYMEMORY_MAX, "libre": 4500}
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "tradutor"
CACHE_DB = CACHE_DIR / "cache.db"
ISO_639_1 = frozenset(
    """aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch
    co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga
    gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja
    jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv
    mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or
    os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr
    ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi
    vo wa wo xh yi yo za zh zu""".split()
)


def valid_lang(code):
    base, _, variant = code.partition("-")
    return base in ISO_639_1 and (not variant or re.match(r"^[a-z0-9]{2,4}$", variant))
ARROW = "\u2192"


class UsageError(Exception):
    pass


class EngineError(Exception):
    pass


class EngineSkip(EngineError):
    pass


class RateLimit(EngineError):
    pass


class AllEnginesFailed(Exception):
    def __init__(self, errors, all_rate=False):
        super().__init__("todos os motores falharam")
        self.errors = errors
        self.all_rate = all_rate


def http_fetch(req):
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (429, 503):
            raise RateLimit(f"limite de requisições (HTTP {e.code})")
        raise EngineError(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise EngineError(f"erro de rede: {e.reason}")
    except (TimeoutError, OSError) as e:
        raise EngineError(f"erro de rede: {e}")


def parse_json(body):
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise EngineError(f"resposta inválida ({e})")


def engine_google(sl, tl, text):
    headers = {"User-Agent": USER_AGENT}
    url = (
        GOOGLE_URL
        + "?"
        + urllib.parse.urlencode({"client": "dict-chrome-ex", "sl": sl, "tl": tl})
        + "&q="
        + urllib.parse.quote(text)
    )
    data = parse_json(http_fetch(urllib.request.Request(url, headers=headers)))
    if not isinstance(data, list) or not data:
        raise EngineError("resposta inesperada")
    parts, detected = [], None
    if isinstance(data[0], list):
        for seg in data:
            if isinstance(seg, list) and seg and isinstance(seg[0], str):
                parts.append(seg[0])
                if detected is None and len(seg) > 1 and isinstance(seg[1], str):
                    detected = seg[1]
    else:
        parts = [s for s in data if isinstance(s, str)]
    if not parts:
        raise EngineError("tradução vazia na resposta")
    return "".join(parts), detected


def engine_mymemory(sl, tl, text):
    if sl in ("", "auto"):
        raise EngineSkip("exige idioma de origem explícito")
    if len(text) > MYMEMORY_MAX:
        raise EngineSkip(f"texto acima de {MYMEMORY_MAX} caracteres")
    url = MYMEMORY_URL + "?" + urllib.parse.urlencode({"q": text, "langpair": f"{sl}|{tl}"})
    data = parse_json(http_fetch(urllib.request.Request(url, headers={"User-Agent": USER_AGENT})))
    status = data.get("responseStatus") if isinstance(data, dict) else None
    translated = (data.get("responseData") or {}).get("translatedText") if isinstance(data, dict) else None
    if status not in (200, "200") or not translated:
        raise EngineError(f"status {status}")
    if "MYMEMORY WARNING" in translated.upper():
        raise RateLimit("cota gratuita esgotada")
    return translated, None


def engine_libre(sl, tl, text):
    payload = json.dumps({"q": text, "source": sl or "auto", "target": tl, "format": "text"}).encode("utf-8")
    headers = {"User-Agent": f"tradutor/{VERSION}", "Content-Type": "application/json"}
    req = urllib.request.Request(LIBRE_URL, data=payload, headers=headers, method="POST")
    data = parse_json(http_fetch(req))
    translated = data.get("translatedText") if isinstance(data, dict) else None
    if not translated:
        raise EngineError("resposta sem tradução")
    detected = (data.get("detectedLanguage") or {}).get("language") if isinstance(data, dict) else None
    return translated, detected


ENGINES = {"google": engine_google, "mymemory": engine_mymemory, "libre": engine_libre}


def translate_chunk(text, sl, tl, forced):
    order = (forced,) if forced else ENGINE_ORDER
    errors, hard_fail = [], False
    for name in order:
        try:
            translation, detected = ENGINES[name](sl, tl, text)
            return name, translation, detected
        except EngineSkip as e:
            if forced:
                raise UsageError(f"motor {name}: {e}")
            errors.append(f"{name} pulado ({e})")
            print(f"tradutor: aviso: {name} pulado ({e})", file=sys.stderr)
        except RateLimit as e:
            errors.append(f"{name} com limite de requisições ({e})")
            print(f"tradutor: aviso: {name}: {e}", file=sys.stderr)
        except (EngineError, Exception) as e:
            detail = f"{e.__class__.__name__}: {e}" if not isinstance(e, EngineError) else str(e)
            errors.append(f"{name} falhou ({detail})")
            hard_fail = True
            print(f"tradutor: aviso: {name} falhou ({detail})", file=sys.stderr)
    raise AllEnginesFailed(errors, all_rate=not hard_fail)


def _hard_wrap(s, max_len):
    out, cur = [], ""
    for w in s.split(" "):
        while len(w) > max_len:
            if cur:
                out.append(cur)
                cur = ""
            out.append(w[:max_len])
            w = w[max_len:]
        cand = f"{cur} {w}" if cur else w
        if len(cand) > max_len and cur:
            out.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def make_chunks(text, max_len):
    if len(text) <= max_len:
        return [text]
    chunks, cur = [], ""
    for para in re.split(r"\n{2,}", text):
        para = para.strip("\n")
        if not para:
            continue
        cand = f"{cur}\n\n{para}" if cur else para
        if len(cand) <= max_len:
            cur = cand
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if len(para) <= max_len:
            cur = para
        else:
            pieces = []
            for sentence in re.split(r"(?<=[.!?…])\s+", para):
                pieces.extend(_hard_wrap(sentence, max_len))
            chunks.extend(pieces[:-1])
            cur = pieces[-1]
    if cur:
        chunks.append(cur)
    return chunks


def open_db():
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(CACHE_DB, timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS translations ("
            "hash TEXT PRIMARY KEY, engine TEXT, sl TEXT, tl TEXT, "
            "text TEXT, translation TEXT, detected TEXT, created_at TEXT)"
        )
        return conn
    except sqlite3.Error as e:
        print(f"tradutor: aviso: cache indisponível ({e})", file=sys.stderr)
        return None


def cache_key(engine, sl, tl, chunk):
    return hashlib.sha256(f"{engine}|{sl}|{tl}|{chunk}".encode("utf-8")).hexdigest()


def cache_get(conn, key):
    if conn is None:
        return None
    try:
        return conn.execute(
            "SELECT engine, translation, detected FROM translations WHERE hash = ?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return None


def cache_put(conn, key, engine, sl, tl, text, translation, detected):
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO translations VALUES (?,?,?,?,?,?,?,?)",
            (key, engine, sl, tl, text, translation, detected, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"tradutor: aviso: falha ao gravar cache ({e})", file=sys.stderr)


def translate_text(text, sl, tl, forced, use_cache):
    conn = open_db() if use_cache else None
    chunks = make_chunks(text, CHUNK_MAX[forced] if forced else CHUNK_MAX["google"])
    parts, detected, hits, primary = [], None, 0, None
    for chunk in chunks:
        result = None
        if conn is not None:
            for name in ((forced,) if forced else ENGINE_ORDER):
                row = cache_get(conn, cache_key(name, sl, tl, chunk))
                if row:
                    result = (row[0], row[1], row[2], True)
                    break
        if result is None:
            name, translation, det = translate_chunk(chunk, sl, tl, forced)
            if conn is not None:
                cache_put(conn, cache_key(name, sl, tl, chunk), name, sl, tl, chunk, translation, det)
            result = (name, translation, det, False)
        name, translation, det, hit = result
        if primary is None:
            primary = name
        parts.append(translation)
        if hit:
            hits += 1
        if detected is None and det:
            detected = det
    if conn is not None:
        conn.close()
    return "\n\n".join(parts), primary, detected, hits, len(chunks)


def parse_langs(raw):
    s = (raw or "").strip().lower()
    if not s:
        raise UsageError("informe os idiomas (ex.: en:pt, :pt ou pt)")
    if ":" in s:
        sl, _, tl = s.partition(":")
    else:
        sl, tl = "auto", s
    sl = sl or "auto"
    if not tl:
        raise UsageError("informe o idioma de destino (ex.: en:pt)")
    if sl != "auto" and not valid_lang(sl):
        raise UsageError(f"idioma de origem inválido: {sl}")
    if not valid_lang(tl):
        raise UsageError(f"idioma de destino inválido: {tl}")
    if tl == "auto":
        raise UsageError("o idioma de destino não pode ser 'auto'")
    return sl, tl


PATH_HINT_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def resolve_text(args):
    if args.text:
        if len(args.text) == 1:
            single = args.text[0]
            path = Path(single)
            if path.is_file():
                try:
                    return path.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    raise UsageError(f"não foi possível ler {single}: {e}")
            if "/" in single or PATH_HINT_RE.search(single):
                raise UsageError(f"arquivo não encontrado: {single}")
            return single
        return " ".join(args.text)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise UsageError('forneça um texto, um arquivo ou a entrada via pipe: echo "hi" | tradutor :pt')


def _trunc(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def print_history(n):
    conn = open_db()
    if conn is None:
        print("tradutor: erro: cache indisponível", file=sys.stderr)
        return 1
    try:
        rows = conn.execute(
            "SELECT created_at, sl, tl, engine, text, translation FROM translations "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (n,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("nenhuma tradução no cache ainda")
        return 0
    for created, sl, tl, engine, text, translation in rows:
        print(f"{created}  {sl}{ARROW}{tl}  [{engine}]  {_trunc(text, 40)} {ARROW} {_trunc(translation, 60)}")
    return 0


def _plural_blocos(n):
    return "1 bloco" if n == 1 else f"{n} blocos"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="tradutor",
        description=(
            "Traduz textos, arquivos e a entrada padrão entre idiomas.\n"
            "Motores: Google → MyMemory → LibreTranslate, com fallback automático\n"
            "e cache local (SQLite) para respostas instantâneas."
        ),
        epilog=(
            "exemplos:\n"
            "  tradutor en:pt \"hello world\"           traduz com origem explícita\n"
            "  tradutor :pt \"good morning\"            auto-detecta o idioma de origem\n"
            "  echo \"hi\" | tradutor -b :pt            pipe com saída limpa (só a tradução)\n"
            "  tradutor en:pt manual.txt -o m_pt.txt  traduz arquivo e grava o resultado\n"
            "  tradutor --no-cache en:pt \"segredo\"    não grava nada no cache local\n"
            "  tradutor --history 5                   lista as 5 traduções recentes\n"
            "\n"
            "guia completo: tradutor --manual  |  man tradutor"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="mostra esta ajuda e sai")
    parser.add_argument("langs", nargs="?", metavar="sl:tl", help="idiomas: en:pt, :pt (origem auto) ou pt (destino)")
    parser.add_argument(
        "text",
        nargs="*",
        metavar="texto",
        help="texto a traduzir; se for um caminho existente, traduz o arquivo; ausente, lê da entrada padrão",
    )
    parser.add_argument("-b", "--brief", action="store_true", help="imprime apenas a tradução")
    parser.add_argument("-o", "--output", metavar="ARQUIVO", help="grava a tradução no arquivo ARQUIVO")
    parser.add_argument(
        "--engine",
        choices=("google", "mymemory", "libre"),
        help="força um motor específico (sem fallback)",
    )
    parser.add_argument("--no-cache", action="store_true", help="não lê nem grava o cache local")
    parser.add_argument("--history", nargs="?", const=10, type=int, metavar="N", help="lista as N traduções recentes (padrão: 10)")
    parser.add_argument("--manual", action="store_true", help="guia completo no terminal")
    parser.add_argument("--version", action="version", version=f"tradutor {VERSION}", help="mostra a versão e sai")
    return parser


QUICK_HELP = """tradutor — tradutor de idiomas para o terminal

exemplos rápidos:
  tradutor en:pt "hello world"             inglês → português
  tradutor :pt "good morning"              detecta o idioma e traduz
  tradutor en:pt doc.txt -o doc_pt.txt     traduz um arquivo

  tradutor --help      todas as opções
  tradutor --manual    guia completo
"""

MANUAL = """TRADUTOR — guia completo

NOME
    tradutor — tradutor de idiomas para o terminal

SINOPSE
    tradutor [sl:tl] [texto | arquivo] [opções]
    tradutor [opções]            (lê da entrada padrão)
    tradutor                     (ajuda rápida)

DESCRIÇÃO
    Traduz textos, arquivos e a entrada padrão entre idiomas, usando o
    Google Translate como motor principal, com fallback automático para
    MyMemory e LibreTranslate quando necessário. Traduções repetidas são
    servidas de um cache local (SQLite), instantaneamente e sem rede.

FORMATO DOS IDIOMAS
    en:pt     origem inglês, destino português
    :pt       origem detectada automaticamente
    pt        igual a :pt (origem automática)
    auto:pt   igual a :pt
    Códigos ISO 639-1 (en, pt, es, fr, de, it, ja, ...) com variante
    opcional (pt-BR, en-GB).

EXEMPLOS
    tradutor en:pt "hello world"
    tradutor :pt "good morning"
    tradutor pt "the house is big"
    echo "the house is big" | tradutor -b :pt
    tradutor pt:en < carta.txt
    tradutor en:pt manual.txt -o manual_pt.txt
    tradutor --engine libre :pt "bonjour"
    tradutor --history 5

OPÇÕES
    -b, --brief          imprime apenas a tradução (ideal para scripts)
    -o, --output ARQ     grava a tradução no arquivo ARQ
    --no-cache           não lê nem grava o cache (texto sensível)
    --engine MOTOR       força um motor: google | mymemory | libre
    --history [N]        lista as N traduções recentes (padrão 10)
    --manual             mostra este guia
    --help               ajuda resumida
    --version            mostra a versão

MOTORES E FALLBACK
    1. google    Google Translate (endpoint do Chrome, suporta auto-detect)
    2. mymemory  MyMemory API (sem auto-detect; textos de até 500 caracteres)
    3. libre     LibreTranslate (instância pública)
    Se um motor falha (rede, limite, formato), o próximo é tentado
    automaticamente e um aviso é mostrado. Com --engine, apenas o motor
    escolhido é usado, sem fallback.

TEXTOS LONGOS E ARQUIVOS
    Textos maiores que o limite de uma requisição são divididos em
    blocos por parágrafo/frase, traduzidos em sequência e reunidos.
    Para traduzir um arquivo e salvar o resultado:
        tradutor en:pt entrada.txt -o saida.txt
    Também funciona com redirecionamento:
        tradutor :pt < entrada.txt > saida.txt

CACHE E HISTÓRICO
    Cache: ~/.cache/tradutor/cache.db (SQLite). Cada tradução é
    indexada por motor, idiomas e texto; repetições são instantâneas.
    --history lista as traduções recentes; --no-cache desliga o cache
    e não grava nada em disco.

PRIVACIDADE
    O texto traduzido é enviado por HTTPS a serviços de terceiros
    (Google, MyMemory ou LibreTranslate). Para textos sensíveis, use
    --no-cache para não guardar nada localmente; lembre-se de que o
    texto ainda trafega para o motor escolhido.

SAÍDA
    Padrão:  tradução + linha de status com motor, idiomas e origem
             detectada; "(em cache)" quando servida do cache.
    -b:      apenas a tradução.
    -o:      resumo no terminal; tradução gravada no arquivo.

SOLUÇÃO DE PROBLEMAS
    Limite de requisições (código 3): aguarde alguns instantes ou
        force outro motor com --engine mymemory ou --engine libre.
    Erro de rede (código 2): verifique a conexão; os três motores
        precisam de internet.
    MyMemory exige idioma de origem explícito e textos curtos;
        para textos longos o fallback pula esse motor.

CÓDIGOS DE SAÍDA
    0  sucesso
    1  argumentos/texto inválidos ou arquivo inexistente
    2  todos os motores falharam
    3  limite de requisições em todos os motores
    4  falha ao gravar o arquivo de saída

VEJA TAMBÉM
    tradutor --help, README.md, man tradutor
"""


def main(argv):
    args = build_parser().parse_args(argv)
    if args.manual:
        print(MANUAL, end="")
        return 0
    if args.history is not None:
        return print_history(args.history)
    if args.langs is None:
        print(QUICK_HELP, end="")
        return 0
    sl, tl = parse_langs(args.langs)
    text = resolve_text(args)
    if not text.strip():
        raise UsageError("texto vazio: forneça um texto, um arquivo ou a entrada via pipe")
    if args.engine == "mymemory" and sl == "auto":
        raise UsageError("MyMemory exige idioma de origem explícito (ex.: en:pt)")
    try:
        translation, primary, detected, hits, total = translate_text(text, sl, tl, args.engine, not args.no_cache)
    except AllEnginesFailed as e:
        print(
            f"tradutor: erro: todos os motores falharam ({'; '.join(e.errors)}). "
            "Verifique a conexão ou tente --engine mymemory/libre.",
            file=sys.stderr,
        )
        return 3 if e.all_rate else 2
    if args.output:
        try:
            Path(args.output).write_text(translation, encoding="utf-8")
        except OSError as e:
            print(f"tradutor: erro: não foi possível gravar {args.output}: {e}", file=sys.stderr)
            return 4
        line = f"[{primary}] {sl} {ARROW} {tl}"
        if sl == "auto" and detected:
            line += f" (detectado: {detected})"
        line += f" ({_plural_blocos(total)}, gravado em {args.output})"
        print(line)
    elif args.brief:
        print(translation)
    else:
        print(translation)
        line = f"[{primary}] {sl} {ARROW} {tl}"
        if sl == "auto" and detected:
            line += f" (detectado: {detected})"
        if total > 1:
            line += f" ({_plural_blocos(total)})"
        if hits == total:
            line += " (em cache)"
        print(line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except UsageError as e:
        print(f"tradutor: erro: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
