# PyneCore + LuxAlgo SMC — Investigation Log

**Período:** 2026-04-26 a 2026-05-02
**Status:** Bloqueado por bugs em PyneCore 6.4.2. Decisão pendente: retomar via exemplos oficiais ou pivotar para Caminho E.
**Versionamento:** Sem bump de VERSION. Material de referência apenas.

---

## Resumo executivo

O projeto SMC Monitor pivotou em 26/04/2026 do daemon próprio v0.1.6 para Freqtrade como chassi de execução. Em paralelo, decidiu-se avaliar PyneCore + PyneComp (PyneSys) como tradução automática Pine→Python do indicador LuxAlgo SMC, reduzindo trabalho de implementação manual.

A investigação confirmou:

1. **PyneComp traduz Pine→Python com sucesso.** O `.py` gerado é estruturalmente válido (16.1 KB, 341 linhas).
2. **PyneCore 6.4.2 tem 3 bugs sérios** que impedem execução programática direta do `.py` traduzido.
3. **Existe documentação programática oficial** (`pynecore.org/docs/programmatic/`) e **repositório oficial de exemplos runnable** (`PyneSys/pynecore-examples`) que cobrem exatamente os casos investigados — **não foram consultados durante a investigação principal.**

A decisão sobre Caminho A (continuar com PyneCore via exemplos oficiais) ou Caminho E (implementação manual sobre `smartmoneyconcepts==0.0.27`) foi adiada para após esse arquivamento documental.

---

## Estado da VM no momento do arquivamento

- **VM:** Oracle Cloud Ubuntu 22.04, IP 167.234.232.143
- **Repo na VM:** `/home/ubuntu/SMC_Monitor/`, branch `main`, HEAD `3fec21a`
- **Daemon Freqtrade:** PID 7440, dry-run com `SampleStrategy`, ativo desde 26/04
- **`.venv-prod` (do daemon legacy v0.1.6):** **NÃO existe.** Foi removido após o pivot — handoff anterior estava desatualizado nesse ponto.
- **`.venv-pynetest`:** Python 3.11.15, `pynesys-pynecore==6.4.2`, `pandas==3.0.2`. **Patchado localmente** (ver `PATCHES.md`).
- **`~/freqtrade/.venv`:** Python 3.11.15, `freqtrade==2026.3`, `ccxt==4.5.50`.
- **`~/.pynetest-throwaway/`:** venv descartável criado durante investigação. Pode ser removido.

### Dados disponíveis

```
/home/ubuntu/SMC_Monitor/user_data/data/okx/futures/BTC_USDT_USDT-{5m,15m,1h}-futures.feather
/home/ubuntu/SMC_Monitor/user_data/data/futures/BTC_USDT_USDT-4h-futures.feather  (180 candles, 30 dias)
```

### Arquivos chave em `tools/pynecore-validation/` (mergeados em PR #26)

- `luxalgo_smc_compute_only.pine` — fonte LuxAlgo SMC v6 otimizado (287 linhas)
- `luxalgo_smc_compute_only.py` — output PyneComp (341 linhas, 16.1 KB)

### Untracked não commitados (estado abandonado da investigação)

- `luxalgo_smc_compute_only.toml` — gerado pelo PyneCore na primeira execução, com `value = "240"` injetado em `fairValueGapsTimeframeInput` durante teste #5
- `test_minimal.py`, `test_minimal_v2.py`, `test_minimal*.toml` — scripts de isolamento usados para reproduzir bugs com superfície mínima
- `workdir/` — estrutura `workdir/scripts/`, `workdir/data/`, `workdir/output/` da CLI `pyne run`

Esses untracked **não foram commitados** intencionalmente, mas servem como evidência prática dos testes. Podem ser limpos ou versionados em PR futuro se houver retomada.

---

## Bugs confirmados em PyneCore 6.4.2

### Bug 1 — `Path.resolve()` no `standalone.py`

**Sintoma:**
```
File "pynecore/standalone.py", line 21
    data_path = Path(data_arg).resolve()
TypeError: Path.resolve() missing 1 required positional argument: 'self'
```

**Reprodução:** Qualquer script PyneCore (`@pyne` + `@script.indicator`) executado via `python script.py data.csv`. Não específico do LuxAlgo — reproduzido com script trivial de 6 linhas (`test_minimal_v2.py`).

**Reprodução programática também falha:** Chamando `pynecore.standalone.run(__file__)` diretamente, mesmo erro. Não é efeito da AST transformation do script de usuário.

