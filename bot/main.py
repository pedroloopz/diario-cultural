"""Diário cultural: gera posts sobre arte, literatura e música até 1910.

Uso:
  python bot/main.py gerar   -> cria o post em docs/posts/ e atualiza autores/estado
  python bot/main.py enviar  -> manda o post pendente ao Telegram com o botão "Enviar ao X"
"""
import datetime
import html
import io
import json
import os
import pathlib
import random
import re
import sys
import unicodedata

import requests
from urllib.parse import quote
from PIL import Image

RAIZ = pathlib.Path(__file__).resolve().parent.parent
AUTORES = RAIZ / "bot" / "autores.json"
ESTADO = RAIZ / "bot" / "estado.json"
POSTS = RAIZ / "docs" / "posts"

# Modelo configurável sem mexer no código: GitHub → Settings → Secrets and variables →
# Actions → aba Variables → CLAUDE_MODEL (ex.: claude-sonnet-5-5 para gastar menos).
MODELO = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-opus-5-5"
UA = {"User-Agent": "diario-cultural-bot/1.0 (https://github.com/pedroloopz/diario-cultural)"}

# Ordem dos posts: cada execução pega a próxima categoria.
DIAGNOSTICO = []  # registra o que deu errado em cada execução
THREAD = os.environ.get("TELEGRAM_THREAD_ID", "").strip()  # tópico 🎨 Diário cultural do grupo
ENSAIO = False  # execução de ensaio: não grava, não publica, não manda ao Telegram

CICLO = ["pintura", "poema", "musica", "diario", "teoria", "movimento", "esquecido"]
AREA_DA_CATEGORIA = {"pintura": "pintura", "movimento": "pintura", "poema": "poesia",
                     "musica": "musica", "diario": "diario", "teoria": "teoria"}
TIPO_DA_AREA = {"pintura": "pintura", "poesia": "poema", "musica": "musica",
                "diario": "diario", "teoria": "teoria"}
DESCRICAO_AREA = {
    "pintura": "pintores",
    "poesia": "poetas",
    "musica": "compositores",
    "diario": "autores de diários, cadernos íntimos ou cartas pessoais",
    "teoria": "teóricos da literatura, da poética ou da estética",
}

LIMITE_USOS = 10       # posts por autor antes do descanso
DESCANSO_DIAS = 90     # dias fora do rodízio depois do limite
MINIMO_DISPONIVEIS = 6 # abaixo disso, o bot busca autores novos
PROP_FAMOSOS = 0.3     # cerca de 30% famosos, 70% pouco conhecidos
ANO_LIMITE = 1910
MORTE_LIMITE = 1955   # autor morto até 1955: obra em domínio público no Brasil (70 anos)

SISTEMA = (
    "Você escreve posts para um perfil pessoal no X sobre arte, literatura e música até 1910. "
    "VOZ: uma pessoa real que gosta dessa obra e quer contar a um amigo por que ela mexe com ela. "
    "A primeira pessoa pode REAGIR à obra, em português do Brasil falado com cuidado, frases curtas "
    "e claras, calor humano. Nada de tom de aula, verbete ou catálogo de museu; nada de 'em "
    "substância', 'cumpre notar', 'nesse sentido', 'me desarma', 'não me larga', 'mexe comigo', "
    "'é isso que', 'o que me pega': fórmulas repetidas matam o perfil. "
    "PROIBIDO INVENTAR VIVÊNCIAS de quem assina o perfil: nada de episódios, conversas, pessoas "
    "(amigo, mãe, professor...), lugares (bar, café, metrô, museu visitado...) ou momentos ('ontem', "
    "'de madrugada', 'semana passada', 'quando eu era criança') da vida dele. O perfil é de uma "
    "pessoa real e qualquer cena assim seria falsa. "
    "COMO CONSTRUIR (retenção de público): "
    "1) GANCHO: a primeira frase tem no máximo 120 caracteres e é uma AFIRMAÇÃO forte que abre uma "
    "lacuna de curiosidade: um fato surpreendente, um contraste ('pintou o mar uma única vez, e é o "
    "quadro que ninguém pode ver'), uma consequência dita antes da causa, ou um detalhe concreto "
    "estranho; tirada da obra ou da vida comprovada do autor, nunca da vida de quem assina, nunca "
    "começando por data ('Em 1827, Fulano...') nem pelo nome do autor. Os primeiros 250 caracteres "
    "(o que o X mostra antes de 'Mostrar mais') precisam prometer uma revelação; "
    "2) LOOP ABERTO: guarde o fato mais surpreendente para o meio ou o fim e cumpra a promessa do "
    "gancho; nada de isca vazia; "
    "3) o ser humano por trás da obra: um medo, uma perda, uma carta, uma teimosia, a pobreza, o "
    "amor, só se for fato comprovado; detalhes específicos (nomes, números, objetos) valem mais que "
    "adjetivos; "
    "4) tensão e espanto: mostre o contraste (glória x miséria, ternura x violência, o que o autor "
    "quis x o que aconteceu) e o que a obra faz com quem a vê, lê ou ouve hoje, em linguagem de carne "
    "e osso; "
    "5) feche com uma frase curta (até 12 palavras) que fique ecoando: uma imagem, uma virada ou uma "
    "confissão, nunca uma moral de manual. "
    "Ritmo: frases curtas, verbos concretos, um parágrafo por ideia, alterne uma frase longa com "
    "golpes curtos. No máximo uma metáfora por post, e só se for boa. Contexto histórico entra pouco "
    "e a serviço da emoção. "
    "REGRAS FIXAS: sem emojis, sem hashtags, sem links, NENHUMA pergunta (nem retórica, nem no gancho, nem no fecho; o único '?' permitido é o que já está no trecho original citado) e sem pedir curtida, "
    "comentário ou compartilhamento; entre 600 e 1100 caracteres no campo texto (o trecho original "
    "e a tradução, quando houver, não contam); nunca invente datas, obras, gravações, cartas ou "
    "citações: se não tiver certeza de um dado, omita-o; texto original em outra língua vem seguido "
    "de tradução sua (sem tradução se o original já for português); se o original for japonês, "
    "coloque a leitura em kana entre parênteses antes da tradução; ao tratar de Wagner ou do "
    "nacionalismo alemão do séc. XIX, fale da obra artística com contexto histórico honesto, sem "
    "exaltar nem esconder o nacionalismo e o antissemitismo da época. "
    "Responda apenas com JSON válido, sem markdown."
)


