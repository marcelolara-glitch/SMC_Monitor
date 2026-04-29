#!/usr/bin/env bash
# ============================================================================
# Freqtrade — Diagnóstico completo (sem assumir paths)
# ----------------------------------------------------------------------------
# Objetivo: validar se o Freqtrade está rodando saudável em dry-run com a
# SampleStrategy, antes de avançar para a estratégia SMC.
#
# Não altera nada. Só lê.
#
# Cobre:
#   1. Descoberta — onde está instalado, onde está o config, onde estão logs
#   2. Processo — daemon vivo? como? supervisor?
#   3. Sistema — recursos VM (disk, RAM, uptime)
#   4. Config — modo (dry-run?), exchange, par, timeframe, stake
#   5. Pipeline de dados — candles atualizados? gaps?
#   6. Estratégia — qual está carregada? quantos trades simulados?
#   7. Performance dry-run — wins/losses/PnL paper
#   8. Canais — Telegram OK? FreqUI OK? API exchange OK?
#   9. Logs — erros recentes, warnings, padrões anômalos
#  10. Backtest histórico — existe? bate com forward?
# ============================================================================

set -u  # erro em var indefinida; NÃO usar -e (queremos ver tudo, mesmo com falha)

echo "============================================================"
echo "  FREQTRADE — DIAGNÓSTICO COMPLETO"
echo "  Data:  $(date -Iseconds)"
echo "  Host:  $(hostname)"
echo "  User:  $(whoami)"
echo "  PWD:   $(pwd)"
echo "  Uptime: $(uptime -p 2>/dev/null || uptime)"
echo "============================================================"

# ============================================================================
# 1. DESCOBERTA — onde tudo vive
# ============================================================================
echo
echo "############################################################"
echo "### 1. DESCOBERTA"
echo "############################################################"

echo
echo "--- 1.1 Diretórios candidatos para o Freqtrade ---"
for dir in ~/freqtrade ~/SMC_Monitor ~/SMC_Freqtrade ~/SMC_Monitor/freqtrade-config; do
  if [ -d "$dir" ]; then
    echo "  ✓ EXISTE: $dir"
    ls -la "$dir" 2>/dev/null | head -20
    echo
  else
    echo "  ✗ não existe: $dir"
  fi
done

echo
echo "--- 1.2 Localizar binário freqtrade (instalação real) ---"
which freqtrade 2>/dev/null || echo "(freqtrade não está no PATH global)"
find ~ -maxdepth 5 -type f -name "freqtrade" -executable 2>/dev/null | head -5
find ~ -maxdepth 5 -type d -name ".venv" 2>/dev/null | head -5

echo
echo "--- 1.3 Localizar arquivos de config (config.json) ---"
find ~ -maxdepth 6 -type f -name "config.json" 2>/dev/null \
  -not -path "*/node_modules/*" -not -path "*/.git/*" | head -20

echo
echo "--- 1.4 Localizar diretório user_data ---"
find ~ -maxdepth 5 -type d -name "user_data" 2>/dev/null | head -10

echo
echo "--- 1.5 Localizar logs recentes (.log modificados nas últimas 48h) ---"
find ~ -maxdepth 6 -type f -name "*.log" -mtime -2 2>/dev/null \
  -not -path "*/node_modules/*" -not -path "*/.git/*" | head -20

echo
echo "--- 1.6 Localizar SQLite db (trades dry-run) ---"
find ~ -maxdepth 6 -type f \( -name "*.sqlite" -o -name "*.db" \) 2>/dev/null \
  -not -path "*/node_modules/*" -not -path "*/.git/*" | head -10

# ============================================================================
# 2. PROCESSO — daemon vivo?
# ============================================================================
echo
echo "############################################################"
echo "### 2. PROCESSO"
echo "############################################################"

