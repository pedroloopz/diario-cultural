"""Envia as mensagens dos bots para o Discord (substitui o Telegram).

Um webhook por canal, guardados juntos no secret DISCORD_WEBHOOKS (JSON):
    {"trade": "https://discord.com/api/webhooks/...",
     "cultural": "...", "idiomas": "...", "avisos": "..."}
A chave é a `fonte` da mensagem; "geral" (opcional) recebe o que não tiver canal próprio.
Só biblioteca padrão. Nunca derruba o bot: falha vira só um print.
Mesmo arquivo nos repositórios alerta-ema, jornal-de-jp, diario-cultural e robo-bingx.
"""
import html as _html
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
import uuid

LIMITE_TEXTO = 2000
LIMITE_ARQUIVO = 10 * 1024 * 1024      # 10 MB por arquivo no plano grátis
SEM_SOM = 1 << 12                      # flag SUPPRESS_NOTIFICATIONS
LETRAS = "ABCD"
FORUM_SEM_TITULO = 220001              # canal Fórum exige título do post
VERDE, VERMELHO, AMARELO, CINZA = 0x2ECC71, 0xE74C3C, 0xF1C40F, 0x95A5A6


def webhooks():
    try:
        d = json.loads(os.environ.get("DISCORD_WEBHOOKS") or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        print("Discord: DISCORD_WEBHOOKS não é um JSON válido")
        return {}


def ativo():
    return bool(webhooks())


def de_html(t):
    """Converte o HTML simples do Telegram para o Markdown do Discord."""
    t = t or ""
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", t, flags=re.I | re.S)
    for tag, md in (("b", "**"), ("strong", "**"), ("i", "*"), ("em", "*"), ("u", "__"),
                    ("s", "~~"), ("code", "`"), ("tg-spoiler", "||")):
        t = re.sub(rf"<{tag}(\s[^>]*)?>(.*?)</{tag}>", lambda m: f"{md}{m.group(2)}{md}", t, flags=re.I | re.S)
    t = re.sub(r"<pre(\s[^>]*)?>(.*?)</pre>", lambda m: f"```\n{m.group(2)}\n```", t, flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", "", t)
    return _html.unescape(t).strip()


def _pedacos(texto):
    texto = texto or ""
    while len(texto) > LIMITE_TEXTO:
        corte = texto.rfind("\n", 0, LIMITE_TEXTO)
        corte = corte if corte > LIMITE_TEXTO // 2 else LIMITE_TEXTO
        yield texto[:corte]
        texto = texto[corte:].lstrip("\n")
    if texto.strip():
        yield texto


def _post(url, payload, arquivos=()):
    """Devolve (mensagem criada ou None, código de erro do Discord ou None)."""
    url = url + ("&" if "?" in url else "?") + "wait=true"
    if arquivos:
        fronteira = uuid.uuid4().hex
        partes = [f"--{fronteira}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                  f"Content-Type: application/json\r\n\r\n".encode() + json.dumps(payload).encode() + b"\r\n"]
        for i, p in enumerate(arquivos):
            partes.append(f"--{fronteira}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; "
                          f"filename=\"{p.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
                          + p.read_bytes() + b"\r\n")
        corpo = b"".join(partes) + f"--{fronteira}--\r\n".encode()
        tipo = f"multipart/form-data; boundary={fronteira}"
    else:
        corpo, tipo = json.dumps(payload).encode(), "application/json"
    for tentativa in range(4):
        req = urllib.request.Request(url, data=corpo, method="POST",
                                     headers={"Content-Type": tipo, "User-Agent": "meus-bots (github actions)"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read() or b"{}"), None
        except urllib.error.HTTPError as e:
            corpo = e.read() or b"{}"
            try:
                erro = json.loads(corpo)
            except ValueError:
                erro = {}
            if e.code == 429 and tentativa < 3:
                time.sleep(min(float(erro.get("retry_after", 2)), 30) + 0.5)
                continue
            if erro.get("code") != FORUM_SEM_TITULO:
                print(f"Discord recusou ({e.code}): {corpo[:300]!r}")
            return None, erro.get("code")
        except Exception as e:
            print(f"Discord falhou: {type(e).__name__}: {e}")
            return None, None
    return None, None


def _cor(texto):
    """Cor do cartão do #trade: verde = compra/ganho, vermelho = venda/perda, amarelo = misto/alerta."""
    verde = len(re.findall(r"🟢|\bLONG\b", texto, re.I))
    vermelho = len(re.findall(r"🔴|🛑|\bSHORT\b", texto, re.I))
    if "⚠️" in texto or "🔒" in texto or (verde and vermelho):
        return AMARELO
    return VERDE if verde else VERMELHO if vermelho else CINZA


def enviar(fonte, texto="", html=False, arquivos=(), extra=None, tipo=""):
    """arquivos = caminhos (ou pares (caminho, título)). Devolve True se chegou."""
    hooks = webhooks()
    url = hooks.get(fonte) or hooks.get("geral")
    if not url:
        return False
    extra = extra or {}
    texto = de_html(texto) if html else (texto or "")

    if tipo == "quiz" and extra.get("opcoes"):
        ops = extra["opcoes"]
        linhas = [f"❓ **{texto}**", ""] + [f"{LETRAS[i]}) {o}" for i, o in enumerate(ops[:4])]
        c = extra.get("correta")
        if isinstance(c, int) and 0 <= c < len(ops):
            resp = f"{LETRAS[c]}) {ops[c]}"
            if extra.get("explicacao"):
                resp += f" — {extra['explicacao']}"
            linhas += ["", f"Resposta: ||{resp}||"]
        texto = "\n".join(linhas)
    if extra.get("link"):
        texto = f"{texto}\n{extra['link']}".strip()
    if extra.get("x"):
        texto = f"{texto}\n\n👉 [Enviar ao X]({extra['x']})".strip()

    caminhos = []
    for a in arquivos or ():
        p = pathlib.Path(a[0] if isinstance(a, (tuple, list)) else a)
        if not p.exists():
            continue
        if p.stat().st_size > LIMITE_ARQUIVO:
            texto += f"\n(arquivo {p.name} grande demais para o Discord)"
            continue
        caminhos.append(p)

    base = {"allowed_mentions": {"parse": []}}
    if extra.get("silencioso"):
        base["flags"] = SEM_SOM
    if fonte == "trade" and texto.strip() and len(texto) <= 4000:
        titulo, _, resto = texto.strip().partition("\n")
        cartao = {"color": _cor(texto)}
        if len(titulo) <= 256:
            cartao["title"] = titulo
            if resto.strip():
                cartao["description"] = resto.strip()
        else:
            cartao["description"] = texto.strip()
        envios = [({**base, "embeds": [cartao]}, caminhos[:10])]
    else:
        pedacos = list(_pedacos(texto)) or [""]
        envios = [({**base, "content": p}, caminhos[:10] if i == len(pedacos) - 1 else [])
                  for i, p in enumerate(pedacos) if p or i == len(pedacos) - 1]
    envios += [(base, caminhos[j:j + 10]) for j in range(10, len(caminhos), 10)]

    ok, alvo = True, url
    for payload, anexos in envios:
        if not payload.get("content") and not payload.get("embeds") and not anexos:
            continue
        msg, erro = _post(alvo, payload, anexos)
        if erro == FORUM_SEM_TITULO:                 # #cultural virou Fórum: cada post é um tópico
            titulo = re.sub(r"[*_`|#>]", "", texto.strip().split("\n")[0]).strip()[:100] or tipo or fonte
            msg, erro = _post(alvo, {**payload, "thread_name": titulo}, anexos)
            if msg and msg.get("channel_id"):
                alvo = f"{url}?thread_id={msg['channel_id']}"
        ok = ok and msg is not None
    return ok