# ---------- utilidades ----------

def ler(caminho, padrao):
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else padrao


def gravar(caminho, dados):
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\W_]+", " ", s).strip()


def sem_acento(s):
    s = unicodedata.normalize("NFKD", s)
    return norm("".join(c for c in s if not unicodedata.combining(c)))


def telegram(metodo, tentativas=3, **kw):
    """Chama a API do Telegram. Lentidão ou erro 5xx/429 tenta de novo (o Telegram às vezes demora)."""
    import time

    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/{metodo}"
    for n in range(1, tentativas + 1):
        for f in (kw.get("files") or {}).values():
            f.seek(0)  # arquivo de imagem: volta ao início antes de reenviar
        try:
            r = requests.post(url, timeout=60, **kw)
        except requests.exceptions.RequestException as erro:
            if n == tentativas:
                raise RuntimeError(f"Telegram {metodo} não respondeu: {erro}") from erro
            time.sleep(5 * n)
            continue
        if r.ok:
            return r.json()
        if n < tentativas and (r.status_code == 429 or r.status_code >= 500):
            time.sleep(5 * n)
            continue
        raise RuntimeError(f"Telegram {metodo} recusou: {r.status_code} {r.text[:300]}")


def destino(aviso=False):
    """Chat e tópico do grupo. TELEGRAM_THREAD_ID vazio = manda como antes (sem tópico).
    aviso=True vai para o tópico ⚠️ Avisos (TELEGRAM_AVISOS_THREAD_ID), se existir."""
    d = {"chat_id": os.environ["TELEGRAM_CHAT_ID"]}
    topico = (aviso and os.environ.get("TELEGRAM_AVISOS_THREAD_ID", "").strip()) or THREAD
    if topico:
        d["message_thread_id"] = topico
    return d


def avisar(texto, aviso=False):
    if ENSAIO:
        print(f"[ensaio] Telegram não enviado: {texto}")
        return
    telegram("sendMessage", data={**destino(aviso), "text": texto})


def do_meu_topico(msg):
    """Privacidade: só o chat configurado e, no grupo, só o tópico deste bot. Sem tópico
    configurado, só a conversa privada. O resto é descartado sem ler nem registrar."""
    chat = msg.get("chat", {})
    if str(chat.get("id")) != str(os.environ["TELEGRAM_CHAT_ID"]):
        return False
    if THREAD:
        return str(msg.get("message_thread_id")) == THREAD
    return chat.get("type") == "private"


class ApiBloqueada(Exception):
    """Erro da API do Claude que não se resolve tentando outro autor (crédito, chave, permissão)."""


SINAIS_BLOQUEIO = ("credit balance", "billing", "insufficient", "quota", "invalid x-api-key",
                   "authentication", "permission", "not_found_error", "model:")


def explicar_bloqueio(status, corpo):
    c = corpo.lower()
    if "credit" in c or "billing" in c or "insufficient" in c:
        return ("os créditos da API do Claude acabaram.",
                "abra platform.claude.com → Billing e adicione crédito. O bot volta sozinho na próxima execução.")
    if status == 401 or "x-api-key" in c or "authentication" in c:
        return ("a chave da API do Claude não é mais válida.",
                "crie uma chave nova em platform.claude.com → API keys e atualize o segredo "
                "ANTHROPIC_API_KEY no GitHub (Settings → Secrets and variables → Actions).")
    if "model" in c or status == 404:
        return (f"o modelo '{MODELO}' não foi aceito pela API.",
                "crie a variável CLAUDE_MODEL no GitHub com um modelo válido (ex.: claude-sonnet-5-5).")
    return (f"a API do Claude recusou o pedido ({status}).", "veja o arquivo bot/ultimo_diagnostico.txt.")