echo
echo "--- 2.1 ps aux para freqtrade ---"
ps auxww | grep -iE "freqtrade|python.*trade" | grep -v grep || \
  echo "(NENHUM processo freqtrade rodando)"

echo
echo "--- 2.2 pgrep -af freqtrade ---"
pgrep -af "freqtrade" 2>/dev/null || echo "(pgrep não encontrou)"

echo
echo "--- 2.3 Hierarquia (PPID — quem é o pai?) ---"
for pid in $(pgrep -f "freqtrade trade" 2>/dev/null); do
  echo "PID $pid:"
  ps -o pid,ppid,user,etime,cmd -p "$pid" 2>/dev/null
  ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
  if [ -n "$ppid" ] && [ "$ppid" != "1" ]; then
    echo "  parent (PPID=$ppid):"
    ps -o pid,ppid,user,cmd -p "$ppid" 2>/dev/null
  fi
done

echo
echo "--- 2.4 Sessões tmux ---"
tmux ls 2>/dev/null || echo "(sem sessões tmux)"

echo
echo "--- 2.5 Sessões screen ---"
screen -ls 2>/dev/null | head -10 || echo "(sem sessões screen ou screen não instalado)"

echo
echo "--- 2.6 Systemd (algum freqtrade?) ---"
systemctl list-units --type=service --state=running 2>/dev/null | grep -i freq || \
  echo "(nenhum service freqtrade no systemd)"
