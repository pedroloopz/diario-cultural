"""Avisos de erro no tópico ⚠️ Avisos do Telegram, com filtro contra alarme falso.

Regra: só avisa quando a MESMA falha acontece 2 vezes seguidas no mesmo fluxo, no máximo
1 aviso por fluxo por dia. Erro passageiro (rede, 429, 5xx) não conta. Estado em .avisos/.

No workflow (último passo, if: always()):
    python3 avisos.py "<fluxo>" "${{ job.status }}"
  lê o fim do run.log quando a execução falhou e grava o estado com git.
No código Python:
    import avisos; avisos.registrar("bot-aster", erro=str(e))   # ou erro=None quando deu certo
Só biblioteca padrão: roda mesmo se o pip install falhou.
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

PASTA = pathlib.Path(".avisos")
BRT = datetime.timezone(datetime.timedelta(hours=-3))

PASSAGEIRO = re.compile(
    r"ConnectionError|ConnectTimeout|ReadTimeout|TimeoutError|timed out|Max retries exceeded"
    r"|RemoteDisconnected|Connection (reset|aborted|refused)|Temporary failure in name resolution"
    r"|NameResolutionError|Name or service not known|Too Many Requests|rate.?limit|overloaded"
    r"|não respondeu|nao respondeu"
    r"|(HTTP|status|Server Error|API|Telegram|Gemini|recusou)\D{0,40}\b(429|5\d\d)\b"
    r"|\b(429|5\d\d) (Server Error|Too Many)",
    re.I)


def passageiro(erro):
    return bool(PASSAGEIRO.search(erro or ""))


def assinatura(erro):
    """Mesma falha = mesma última linha, ignorando números (horários, ids, valores)."""
    linhas = [l.strip() for l in (erro or "").splitlines() if l.strip()]
    return re.sub(r"\d+", "#", linhas[-1] if linhas else "sem detalhes")[:300]


def telegram(texto):
    token, chat = os.environ.get("TELEGRAM_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        print("aviso (sem Telegram configurado):\n" + texto)
        return
    dados = {"chat_id": chat, "text": texto[:4000]}
    topico = (os.environ.get("TELEGRAM_AVISOS_THREAD_ID") or os.environ.get("TELEGRAM_THREAD_ID") or "").strip()
    if topico:
        dados["message_thread_id"] = topico
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=urllib.parse.urlencode(dados).encode())
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:  # o aviso nunca derruba o bot
        print(f"aviso no Telegram falhou: {e}")


def registrar(fluxo, erro=None, log_url=""):
    """erro=None: deu certo (zera a sequência). Devolve True se o estado mudou."""
    arq = PASTA / (re.sub(r"[^\w-]+", "_", fluxo) + ".json")
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    antes = dict(est)
    if erro is None:
        est["seguidas"], est["falha"] = 0, None
    elif passageiro(erro):
        print(f"[avisos] {fluxo}: erro passageiro, não conta: {assinatura(erro)}")
        return False
    else:
        sig = assinatura(erro)
        est["seguidas"] = est.get("seguidas", 0) + 1 if est.get("falha") == sig else 1
        est["falha"] = sig
        hoje = datetime.datetime.now(BRT).date().isoformat()
        if est["seguidas"] >= 2 and est.get("avisado_em") != hoje:
            est["avisado_em"] = hoje
            detalhe = "\n".join(l[:200] for l in erro.strip().splitlines()[-12:])[-1500:]
            telegram(f"⚠️ {fluxo} falhou {est['seguidas']} vezes seguidas com o mesmo erro.\n"
                     f"{detalhe}" + (f"\nLog: {log_url}" if log_url else "") +
                     "\n(No máximo 1 aviso por dia para este fluxo.)")
    if est == antes or (not antes and erro is None):
        return False
    PASTA.mkdir(exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def git_salvar():
    git = ["git", "-c", "user.name=avisos-bot", "-c", "user.email=avisos-bot@users.noreply.github.com"]
    subprocess.run(git + ["add", str(PASTA)], check=False)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(git + ["commit", "-q", "-m", "avisos: estado das falhas"], check=False)
    ramo = os.environ.get("GITHUB_REF_NAME", "")
    for _ in range(3):
        subprocess.run(git + ["pull", "-q", "--rebase", "origin", ramo], check=False)
        if subprocess.run(git + ["push", "-q", "origin", f"HEAD:{ramo}"]).returncode == 0:
            return


def main(fluxo, status, log="run.log"):
    if status not in ("success", "failure"):
        return
    erro = None
    if status == "failure":
        p = pathlib.Path(log)
        erro = p.read_text(encoding="utf-8", errors="replace")[-6000:] if p.exists() else ""
        erro = erro.strip() or "falhou antes do script (sem log)"
        print(f"::error title={fluxo}::" + assinatura(erro).replace("%", "%25"))
    url = (f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}"
           f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}") if os.environ.get("GITHUB_RUN_ID") else ""
    registrar(fluxo, erro, url)
    if os.environ.get("GITHUB_ACTIONS") and PASTA.exists():
        git_salvar()


if __name__ == "__main__":
    try:
        main(*sys.argv[1:3])
    except Exception as e:  # nunca falha o job por causa do aviso
        print(f"[avisos] erro interno: {e}")