def claude(pedido, max_tokens=8000):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODELO, "max_tokens": max_tokens, "system": SISTEMA,
              "messages": [{"role": "user", "content": pedido}]},
        timeout=180,
    )
    if not r.ok:
        corpo = r.text[:500]
        if r.status_code in (401, 403, 404) or (
                r.status_code == 400 and any(x in corpo.lower() for x in SINAIS_BLOQUEIO)):
            raise ApiBloqueada(f"{r.status_code} {corpo}")
        raise RuntimeError(f"API do Claude {r.status_code}: {corpo}")
    uso = r.json().get("usage", {})
    DIAGNOSTICO.append(f"uso da API: {uso.get('input_tokens', 0)} tokens de entrada, "
                       f"{uso.get('output_tokens', 0)} de saída")
    texto = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    return json.loads(texto)


# ---------- rodízio de autores ----------

def disponiveis(autores, area, hoje):
    lista = []
    for a in autores:
        if a["area"] != area or not a.get("aprovado", True):
            continue
        if a.get("descanso_ate"):
            if hoje < datetime.date.fromisoformat(a["descanso_ate"]):
                continue
            a["descanso_ate"], a["usos"] = None, 0
        lista.append(a)
    return lista


def escolher(autores, area, hoje, so_desconhecidos=False, evitar=()):
    disp = [a for a in disponiveis(autores, area, hoje) if a["nome"] not in evitar]
    if len(disp) < MINIMO_DISPONIVEIS:
        try:
            repor(autores, area)
        except ApiBloqueada:
            raise
        except Exception as e:
            DIAGNOSTICO.append(f"reposição de autores em {area} falhou: {type(e).__name__}: {str(e)[:200]}")
        disp = [a for a in disponiveis(autores, area, hoje) if a["nome"] not in evitar]
    famosos = [a for a in disp if a["famoso"]]
    obscuros = [a for a in disp if not a["famoso"]]
    if so_desconhecidos or not famosos or (obscuros and random.random() > PROP_FAMOSOS):
        grupo = obscuros or famosos
    else:
        grupo = famosos
    return random.choice(grupo) if grupo else None


def registrar_uso(autor, hoje):
    autor["usos"] = autor.get("usos", 0) + 1
    if autor["usos"] >= LIMITE_USOS:
        autor["descanso_ate"] = (hoje + datetime.timedelta(days=DESCANSO_DIAS)).isoformat()


def ano_wikidata(claims, prop):
    for c in claims.get(prop, []):
        t = c["mainsnak"].get("datavalue", {}).get("value", {}).get("time")
        m = re.match(r"([+-])(\d+)-", t or "")
        if m:
            return int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
    return None


def validar_wikidata(nome):
    """Confere se a pessoa existe no Wikidata, produziu até 1910 e morreu até 1955."""
    busca = requests.get("https://www.wikidata.org/w/api.php", headers=UA, timeout=30, params={
        "action": "wbsearchentities", "search": nome, "language": "en",
        "type": "item", "limit": 3, "format": "json"}).json()
    for item in busca.get("search", []):
        dados = requests.get(f"https://www.wikidata.org/wiki/Special:EntityData/{item['id']}.json",
                             headers=UA, timeout=30).json()
        ent = next(iter(dados["entities"].values()))
        claims = ent.get("claims", {})
        humano = any(c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") == "Q5"
                     for c in claims.get("P31", []))
        if not humano:
            continue
        nasc, morte = ano_wikidata(claims, "P569"), ano_wikidata(claims, "P570")
        if morte is not None and morte <= MORTE_LIMITE and (nasc is None or nasc < 1895):
            return item["id"]
    return None


def repor(autores, area):
    existentes = {a["nome"].lower() for a in autores}
    pedido = claude(
        f"Liste 30 {DESCRICAO_AREA[area]} cuja obra principal seja de até 1910 e que tenham morrido até "
        f"1955, de países e épocas variados (da Antiguidade a 1910). Cerca de 70% pouco conhecidos do público geral e 30% famosos. Não repita nenhum "
        f"destes: {', '.join(sorted(existentes))}. "
        'Responda: {"autores":[{"nome":"nome como aparece na Wikipedia em inglês","famoso":true}]}',
        max_tokens=8000,
    )
    novos = []
    for c in pedido.get("autores", []):
        nome = c.get("nome", "").strip()
        if not nome or nome.lower() in existentes:
            continue
        qid = validar_wikidata(nome)
        if qid:
            autores.append({"nome": nome, "area": area, "famoso": bool(c.get("famoso")),
                            "usos": 0, "descanso_ate": None, "aprovado": True, "wikidata": qid})
            existentes.add(nome.lower())
            novos.append(nome)
    if novos:
        avisar(f"Novos autores em {area}:\n" + "\n".join(novos) +
               "\n\nPara tirar um do rodízio, mande: /remover Nome Completo")


