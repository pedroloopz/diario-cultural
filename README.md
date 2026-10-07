# Diário cultural

Bot que gera 3 posts por dia (arte, literatura e música até 1910) e manda ao Telegram com o botão "Enviar ao X".

- Código: `bot/main.py`
- Autores e rodízio: `bot/autores.json` (10 posts por autor, depois 90 dias de descanso)
- Página do botão: `docs/enviar.html` (GitHub Pages, pasta /docs)
- Agendamento: `.github/workflows/diario.yml`

Segredos necessários: `ANTHROPIC_API_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `PAGES_URL`.
