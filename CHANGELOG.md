# Changelog — SMC Monitor

## v0.1.5 — 2026-04-19

### Added
- bot_handler.py: bot Telegram bidirecional com long-polling manual
- Comandos: /ajuda, /ping, /status, /snapshot (alias /btc), /sinais,
  /trades, /performance (alias /perf)
- Whitelist de chat_ids via TELEGRAM_AUTHORIZED_CHAT_IDS
- Cooldown de 1s por (chat_id, command) contra spam
- Tabela bot_state no smc_state.db para persistência de last_update_id
- Registro de menu de comandos no Telegram via setMyCommands

### Changed
- config.py: adicionadas TELEGRAM_AUTHORIZED_CHAT_IDS e BOT_POLL_TIMEOUT
- main.py: inicia thread do bot após setup do engine e WebSocket
- state.py: nova função ensure_bot_state_table()