def processar_comandos(estado, autores):
    """Lê os comandos mandados ao bot (/remover). Se o Telegram falhar, o post sai mesmo assim."""
    try:
        r = telegram("getUpdates", data={"offset": estado.get("offset", 0), "timeout": 0})
    except Exception as erro:
        DIAGNOSTICO.append(f"comandos do Telegram não lidos nesta execução: {erro}")
        return
    ignoradas = 0
    for u in r.get("result", []):
        estado["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if not do_meu_topico(m):
            ignoradas += 1  # outro tópico/chat: só a contagem, nada do conteúdo
            continue
        texto = re.sub(r"^(/\w+)@\w+", r"\1", (m.get("text") or "").strip())  # /remover@bot no grupo
        if texto.startswith("/remover "):
            alvo = texto[len("/remover "):].strip().lower()
            for a in autores:
                if a["nome"].lower() == alvo:
                    a["aprovado"] = False
                    avisar(f"{a['nome']} saiu do rodízio.")
    if ignoradas:
        DIAGNOSTICO.append(f"Telegram: {ignoradas} mensagem(ns) de fora do tópico ignorada(s)")


# ---------- imagens via Wikidata/Wikimedia Commons (fonte principal) ----------

WD_API = "https://www.wikidata.org/w/api.php"


def wd_entidades(ids, props="claims|labels"):
    ids = [i for i in ids if i]
    if not ids:
        return {}
    r = requests.get(WD_API, headers=UA, timeout=30, params={
        "action": "wbgetentities", "ids": "|".join(ids[:50]), "props": props,
        "languages": "pt|en", "format": "json"}).json()
    return r.get("entities", {})


def wd_busca(texto, limite=30):
    r = requests.get(WD_API, headers=UA, timeout=30, params={
        "action": "query", "list": "search", "srsearch": texto, "srnamespace": 0,
        "srlimit": limite, "format": "json"}).json()
    return [h["title"] for h in r.get("query", {}).get("search", [])]


def rotulo(ent):
    l = ent.get("labels", {})
    return (l.get("pt") or l.get("en") or {}).get("value")


def wd_valor(claims, prop):
    for c in claims.get(prop, []):
        v = c["mainsnak"].get("datavalue", {}).get("value")
        if v:
            return v
    return None


def wd_pessoa(nome):
    busca = requests.get(WD_API, headers=UA, timeout=30, params={
        "action": "wbsearchentities", "search": nome, "language": "en",
        "type": "item", "limit": 5, "format": "json"}).json()
    ids = [i["id"] for i in busca.get("search", [])]
    for qid, ent in wd_entidades(ids, "claims").items():
        p31 = [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
               for c in ent.get("claims", {}).get("P31", [])]
        if "Q5" in p31:
            return qid
    return None


def wd_pintura(ent, artista=None):
    c = ent.get("claims", {})
    arquivo = wd_valor(c, "P18")
    if not arquivo:
        return None
    ano = ano_wikidata(c, "P571")
    if ano and ano > ANO_LIMITE:
        return None
    criador = (wd_valor(c, "P170") or {}).get("id")
    colecao = (wd_valor(c, "P195") or {}).get("id")
    nomes = wd_entidades([i for i in (criador, colecao) if i and not (i == criador and artista)], "labels")
    base = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(arquivo.replace(" ", "_"))
    return {"url": base + "?width=2048", "url_menor": base + "?width=1024",
            "titulo": rotulo(ent) or "sem título",
            "artista": artista or rotulo(nomes.get(criador, {})) or "autor desconhecido",
            "data": str(ano) if ano else "data não informada",
            "museu": rotulo(nomes.get(colecao, {})) or "Wikimedia Commons"}


def wd_pinturas(consulta, artista=None):
    ids = wd_busca(f"{consulta} haswbstatement:P31=Q3305213 haswbstatement:P18")
    random.shuffle(ids)
    for qid, ent in wd_entidades(ids[:20]).items():
        obra = wd_pintura(ent, artista)
        if obra:
            return obra
    return None


def tentar(funcao, *args):
    try:
        return funcao(*args)
    except ApiBloqueada:
        raise
    except Exception as e:
        DIAGNOSTICO.append(f"{funcao.__name__} falhou: {type(e).__name__}: {str(e)[:150]}")
        return None


# ---------- imagens (domínio público) ----------

def met_busca(params, filtro):
    ids = requests.get("https://collectionapi.metmuseum.org/public/collection/v1/search",
                       params=params, headers=UA, timeout=30).json().get("objectIDs") or []
    for oid in ids[:40]:
        o = requests.get(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}",
                         headers=UA, timeout=30).json()
        if (o.get("isPublicDomain") and o.get("primaryImage")
                and (o.get("objectEndDate") or 9999) <= ANO_LIMITE and filtro(o)):
            return {"url": o["primaryImage"], "url_menor": o.get("primaryImageSmall"),
                    "titulo": o.get("title"),
                    "artista": o.get("artistDisplayName") or "autor desconhecido",
                    "data": o.get("objectDate"), "museu": "The Metropolitan Museum of Art, Nova York"}
    return None