**Investigação:** O código de `standalone.py` é trivial e correto. `Path` no namespace do módulo é `pathlib.Path` íntegro (`standalone.Path is pathlib.Path == True`). A causa exata da falha permanece **não diagnosticada** — Python pode estar reportando linha errada por reentrant exception em algum hook.

**Workaround viável:** Bypassar `standalone.run()` e chamar `ScriptRunner` diretamente, replicando a lógica de `standalone.py` linhas 35-91 em código de usuário.

---

### Bug 2 — `EnumType` no `data_converter.py` linha 97 (PATCHADO localmente)

**Sintoma:**
```
File "pynecore/core/data_converter.py", line 97
    if detected_format not in SupportedFormats:
TypeError: unsupported operand type(s) for 'in': 'str' and 'EnumType'
```

**Causa:** Código incompatível com Python 3.11 (mínimo declarado pelo próprio PyneCore). O `in` operator entre `str` e `EnumType` deixou de funcionar em alguma minor do 3.11.

**Patch aplicado:** Substituir `if detected_format not in SupportedFormats:` por `if detected_format not in [e.value for e in SupportedFormats]:` no arquivo local. Detalhes em `PATCHES.md`.

**Mesma classe de bug em outro arquivo:** `pynecore/cli/commands/data.py` linha 355 (`if fmt not in InputFormats:`). Não patchado por enquanto — só a CLI usa, e o caminho programático contorna.

---

### Bug 3 — `_old_input_values.clear()` zera overrides programáticos antes da avaliação dos defaults

**Sintoma:**
- Passar `inputs={"fairValueGapsTimeframeInput": "240"}` ao `ScriptRunner.__init__()` não tem efeito.
- Mesmo resultado ao colocar `value = "240"` no `.toml` ao lado do script.
- Erro final: `ValueError: Invalid timeframe: None` (que vira string `'None'` no parser de TF, falhando em `int(timeframe[:-1])` com `'Non'`).

**Diagnóstico via instrumentação (monkey-patch das dicts globais `_old_input_values` e `_programmatic_inputs`):**

Sequência observada durante `ScriptRunner.__init__`:
1. `_programmatic_inputs.update({'fairValueGapsTimeframeInput': '240'})` — ✓ valor entrou
2. `_old_input_values['fairValueGapsTimeframeInput'] = '240'` (1ª vez, durante `_decorate()`)
3. `_old_input_values['fairValueGapsTimeframeInput__global__'] = '240'`
4. `_old_input_values['fairValueGapsTimeframeInput'] = '240'` (2ª vez — `_decorate()` chamado duas vezes)
5. `_old_input_values['fairValueGapsTimeframeInput__global__'] = '240'`
6. `_programmatic_inputs.clear()` — ✓ esperado
7. **`_old_input_values.clear()` — LIMPA TUDO antes que os inputs sejam avaliados**
8. Estado final do `inputs` (InputData dict registrado pelo decorator): **vazio**

O `_old_input_values.clear()` na linha 260 do `script.py` roda no fim do `decorator(func)` interno do `_decorate()`, mas **antes** de a `main()` ser chamada com os defaults avaliados. Quando `input.timeframe('')` é finalmente avaliado no fluxo do `ScriptRunner`, `_old_input_values` já está vazio e ele retorna `defval` (que é `None` por algum motivo, virando string `'None'` no parser de TF).

**Hipótese:** Bug de arquitetura. A ordem de operações está fundamentalmente errada para uso programático sem TradingView. A natureza "lazy" da avaliação de inputs combinada com o `clear()` prematuro inviabiliza o override pelo caminho que tentamos.

**Workaround possível (não testado):** Comentar a linha 260 do `script.py` (`_old_input_values.clear()`). Risco: vazamento entre múltiplos scripts no mesmo processo (cenário do Freqtrade rodando 24/7).

**Hipótese alternativa (não confirmada):** O caminho correto talvez seja diferente do que foi tentado. **Os exemplos oficiais em `pynecore-examples/02-programmatic/` mostram o padrão canônico de override de inputs e não foram consultados.** É a primeira coisa a verificar antes de tirar conclusão sobre Caminho A.

---

## Bugs colaterais investigados

