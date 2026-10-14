"""Central no Claude: substitui o Telegram como destino das mensagens dos bots.

Cada mensagem vira uma linha em central_novo/saida.jsonl (com áudios e imagens ao lado).
No fim do workflow, `python3 central.py publicar` junta tudo na branch `central` do
repositório (1 commit só, últimos 7 dias). O avisos.py chama isso sozinho no último
passo de cada workflow. O painel-central do alerta-ema lê essas
branches, monta o feed e manda para o Google Drive, de onde a página Central lê.

Telegram volta a funcionar só com a variável TELEGRAM_ATIVO=sim.
Mesmo arquivo nos repositórios alerta-ema, Jornal-DE-JP e diario-cultural.
"""
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid

NOVO = pathlib.Path("central_novo")
DIAS = 7


def ativa():
    return (os.environ.get("TELEGRAM_ATIVO") or "").lower() != "sim"


def publicar_item(fonte, tipo, texto="", html=False, arquivos=(), extra=None):
    """Grava uma mensagem para a Central. arquivos = caminhos de áudio/imagem a anexar."""
    NOVO.mkdir(exist_ok=True)
    (NOVO / "arquivos").mkdir(exist_ok=True)
    agora = datetime.datetime.now(datetime.timezone.utc)
    iid = agora.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    nomes = []
    for i, (caminho, titulo) in enumerate(arquivos):
        p = pathlib.Path(caminho)
        if p.exists():
            nome = f"{iid}-{i}{p.suffix.lower()}"
            shutil.copy(p, NOVO / "arquivos" / nome)
            nomes.append({"arquivo": nome, "titulo": titulo})
    item = {"id": iid, "t": agora.isoformat(timespec="seconds"), "fonte": fonte, "tipo": tipo,
            "texto": texto, "html": bool(html), "anexos": nomes, "extra": extra or {}}
    with open(NOVO / "saida.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Central: {fonte}/{tipo} gravado ({len(nomes)} anexo(s))")
    return iid


def _git(*args, cwd=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def publicar_branch():
    """Junta central_novo/ com a branch `central` e regrava (1 commit, últimos 7 dias)."""
    if not (NOVO / "saida.jsonl").exists():
        print("Central: nada novo")
        return
    repo = os.environ.get("GITHUB_REPOSITORY")
    url = f"https://github.com/{repo}" if repo else None
    # usa a credencial que o actions/checkout já deixou no repositório principal
    cab = _git("config", "--get", "http.https://github.com/.extraheader", check=False).stdout.strip()
    auth = ["-c", f"http.https://github.com/.extraheader={cab}"] if cab else []
    for tentativa in range(4):
        tmp = pathlib.Path("/tmp/central_branch")
        shutil.rmtree(tmp, ignore_errors=True)
        r = _git(*auth, "clone", "-q", "--depth", "1", "-b", "central", url, str(tmp), check=False) if url else None
        if not r or r.returncode != 0:
            tmp.mkdir(parents=True, exist_ok=True)
        antigo = _git("rev-parse", "HEAD", cwd=tmp, check=False).stdout.strip() if (tmp / ".git").exists() else ""
        (tmp / "arquivos").mkdir(exist_ok=True)
        itens = []
        if (tmp / "saida.jsonl").exists():
            itens = [json.loads(x) for x in (tmp / "saida.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        ids = {i["id"] for i in itens}
        for x in (NOVO / "saida.jsonl").read_text(encoding="utf-8").splitlines():
            if x.strip():
                i = json.loads(x)
                if i["id"] not in ids:
                    itens.append(i)
        for f in (NOVO / "arquivos").glob("*"):
            shutil.copy(f, tmp / "arquivos" / f.name)
        corte = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DIAS)).isoformat()
        itens = sorted((i for i in itens if i["t"] >= corte), key=lambda i: i["t"])
        vivos = {a["arquivo"] for i in itens for a in i.get("anexos", [])}
        for f in (tmp / "arquivos").glob("*"):
            if f.name not in vivos:
                f.unlink()
        (tmp / "saida.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in itens), encoding="utf-8")
        shutil.rmtree(tmp / ".git", ignore_errors=True)
        _git("init", "-q", cwd=tmp)
        _git("checkout", "-q", "-b", "central", cwd=tmp)
        _git("add", "-A", cwd=tmp)
        _git("-c", "user.name=central-bot", "-c", "user.email=central-bot@users.noreply.github.com",
             "commit", "-qm", "central", cwd=tmp)
        if not url or not cab:
            print("Central: fora do GitHub Actions, não publiquei (ensaio)")
            return
        lease = f"--force-with-lease=central:{antigo}" if antigo else "--force"
        p = _git(*auth, "push", "-q", lease, url, "central", cwd=tmp, check=False)
        if p.returncode == 0:
            print(f"Central: publicado ({len(itens)} itens nos últimos {DIAS} dias)")
            return
        print(f"Central: outro envio ao mesmo tempo, tentando de novo ({tentativa + 1})")
    raise RuntimeError("Central: não consegui publicar na branch central")


if __name__ == "__main__":
    if sys.argv[1:] == ["publicar"]:
        publicar_branch()