def aic_busca(q, filtro):
    r = requests.get("https://api.artic.edu/api/v1/artworks/search", headers=UA, timeout=30, params={
        "q": q, "limit": 40,
        "fields": "title,artist_title,date_display,date_end,image_id,is_public_domain,classification_title"}).json()
    for o in r.get("data", []):
        if (o.get("is_public_domain") and o.get("image_id")
                and (o.get("date_end") or 9999) <= ANO_LIMITE and filtro(o)):
            return {"url": f"https://www.artic.edu/iiif/2/{o['image_id']}/full/1686,/0/default.jpg",
                    "url_menor": f"https://www.artic.edu/iiif/2/{o['image_id']}/full/843,/0/default.jpg",
                    "titulo": o.get("title"), "artista": o.get("artist_title") or "autor desconhecido",
                    "data": o.get("date_display"), "museu": "Art Institute of Chicago"}
    return None


def obra_do_pintor(nome):
    qid = tentar(wd_pessoa, nome)
    if qid:
        obra = tentar(wd_pinturas, f"haswbstatement:P170={qid}", nome)
        if obra:
            return obra
    return tentar(obra_do_pintor_museus, nome)


def obra_do_pintor_museus(nome):
    sobrenome = sem_acento(nome).split()[-1]
    return (met_busca({"q": nome, "artistOrCulture": "true", "hasImages": "true"},
                      lambda o: o.get("classification") == "Paintings"
                      and sobrenome in sem_acento(o.get("artistDisplayName") or ""))
            or aic_busca(nome, lambda o: (o.get("classification_title") or "").lower().startswith("painting")
                         and sobrenome in sem_acento(o.get("artist_title") or "")))


