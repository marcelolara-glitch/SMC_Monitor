# tools/diagnostics

Scripts de coleta de estado operacional para a VM de produção. Read-only
por design — nenhum script aqui altera estado do daemon, do banco ou do
sistema.

## Convenções

- Todo script deve começar com cabeçalho `OBJETIVO / FONTE DE DADOS /
  LIMITAÇÕES CONHECIDAS / NÃO FAZER` (padrão de docstring do projeto)
- Scripts não usam `set -e` — devem coletar tudo mesmo em caso de falha
  parcial, e o operador analisa o output completo
- Output esperado: stdout legível em terminal e capturável via `tee`
  para arquivo
- Nenhum script deve expor segredos (tokens, API keys, senhas) no
  output — redação automática quando o campo for detectado

## Inventário

| Script                    | Propósito                                    |
|---------------------------|----------------------------------------------|
| `diagnose_freqtrade.sh`   | Diagnóstico completo do chassi Freqtrade     |

## Outras pastas em tools/

- `tools/pynecore-validation/` — experimento de validação cruzada do
  LuxAlgo SMC traduzido para Python via PyneCore (lateral ao runtime
  de produção; não interfere)

## Uso típico

```bash
cd ~/SMC_Monitor
git pull origin main
chmod +x tools/diagnostics/diagnose_freqtrade.sh
bash tools/diagnostics/diagnose_freqtrade.sh 2>&1 | tee ~/diag_$(date +%Y%m%d_%H%M%S).out
```