- **`request.security` exige `security_data={}`** com chaves específicas para cada `(symbol, timeframe)` chamado pelo script. Funcionou após chuteagem das chaves (`"CUSTOM:BTC_4H_30DAYS"`, etc.) — frágil mas viável.
- **CSV → OHLCV via `DataConverter`:** funciona após patch do Bug 2. Gera `.ohlcv` binário + `.toml` com SymInfo.
- **`SymInfo`** carrega corretamente do `.toml` gerado pelo conversor.

---

## Resultados confirmados

| Teste | Resultado |
|---|---|
| `python test_minimal_v2.py btc_4h_30days.csv` (standalone direto) | ❌ Bug 1 |
| Bypass via `ScriptRunner` direto, `test_minimal_v2.py` (sem multi-TF, sem inputs) | ✅ Gera CSV de 14KB com 180 candles + coluna `close_value` |
| Bypass via `ScriptRunner`, `luxalgo_smc_compute_only.py` (com `request.security` mas sem inputs) | ⚠️ Erro de `security_data` faltando |
| Idem + `security_data={}` com chaves variadas | ⚠️ Avança, falha em `Invalid timeframe: None` (Bug 3) |
| Idem + `inputs={"fairValueGapsTimeframeInput": "240"}` programático | ❌ Bug 3 — override zerado antes da avaliação |
| Idem + `value = "240"` no `.toml` ao lado do script | ❌ Bug 3 — mesmo zeramento atinge valores do TOML |

**Conclusão parcial:** O `test_minimal_v2.py` (script PyneCore trivial) roda end-to-end via `ScriptRunner` direto, mas o `luxalgo_smc_compute_only.py` (script real com `request.security` + `input.timeframe`) trava no Bug 3.

---

## O que foi descoberto tarde — exemplos oficiais

**Existe documentação programática oficial completa** que não foi consultada durante a investigação principal. Disponível em:

- **`pynecore.org/docs/programmatic/`** — três seções: ScriptRunner API, Data & SymInfo, Integration Patterns
- **`PyneSys/pynecore-examples`** (CC0-1.0) — 6 exemplos runnable:
  1. `01-standalone/` — Run script on CSV, zero code
  2. `02-programmatic/` — **ScriptRunner API com override de inputs** (exatamente o caso testado)
  3. `03-custom-data/` — OHLCV de qualquer fonte (API, DB, DataFrame)
  4. `04-live-ccxt/` — Live exchange via CCXT
  5. `05-freqtrade-indicators/` — Freqtrade + PyneCore como fonte de indicadores
  6. `06-freqtrade-strategy/` — Freqtrade + sinais de PyneCore como estratégia

Os 6 exemplos foram copiados para `tools/pynecore-validation/pynecore-examples/` neste PR como referência permanente.

**Antes de concluir** que Caminho A é inviável, é necessário verificar o padrão canônico que `02-programmatic/` usa para override de inputs. Pode ser que:

a) O padrão usado nessa investigação esteja incorreto, e o exemplo oficial revele a forma certa.
b) O bug exista, mas haja workaround conhecido nos exemplos.
c) A versão suportada seja diferente de 6.4.2.

---

## Próximos passos pendentes

1. **Ler `pynecore-examples/02-programmatic/`** (código + README) e identificar o padrão correto de `inputs={}`.
2. **Re-testar luxalgo** seguindo exatamente o padrão do exemplo oficial.
3. Se funcionar → Caminho A volta a ser viável; próxima etapa é avaliar `05-freqtrade-indicators/` e `06-freqtrade-strategy/` para integração com Freqtrade.
4. Se não funcionar → confirmar Caminho E (implementação manual usando `smartmoneyconcepts==0.0.27` + diferenciais LuxAlgo).

---

## Lições aprendidas

- **Buscar documentação oficial e exemplos runnable antes de fazer engenharia reversa do código fonte.** Várias horas foram gastas reproduzindo via inspeção AST o que provavelmente está respondido em uma página de docs.
- **PyneCore tem ecossistema mais maduro do que o handoff anterior reconhecia.** Lib `smartmoneyconcepts==0.0.27` foi chamada de "amadora" durante a investigação — incorretamente; foi validada em produção no Passo 8 antigo (abr/2026).
- **O bug `Path.resolve()` do handoff anterior é real** (não falso positivo, como inicialmente concluí ao ver mensagem de uso sem argumentos). A confirmação só veio com argumento real.
- **`request.security` no PyneCore programático é altamente acoplado** ao `security_data={}` com chaves específicas. Multi-TF não é trivial fora da CLI oficial.