def imagem_do_post(autor, busca):
    """Teoria, poema, diário e música: 1) retrato do autor (Wikidata P18); 2) pintura ligada ao
    tema, do mesmo país do autor e da mesma época (±50 anos); 3) busca genérica pelo tema."""
    qid = autor.get("wikidata") or tentar(wd_pessoa, autor["nome"])
    claims = ((tentar(wd_entidades, [qid]) or {}).get(qid, {}) if qid else {}).get("claims", {})
    arquivo = wd_valor(claims, "P18")
    if arquivo:
        DIAGNOSTICO.append("imagem: 1 (retrato do autor no Wikidata)")
        base = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(arquivo.replace(" ", "_"))
        return {"url": base + "?width=2048", "url_menor": base + "?width=1024",
                "titulo": f"Retrato de {autor['nome']}", "artista": "", "data": "",
                "museu": "Wikimedia Commons"}
    anos = [a for a in (ano_wikidata(claims, "P569"), ano_wikidata(claims, "P570")) if a]
    paises = [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P27", [])]
    paises = [x for x in paises if x]
    if anos and paises:
        obra = tentar(wd_pinturas_epoca, busca, paises, sum(anos) // len(anos))
        if obra:
            DIAGNOSTICO.append("imagem: 2 (obra do mesmo país e época do autor)")
            return obra
    DIAGNOSTICO.append("imagem: 3 (busca genérica pelo tema)")
    return imagem_por_tema(busca)


def wd_pinturas_epoca(busca, paises, ano):
    termos = [busca] + ([busca.split()[0]] if len(busca.split()) > 1 else [])
    for termo in termos:
        for pais in paises[:3]:
            ids = wd_busca(f"{termo} haswbstatement:P31=Q3305213 haswbstatement:P18 haswbstatement:P495={pais}")
            random.shuffle(ids)
            for ent in wd_entidades(ids[:20]).values():
                a = ano_wikidata(ent.get("claims", {}), "P571")
                if a and abs(a - ano) <= 50:
                    obra = wd_pintura(ent)
                    if obra:
                        return obra
    return None


def imagem_por_tema(busca):
    return (tentar(wd_pinturas, busca)
            or tentar(wd_pinturas, busca.split()[0] if busca.split() else "landscape")
            or tentar(wd_pinturas, "landscape")
            or tentar(met_busca, {"q": busca, "hasImages": "true"}, lambda o: True)
            or tentar(aic_busca, busca, lambda o: True))


NAVEGADOR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0 Safari/537.36", "Accept": "image/avif,image/webp,image/*,*/*"}


def baixar_imagem(imagem, destino):
    """Tenta a imagem grande, depois a menor; registra no diagnóstico o que falhar."""
    for url in [imagem.get("url"), imagem.get("url_menor")]:
        if not url:
            continue
        try:
            baixar_url(url, destino)
            return True
        except Exception as e:
            DIAGNOSTICO.append(f"download da imagem falhou ({url[:80]}): {type(e).__name__}: {str(e)[:150]}")
    return False


def baixar_url(url, destino):
    r = requests.get(url, headers=UA if "wiki" in url else NAVEGADOR, timeout=120)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    img.thumbnail((2048, 2048))
    img.save(destino, "JPEG", quality=88)


# ---------- textos verificados (Wikisource) ----------

def wikisource(lang, busca, autor=""):
    api = f"https://{lang}.wikisource.org/w/api.php"
    achados = requests.get(api, headers=UA, timeout=30, params={
        "action": "query", "list": "search", "srsearch": busca, "srlimit": 3, "format": "json"}).json()
    for hit in achados.get("query", {}).get("search", []):
        t_hit = norm(hit["title"].split(":", 1)[-1])
        if autor and t_hit == norm(autor):
            continue  # página do autor (biografia/lista de obras), não a obra
        p = requests.get(api, headers=UA, timeout=30, params={
            "action": "parse", "page": hit["title"], "prop": "text",
            "format": "json", "formatversion": 2}).json()
        h = p.get("parse", {}).get("text", "")
        h = re.sub(r"(?s)<(style|script)\b.*?</\1>", "", h)
        h = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", h)
        t = html.unescape(re.sub(r"<[^>]+>", "", h))
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t).strip()
        if len(t) > 300:
            return hit["title"], t[:15000]
    return None


def trecho_confere(trecho, fonte):
    f = norm(fonte)
    linhas = [norm(l) for l in trecho.splitlines() if len(norm(l)) >= 3]
    return bool(linhas) and all(l in f for l in linhas)


# ---------- montagem de cada tipo de post ----------

def post_pintura(autor, movimento=False):
    obra = obra_do_pintor(autor["nome"])
    if not obra:
        DIAGNOSTICO.append(f"{autor['nome']}: nenhuma pintura em domínio público no Met nem no AIC")
        return None
    DIAGNOSTICO.append("imagem: a própria pintura do post")
    foco = ("Escreva sobre o movimento ou escola artística a que o pintor pertence, usando esta obra "
            "como exemplo concreto do que o movimento buscava."
            if movimento else
            "Escreva sobre esta obra como quem para diante dela: o detalhe que prende o olhar, "
            "quem era o pintor naquele momento da vida e o que a tela faz com quem a vê hoje.")
    dados = claude(f"{foco}\nDados de catálogo (confiáveis): título: {obra['titulo']}; artista: "
                   f"{obra['artista']}; data: {obra['data']}; acervo: {obra['museu']}.\n"
                   'Responda: {"texto":"..."}')
    return {"texto": dados["texto"], "imagem": obra, "credito": False}


def post_com_fonte(autor, tipo):
    o_que = "um poema curto ou trecho de poema" if tipo == "poema" else \
            "um trecho de diário, caderno íntimo ou carta pessoal"
    plano = claude(f"Escolha {o_que} de {autor['nome']} que esteja no Wikisource, na língua original.\n"
                   'Responda: {"lang":"código do Wikisource (en, de, fr, it, es, pt, la, ja...)",'
                   '"busca":"termos para achar a página no Wikisource"}')
    achado = wikisource(plano["lang"], plano["busca"], autor["nome"])
    if not achado:
        DIAGNOSTICO.append(f"{autor['nome']}: nada no Wikisource ({plano['lang']}) para '{plano['busca']}'")
        return None
    titulo, fonte = achado
    for _ in range(2):
        dados = claude(
            f"Fonte: Wikisource ({plano['lang']}), página '{titulo}', de {autor['nome']}:\n<<<\n{fonte}\n>>>\n"
            "Escolha um trecho de 2 a 8 linhas copiado EXATAMENTE da fonte acima, sem alterar nada. "
            "O trecho tem de ser versos ou prosa escritos pelo autor: nunca cabeçalho da página, "
            "título, datas, dados biográficos, notas ou índice. Se a fonte não tiver texto literário, "
            'responda {"trecho_original":"","texto":"","busca_imagem":""}. '
            "Monte o post: o trecho original, a tradução (se necessária) e de 2 a 4 frases de contexto.\n"
            'Responda: {"trecho_original":"...","texto":"post completo contendo o trecho original '
            'idêntico","busca_imagem":"2 ou 3 palavras em inglês para achar uma obra de museu '
            'de até 1910 com o mesmo clima"}', max_tokens=8000)
        trecho = dados.get("trecho_original", "")
        if not trecho.strip() or re.search(r"[†*]", trecho):
            DIAGNOSTICO.append(f"{autor['nome']}: fonte '{titulo}' sem trecho literário utilizável")
            return None
        if trecho_confere(dados["trecho_original"], fonte) and \
                norm(dados["trecho_original"]) in norm(dados["texto"]):
            return {"texto": dados["texto"], "imagem": imagem_do_post(autor, dados["busca_imagem"]),
                    "credito": True, "trecho": trecho}
    DIAGNOSTICO.append(f"{autor['nome']}: trecho não conferiu com a fonte '{titulo}'")
    return None


def post_musica(autor):
    dados = claude(
        f"Escolha uma obra de {autor['nome']} que você tenha certeza absoluta de que existe. "
        "Escreva como quem acabou de ouvir e quer contar a um amigo: o momento da música que pega "
        "(descrito de forma concreta: um acorde, uma entrada, um silêncio), o que o compositor vivia "
        "quando a escreveu, e termine com: Para ouvir: busque \"compositor, título da obra\". "
        "Não cite intérpretes nem gravações.\n"
        'Responda: {"texto":"...","busca_imagem":"2 ou 3 palavras em inglês para achar um '
        'instrumento, partitura ou cena musical de museu de até 1910"}')
    return {"texto": dados["texto"], "imagem": imagem_do_post(autor, dados["busca_imagem"]), "credito": True}


def post_teoria(autor):
    dados = claude(
        f"Explique uma ideia central de teoria literária, poética ou estética de {autor['nome']} "
        "(obra de até 1910), em paráfrase, sem citação literal. Parta de uma cena da obra ou da vida "
        "comprovada do autor, e mostre por que a ideia ainda importa hoje (em termos gerais, sem "
        "inventar episódios pessoais).\n"
        'Responda: {"texto":"...","busca_imagem":"2 ou 3 palavras em inglês para achar uma obra de '
        'museu de até 1910 ligada ao tema"}')
    return {"texto": dados["texto"], "imagem": imagem_do_post(autor, dados["busca_imagem"]), "credito": True}


VIVENCIA = re.compile(
    r"\b(uma? amig[oa]|meu amigo|minha amiga|amigos meus|ontem|anteontem|de madrugada|na madrugada"
    r"|no bar|num bar|no café|num café|no metrô|no ônibus|na fila|semana passada|outro dia|certa vez"
    r"|quando eu era|me disse|me contou|me falou|minha mãe|meu pai|minha avó|meu avô"
    r"|minha namorada|meu namorado|minha mulher|meu marido|meu professor|minha professora)\b", re.I)


def revisar_vivencia(post, autor):
    """Vivência inventada no nome de quem assina ('um amigo', 'no bar', 'de madrugada'...):
    pede UMA reescrita. O trecho original (poema/diário) não entra na checagem."""
    trecho = post.get("trecho", "")
    def marcas(t):
        return sorted({m.lower() for m in VIVENCIA.findall(t.replace(trecho, "") if trecho else t)})
    achadas = marcas(post["texto"])
    if not achadas:
        return post
    DIAGNOSTICO.append(f"{autor['nome']}: marcas de vivência inventada ({', '.join(achadas)}); reescrita pedida")
    novo = claude(
        "Reescreva o post abaixo sem nenhuma vivência pessoal inventada de quem assina o perfil "
        f"(marcas encontradas: {', '.join(achadas)}). Se a abertura for uma cena da vida de quem assina, "
        "troque por uma cena da obra ou da vida comprovada do autor. A primeira pessoa pode reagir à obra. "
        "Mantenha o resto, o tamanho e o tom; trecho original e tradução, se houver, ficam idênticos.\n"
        f"<<<\n{post['texto']}\n>>>\n" 'Responda: {"texto":"..."}').get("texto", "").strip()
    if not novo or (trecho and norm(trecho) not in norm(novo)):
        DIAGNOSTICO.append(f"{autor['nome']}: reescrita descartada (vazia ou sem o trecho original)")
        return post
    resto = marcas(novo)
    DIAGNOSTICO.append(f"{autor['nome']}: reescrito" + (f"; ainda contém: {', '.join(resto)}" if resto else ""))
    post["texto"] = novo
    return post


def montar(categoria, autores, hoje):
    so_desconhecidos = categoria == "esquecido"
    area = random.choice(list(TIPO_DA_AREA)) if so_desconhecidos else AREA_DA_CATEGORIA[categoria]
    tipo = TIPO_DA_AREA[area]
    tentados = set()
    for _ in range(5):
        autor = escolher(autores, area, hoje, so_desconhecidos, evitar=tentados)
        if not autor:
            return None
        tentados.add(autor["nome"])
        try:
            if tipo == "pintura":
                post = post_pintura(autor, movimento=(categoria == "movimento"))
            elif tipo in ("poema", "diario"):
                post = post_com_fonte(autor, tipo)
            elif tipo == "musica":
                post = post_musica(autor)
            else:
                post = post_teoria(autor)
            if post:
                post = revisar_vivencia(post, autor)
        except ApiBloqueada:
            raise
        except Exception as e:  # um autor problemático não derruba a execução
            print(f"Falhou com {autor['nome']}: {e}")
            DIAGNOSTICO.append(f"{autor['nome']}: erro {type(e).__name__}: {str(e)[:300]}")
            post = None
        if post and not post.get("imagem"):
            DIAGNOSTICO.append(f"{autor['nome']}: texto pronto, mas nenhuma imagem encontrada")
        if post and len(post.get("texto", "")) > 3000:
            DIAGNOSTICO.append(f"{autor['nome']}: texto longo demais ({len(post['texto'])} caracteres)")
        if post and post.get("imagem") and len(post["texto"]) <= 3000:
            registrar_uso(autor, hoje)
            return post
    return None


# ---------- comandos ----------

def pausar_por_bloqueio(erro, categoria, estado, autores):
    """Sem crédito/chave não adianta tentar 10 autores nem falhar a execução toda vez:
    registra, avisa no Telegram no máximo 1 vez por dia e encerra sem erro."""
    status, _, corpo = str(erro).partition(" ")
    motivo, solucao = explicar_bloqueio(int(status) if status.isdigit() else 0, corpo)
    agora = datetime.datetime.now(datetime.timezone.utc)
    (RAIZ / "bot" / "ultimo_diagnostico.txt").write_text(
        f"{agora.isoformat()} categoria={categoria}\nPAUSADO: {motivo}\nResposta da API: {erro}\n"
        + "\n".join(DIAGNOSTICO), encoding="utf-8")
    estado["proxima"] = estado.get("proxima", 1) - 1  # não pula a categoria
    estado["pendente"] = None
    hoje = agora.date().isoformat()
    if estado.get("aviso_bloqueio") != hoje:
        estado["aviso_bloqueio"] = hoje
        try:
            avisar(f"⚠️ Diário cultural pausado: {motivo}\nComo resolver: {solucao}\n"
                   "(Este aviso sai no máximo 1 vez por dia.)", aviso=True)
        except Exception as e:
            print(f"aviso no Telegram falhou: {e}")
    gravar(AUTORES, autores)
    gravar(ESTADO, estado)
    print(f"Pausado: {motivo} | {erro}")


def gerar():
    hoje = datetime.date.today()
    autores = ler(AUTORES, [])
    estado = ler(ESTADO, {"offset": 0, "proxima": 0, "pendente": None})
    processar_comandos(estado, autores)

    categoria = CICLO[estado.get("proxima", 0) % len(CICLO)]
    estado["proxima"] = estado.get("proxima", 0) + 1

    try:
        post = montar(categoria, autores, hoje) or montar("pintura", autores, hoje)
    except ApiBloqueada as e:
        pausar_por_bloqueio(e, categoria, estado, autores)
        return
    (RAIZ / "bot" / "ultimo_diagnostico.txt").write_text(
        f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} categoria={categoria}\n"
        + "\n".join(DIAGNOSTICO), encoding="utf-8")
    if not post:
        gravar(AUTORES, autores)
        gravar(ESTADO, estado)
        print("O post desta execução falhou:\n" + "\n".join(DIAGNOSTICO[-8:]))
        sys.exit("Nenhum post gerado nesta execução.")

    pid = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M")
    POSTS.mkdir(parents=True, exist_ok=True)
    if not baixar_imagem(post["imagem"], POSTS / f"{pid}.jpg"):
        reserva = tentar(wd_pinturas, "landscape")
        if not (reserva and baixar_imagem(reserva, POSTS / f"{pid}.jpg")):
            raise RuntimeError("nenhuma imagem pôde ser baixada")
        post["imagem"], post["credito"] = reserva, True

    texto = post["texto"].strip()
    if post["credito"]:
        i = post["imagem"]
        partes = ", ".join(x for x in (i["titulo"], i["artista"], i["data"]) if x)
        texto += f"\n\nImagem: {partes}. {i['museu']}."
    gravar(POSTS / f"{pid}.json", {"texto": texto, "imagem": f"{pid}.jpg", "categoria": categoria})

    estado["pendente"] = pid
    gravar(AUTORES, autores)
    gravar(ESTADO, estado)
    print(f"Post {pid} ({categoria}) gerado.")


