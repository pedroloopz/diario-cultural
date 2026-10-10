"""Descobre o chat_id do grupo e o message_thread_id de cada tópico.

Antes de rodar: mande uma mensagem qualquer em cada tópico do grupo. Rode logo depois:
os bots leem o chat sozinhos e, depois disso, as mensagens já lidas somem desta lista.
Não consome nada (lê sem offset) e manda o resultado no chat atual e no resumo da execução.
Só biblioteca padrão.
"""
import json
import os
import urllib.parse
import urllib.request

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def api(metodo, **dados):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{metodo}",
                                 data=urllib.parse.urlencode(dados).encode())
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def coletar(updates):
    """Devolve {chat_id: {"nome", "forum", "topicos": {thread_id: nome}}}."""
    grupos = {}
    for u in updates:
        m = u.get("message") or u.get("edited_message") or u.get("my_chat_member") or \
            (u.get("callback_query") or {}).get("message") or {}
        chat = m.get("chat") or {}
        if chat.get("type") not in ("group", "supergroup"):
            continue
        g = grupos.setdefault(chat["id"], {"nome": chat.get("title", ""), "forum": bool(chat.get("is_forum")),
                                           "topicos": {}})
        tid = m.get("message_thread_id")
        criado = m.get("forum_topic_created") or (m.get("reply_to_message") or {}).get("forum_topic_created") or {}
        if tid and (m.get("is_topic_message") or criado):
            g["topicos"][tid] = criado.get("name") or g["topicos"].get(tid) or "(nome não visto)"
    return grupos


def texto(grupos, eu):
    if not grupos:
        return ("Nenhum grupo encontrado. Confira: 1) o bot @" + eu + " está no grupo; 2) o modo de "
                "privacidade está desligado (@BotFather → /setprivacy → Disable) e o bot foi removido e "
                "adicionado de novo ao grupo; 3) você mandou uma mensagem em cada tópico pouco antes de rodar.")
    L = [f"IDs vistos pelo bot @{eu}:"]
    for cid, g in grupos.items():
        L.append(f"\nGrupo: {g['nome']}\nTELEGRAM_CHAT_ID = {cid}" + ("" if g["forum"] else "  (tópicos desligados)"))
        for tid, nome in sorted(g["topicos"].items()):
            L.append(f"  {nome}: message_thread_id = {tid}")
        if g["forum"] and not g["topicos"]:
            L.append("  Nenhum tópico visto: mande uma mensagem em cada tópico e rode de novo.")
    L.append("\nTópico 'General' não tem número: não use para os bots.")
    return "\n".join(L)


def main():
    eu = api("getMe")["result"].get("username", "?")
    res = texto(coletar(api("getUpdates", timeout=0).get("result", [])), eu)
    print(res)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("```\n" + res + "\n```\n")
    if CHAT:
        try:
            api("sendMessage", chat_id=CHAT, text=res)
        except Exception as e:
            print(f"não consegui mandar no chat atual: {e}")


if __name__ == "__main__":
    main()