ls /etc/systemd/system/*freq*.service 2>/dev/null || echo "(sem unit file de freqtrade)"

echo
echo "--- 2.7 nohup.out ---"
ls -lh ~/nohup.out ~/freqtrade/nohup.out ~/SMC_Monitor/nohup.out 2>/dev/null || \
  echo "(sem nohup.out em paths comuns)"

# ============================================================================
# 3. SISTEMA — recursos da VM
# ============================================================================
echo
echo "############################################################"
echo "### 3. SISTEMA (VM)"
echo "############################################################"

echo
echo "--- 3.1 Memória ---"
free -h

echo
echo "--- 3.2 Disco ---"
df -h / /home 2>/dev/null | head -5

echo
echo "--- 3.3 Load average ---"
uptime

echo
echo "--- 3.4 Top 5 processos por CPU ---"
ps aux --sort=-%cpu | head -6

echo
echo "--- 3.5 Top 5 processos por memória ---"
ps aux --sort=-%mem | head -6

echo
echo "--- 3.6 Reboot pendente? ---"
if [ -f /var/run/reboot-required ]; then
  echo "  ⚠️  REBOOT PENDENTE"
  cat /var/run/reboot-required 2>/dev/null
  cat /var/run/reboot-required.pkgs 2>/dev/null | head -10
else
  echo "  ✓ sem reboot pendente"
fi

# ============================================================================
# 4. CONFIG — o que está rodando?
# ============================================================================
echo
echo "############################################################"
echo "### 4. CONFIG"
echo "############################################################"

# tenta achar o config principal
CONFIG_CANDIDATE=""
for c in ~/SMC_Monitor/user_data/config.json \
         ~/SMC_Freqtrade/user_data/config.json \
         ~/freqtrade/user_data/config.json \
         ~/SMC_Monitor/freqtrade-config/config.json \
         ~/freqtrade/config.json; do
  if [ -f "$c" ]; then
    CONFIG_CANDIDATE="$c"
    break
  fi
done

# fallback: pega o primeiro config.json não-trivial achado
if [ -z "$CONFIG_CANDIDATE" ]; then
  CONFIG_CANDIDATE=$(find ~ -maxdepth 6 -type f -name "config.json" 2>/dev/null \
    -not -path "*/node_modules/*" -not -path "*/.git/*" | head -1)
fi

echo
echo "--- 4.1 Config detectado: ${CONFIG_CANDIDATE:-NENHUM} ---"

if [ -n "$CONFIG_CANDIDATE" ] && [ -f "$CONFIG_CANDIDATE" ]; then
  echo
  echo "--- 4.2 Campos essenciais (sem expor segredos) ---"
  python3 - "$CONFIG_CANDIDATE" << 'PYEOF' 2>/dev/null
import json, sys
try:
    cfg = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"ERRO ao parsear: {e}")
    sys.exit(1)

def show(k, redact=False):
    v = cfg.get(k, "<ausente>")
    if redact and isinstance(v, str) and len(v) > 8:
        v = v[:4] + "..." + v[-4:]
    if isinstance(v, dict):
        # achatar 1 nível para visualização
        v = {kk: ("***" if "secret" in kk.lower() or "key" in kk.lower() or "token" in kk.lower() or "password" in kk.lower() else vv) for kk, vv in v.items()}
    print(f"  {k:30s}: {v}")

# campos críticos
for k in ["dry_run", "dry_run_wallet", "stake_currency", "stake_amount",
         "max_open_trades", "timeframe", "trading_mode", "margin_mode"]:
    show(k)

# pares
print(f"  pair_whitelist             : {cfg.get('exchange', {}).get('pair_whitelist', '<ausente>')}")

# exchange (sem segredos)
exch = cfg.get("exchange", {})
print(f"  exchange.name              : {exch.get('name', '<ausente>')}")
print(f"  exchange.sandbox           : {exch.get('sandbox', '<ausente>')}")
print(f"  exchange.has key?          : {'sim' if exch.get('key') else 'não'}")
print(f"  exchange.has secret?       : {'sim' if exch.get('secret') else 'não'}")
print(f"  exchange.has password?     : {'sim' if exch.get('password') else 'não'}")

# telegram
tg = cfg.get("telegram", {})
print(f"  telegram.enabled           : {tg.get('enabled', '<ausente>')}")
print(f"  telegram.has token?        : {'sim' if tg.get('token') else 'não'}")
print(f"  telegram.has chat_id?      : {'sim' if tg.get('chat_id') else 'não'}")

# api server / freqUI
api = cfg.get("api_server", {})
print(f"  api_server.enabled         : {api.get('enabled', '<ausente>')}")
print(f"  api_server.listen_ip       : {api.get('listen_ip_address', '<ausente>')}")
print(f"  api_server.listen_port     : {api.get('listen_port', '<ausente>')}")
print(f"  api_server.username        : {api.get('username', '<ausente>')}")

# strategy
print(f"  strategy                   : {cfg.get('strategy', '<ausente>')}")
print(f"  strategy_path              : {cfg.get('strategy_path', '<ausente>')}")

# entry/exit
print(f"  entry_pricing.price_side   : {cfg.get('entry_pricing', {}).get('price_side', '<ausente>')}")
print(f"  exit_pricing.price_side    : {cfg.get('exit_pricing', {}).get('price_side', '<ausente>')}")
PYEOF

  echo
  echo "--- 4.3 Tamanho e timestamp do config ---"
  ls -la "$CONFIG_CANDIDATE"
  echo "  modificado há: $(( ($(date +%s) - $(stat -c %Y "$CONFIG_CANDIDATE")) / 3600 )) horas"
else
  echo "  ⚠️  Nenhum config.json localizado em paths esperados"
fi

# ============================================================================
# 5. ESTRATÉGIA
# ============================================================================
echo
echo "############################################################"
echo "### 5. ESTRATÉGIA"
echo "############################################################"

echo
echo "--- 5.1 Estratégias disponíveis ---"
find ~ -maxdepth 6 -type d -name "strategies" 2>/dev/null \
  -not -path "*/.git/*" -not -path "*/node_modules/*" | while read d; do
  echo "  diretório: $d"
  ls "$d"/*.py 2>/dev/null | head -10
done

echo
echo "--- 5.2 SampleStrategy ou estratégia principal — primeiras 30 linhas ---"
SAMPLE=$(find ~ -maxdepth 6 -type f -name "SampleStrategy.py" 2>/dev/null | head -1)
if [ -n "$SAMPLE" ]; then
  echo "  arquivo: $SAMPLE"
  head -30 "$SAMPLE"
else
  echo "  (SampleStrategy.py não encontrado)"
fi

# ============================================================================
# 6. PIPELINE DE DADOS
# ============================================================================
echo
echo "############################################################"
echo "### 6. PIPELINE DE DADOS"
echo "############################################################"

echo
echo "--- 6.1 Diretório de dados históricos ---"
find ~ -maxdepth 7 -type d -name "data" 2>/dev/null | grep -i user_data | head -5

echo
echo "--- 6.2 Arquivos de candles (.feather/.json) — mais recentes ---"
find ~ -maxdepth 8 -type f \( -name "*.feather" -o -name "*-trades.json*" -o -name "*USDT*.json*" \) 2>/dev/null \
  -not -path "*/.git/*" | head -10 | while read f; do
  echo "  $(stat -c '%y %s %n' "$f" 2>/dev/null | cut -c1-19)... $(basename "$f") ($(du -h "$f" 2>/dev/null | cut -f1))"
done

# ============================================================================
# 7. PERFORMANCE DRY-RUN — SQLite trades
# ============================================================================
echo
echo "############################################################"
echo "### 7. PERFORMANCE DRY-RUN (SQLite)"
echo "############################################################"

DB_CANDIDATE=$(find ~ -maxdepth 6 -type f -name "tradesv3*.sqlite" 2>/dev/null | head -1)
if [ -z "$DB_CANDIDATE" ]; then
  DB_CANDIDATE=$(find ~ -maxdepth 6 -type f -name "tradesv3*.dryrun.sqlite" 2>/dev/null | head -1)
fi
if [ -z "$DB_CANDIDATE" ]; then
  DB_CANDIDATE=$(find ~ -maxdepth 6 -type f -name "*.sqlite" 2>/dev/null | grep -i trade | head -1)
fi

echo
echo "--- 7.1 DB detectado: ${DB_CANDIDATE:-NENHUM} ---"

if [ -n "$DB_CANDIDATE" ] && [ -f "$DB_CANDIDATE" ]; then
  echo
  echo "--- 7.2 Tabelas ---"
  sqlite3 "$DB_CANDIDATE" ".tables" 2>/dev/null

  echo
  echo "--- 7.3 Total de trades ---"
  sqlite3 "$DB_CANDIDATE" "SELECT COUNT(*) AS total_trades FROM trades;" 2>/dev/null

  echo
  echo "--- 7.4 Trades por status (open / closed) ---"
  sqlite3 -header -column "$DB_CANDIDATE" \
    "SELECT is_open, COUNT(*) AS n FROM trades GROUP BY is_open;" 2>/dev/null

  echo
  echo "--- 7.5 Últimos 5 trades ---"
  sqlite3 -header -column "$DB_CANDIDATE" \
    "SELECT id, pair, is_open, open_date, close_date, ROUND(open_rate,2) AS open_rate, ROUND(close_rate,2) AS close_rate, ROUND(close_profit*100,2) AS pct, exit_reason FROM trades ORDER BY id DESC LIMIT 5;" 2>/dev/null

  echo
  echo "--- 7.6 Estatística agregada de fechados ---"
  sqlite3 -header -column "$DB_CANDIDATE" \
    "SELECT COUNT(*) AS n_closed, SUM(CASE WHEN close_profit>0 THEN 1 ELSE 0 END) AS wins, SUM(CASE WHEN close_profit<=0 THEN 1 ELSE 0 END) AS losses, ROUND(AVG(close_profit)*100,2) AS avg_pct, ROUND(SUM(close_profit_abs),4) AS total_abs FROM trades WHERE is_open=0;" 2>/dev/null

  echo
  echo "--- 7.7 Distribuição por exit_reason ---"
  sqlite3 -header -column "$DB_CANDIDATE" \
    "SELECT exit_reason, COUNT(*) AS n, ROUND(AVG(close_profit)*100,2) AS avg_pct FROM trades WHERE is_open=0 GROUP BY exit_reason ORDER BY n DESC;" 2>/dev/null
else
  echo "  ⚠️  Nenhum DB de trades localizado"
fi

# ============================================================================
# 8. CANAIS — Telegram, FreqUI, exchange
# ============================================================================
echo
echo "############################################################"
echo "### 8. CANAIS"
echo "############################################################"

echo
echo "--- 8.1 Portas em escuta (FreqUI / API) ---"
ss -tlnp 2>/dev/null | grep -E ":80[0-9][0-9]|:88[0-9][0-9]" || \
  echo "(sem portas 8000-8099 ou 8800-8899 escutando)"

echo
echo "--- 8.2 Conectividade com OKX (REST público) ---"
curl -s -o /dev/null -w "HTTP %{http_code} — tempo: %{time_total}s\n" \
  --max-time 10 "https://www.okx.com/api/v5/public/time"

echo
echo "--- 8.3 Conectividade com Telegram API ---"
curl -s -o /dev/null -w "HTTP %{http_code} — tempo: %{time_total}s\n" \
  --max-time 10 "https://api.telegram.org"

echo
echo "--- 8.4 Resolução DNS ---"
getent hosts www.okx.com api.telegram.org 2>/dev/null

# ============================================================================
# 9. LOGS — erros e warnings recentes
# ============================================================================
echo
echo "############################################################"
echo "### 9. LOGS (últimas 48h)"
echo "############################################################"

LOG_FILES=$(find ~ -maxdepth 6 -type f -name "*.log" -mtime -2 2>/dev/null \
  -not -path "*/.git/*" -not -path "*/node_modules/*")

if [ -n "$LOG_FILES" ]; then
  echo "$LOG_FILES" | while read logf; do
    echo
    echo "--- 9.x $logf ---"
    echo "  tamanho: $(du -h "$logf" 2>/dev/null | cut -f1) | linhas: $(wc -l < "$logf" 2>/dev/null)"
    echo "  últimas 15 linhas:"
    tail -15 "$logf" 2>/dev/null | sed 's/^/    /'
    echo
    echo "  ERRORS (últimos 5):"
    grep -iE "error|exception|traceback" "$logf" 2>/dev/null | tail -5 | sed 's/^/    /' || echo "    (nenhum)"
    echo
    echo "  WARNINGS (últimos 5):"
    grep -iE "warning|warn" "$logf" 2>/dev/null | tail -5 | sed 's/^/    /' || echo "    (nenhum)"
    echo
    echo "  RECONEXÕES (count nas últimas 24h):"
    grep -ic "reconnect\|disconnect\|connection lost" "$logf" 2>/dev/null
  done
else
  echo "  ⚠️  Nenhum .log modificado nas últimas 48h"
fi

# ============================================================================
# 10. BACKTEST HISTÓRICO
# ============================================================================
echo
echo "############################################################"
echo "### 10. BACKTEST HISTÓRICO"
echo "############################################################"

echo
echo "--- 10.1 Diretório backtest_results ---"
find ~ -maxdepth 6 -type d -name "backtest_results" 2>/dev/null | head -3

echo
echo "--- 10.2 Resultados de backtest (.json/.zip mais recentes) ---"
find ~ -maxdepth 7 -path "*backtest_results*" -type f 2>/dev/null | \
  xargs ls -lt 2>/dev/null | head -10

# ============================================================================
# CONCLUSÃO
# ============================================================================
echo
echo "############################################################"
echo "### FIM DO DIAGNÓSTICO"
echo "############################################################"
echo
echo "Coletado em: $(date -Iseconds)"
echo
echo "Cole o output completo na conversa para análise."

