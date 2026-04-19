# Changelog — SMC Monitor

## v0.1.6 — 2026-04-19

### Added
- historical_loader.py: warm-up de histórico via OKX REST no boot do daemon
  - Busca 500 candles 15m, 500 candles 1H, 300 candles 4H via REST
  - Auditoria de 5 tipos de problema: gaps, duplicatas, desordem, malformação, gap-até-agora
  - Estratégia híbrida de correção: refetch (Estratégia A) → forward fill com volume=0 (B)
  - Aborta boot em falha catastrófica (qualquer TF < 50% do alvo)
  - Envia alerta Telegram crítico em caso de falha
- smc_engine.bootstrap_from_history(): popula buffers com DataFrames históricos
- state.ensure_historical_synthesis_table(): tabela nova para auditoria de sínteses
- Tabela historical_synthesis no smc_state.db: registra candles sintetizados ou refetchados

### Changed
- main.py: ordem de boot agora inclui warm-up histórico ANTES de ws_feed.start()
- config.py: constantes HIST_* para parametrização do warm-up
- Todos os 11 módulos bumpados para 0.1.6 (regra de padronização)

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
