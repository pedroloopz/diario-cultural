# CLAUDE.md — diario-cultural

## O que é
Bot que gera 3 posts por dia sobre arte, literatura e música (até 1910) com a API do Claude,
publica no GitHub Pages (`docs/`) e manda ao Telegram com o botão "Enviar ao X".

- Código: `bot/main.py` (`gerar` cria o post; `enviar` manda ao Telegram e lê `/remover Nome`)
- Rodízio de autores: `bot/autores.json` (10 posts por autor, depois 90 dias de descanso)
- Estado e diagnóstico: `bot/estado.json`, `bot/ultimo_diagnostico.txt`
- Workflow: `.github/workflows/diario.yml` — 07h, 12h e 18h de Brasília (10, 15 e 21 UTC)
- Sem crédito na API: pausa sem falhar e avisa no máximo 1x por dia.

## Segredos e variáveis (só os nomes)
- Secrets: `ANTHROPIC_API_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `PAGES_URL`
- Variables: `CLAUDE_MODEL` (vazio = modelo padrão do código), `TELEGRAM_THREAD_ID` (tópico 🎨 Diário cultural), `TELEGRAM_AVISOS_THREAD_ID` (⚠️ Avisos)

## Como testar
- Sintaxe: `python -m py_compile bot/main.py`
- Ensaio: Actions → diario-cultural → Run workflow → `ensaio: teoria|musica|poema` (não publica nem manda ao Telegram; texto, imagem e diagnóstico no resumo da execução). **Cada execução custa ~US$ 0,04**; no máximo 5 por tarefa.
- Conferir `bot/ultimo_diagnostico.txt` e o post em `docs/posts/`.

## Regras do Pedro
- Pedro não tem computador: tudo roda no GitHub Actions e se configura pelo navegador do celular (Android).
- Não quebre o que funciona. Antes de mudar, leia o código e os workflows e resuma em 5 linhas o que existe.
- Teste antes (pytest, execução de ensaio ou `workflow_dispatch`); depois commit e push direto na `main`. Push bloqueado → abra PR e faça o merge. Teste falhou e não dá para corrigir → desfaça e explique.
- Mensagens dos bots em português.
- Segredos só via `secrets`/`vars` do GitHub. Nunca chave no código nem no log; nunca peça token colado na conversa.
- Dependeu de decisão do Pedro → pare e pergunte em uma frase, com opções.
- **Custo:** este é o único bot que usa a API paga do Claude (crédito só para ele). Não aumente o número de chamadas sem perguntar.
- Conteúdo: tom humano, mas **nada de vivência inventada** do Pedro (pessoas, lugares, episódios). Cenas só da obra ou da vida comprovada do autor. Marcas de vivência (`VIVENCIA` em `bot/main.py`) pedem uma reescrita.
- Imagem (teoria, poema, diário, música): 1) retrato do autor no Wikidata; 2) obra do mesmo país e época; 3) busca genérica. O diagnóstico diz qual.
- **Privacidade:** o bot é admin do grupo e recebe tudo. Só processa mensagens do próprio tópico (`do_meu_topico`); as de outros tópicos (📸 Família, 📝 Rascunhos…) são descartadas sem salvar, logar ou enviar ao Claude.
- Erros vão para ⚠️ Avisos via `avisos.py` (mesma falha 2x seguidas, 1 aviso/dia, ignora rede/429/5xx).

## Como trabalhar
- **Pense antes de codar:** diga as suposições em voz alta; se o pedido aceita mais de uma leitura, pergunte em vez de escolher calado.
- **Simplicidade primeiro:** escreva o menor código que resolve. Nada de opção, camada ou recurso que não foi pedido.
- **Mudanças cirúrgicas:** toque só nas linhas necessárias. Não reformate, não renomeie, não "melhore" o código vizinho.
- **Objetivo verificável:** antes de começar, diga como saber que deu certo (teste ou execução de ensaio). Só termine quando passar.