def enviar():
    estado = ler(ESTADO, {})
    pid = estado.get("pendente")
    if not pid:
        return
    post = ler(POSTS / f"{pid}.json", None)
    pagina = f"{os.environ['PAGES_URL'].rstrip('/')}/enviar.html?id={pid}"
    telegram("sendMessage", data={**destino(), "parse_mode": "HTML",
                                  "text": f"<pre>{html.escape(post['texto'])}</pre>"})
    with open(POSTS / post["imagem"], "rb") as f:
        telegram("sendPhoto", files={"photo": f}, data={
            **destino(),
            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "Enviar ao X", "url": pagina}]]}),
        })


def ensaio(categoria):
    """Execução de ensaio: gera um post da categoria pedida sem gravar estado, sem publicar e
    sem mandar ao Telegram. Mostra texto, imagem e diagnóstico no log e no resumo da execução."""
    global ENSAIO
    ENSAIO = True
    post = montar(categoria, ler(AUTORES, []), datetime.date.today())
    i = (post or {}).get("imagem") or {}
    saida = (f"## Ensaio: {categoria}\n\n" + "\n".join(f"- {d}" for d in DIAGNOSTICO) + "\n\n"
             + (f"**Texto:**\n\n```\n{post['texto']}\n```\n\n**Imagem:** "
                f"{', '.join(x for x in (i.get('titulo'), i.get('artista'), i.get('data')) if x)} "
                f"({i.get('museu')}) {i.get('url')}\n" if post else "Nenhum post gerado.\n"))
    print(saida)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(saida)
    if not post:
        sys.exit("Ensaio sem post.")


if __name__ == "__main__":
    import traceback
    try:
        if sys.argv[1] == "ensaio":
            ensaio(sys.argv[2])
            sys.exit(0)
        {"gerar": gerar, "enviar": enviar}[sys.argv[1]]()
    except SystemExit:
        raise
    except Exception:
        erro = traceback.format_exc()
        print(erro)
        (RAIZ / "bot" / "ultimo_diagnostico.txt").write_text(
            f"{sys.argv[1]} falhou\n" + "\n".join(DIAGNOSTICO) + "\n\n" + erro, encoding="utf-8")
        sys.exit(1)  # o aviso no Telegram sai pelo avisos.py do workflow
