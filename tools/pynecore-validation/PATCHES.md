# Patches Aplicados ao `.venv-pynetest`

Esses patches foram aplicados **localmente** no venv `~/SMC_Monitor/.venv-pynetest/` durante a investigação PyneCore. **Não fazem parte do repositório do PyneCore upstream nem do nosso codebase.** Vivem dentro do venv.

Se o `.venv-pynetest` for recriado (`rm -rf` + `python3.11 -m venv` + `pip install`), os patches **somem** e devem ser reaplicados.

Esses patches **não devem** ser aplicados em produção sem entendimento profundo do impacto. Eles existem para destravar exploração técnica em terreno controlado.

---

## Patch 1 — `data_converter.py` linha 97 (Bug 2 do `INVESTIGATION_LOG.md`)

### Contexto

`pynecore.core.data_converter.DataConverter.convert_to_ohlcv()` faz `if detected_format not in SupportedFormats:` onde `SupportedFormats` é uma `Enum`. Em Python 3.11.x, `str in EnumType` deixou de funcionar e levanta `TypeError: unsupported operand type(s) for 'in': 'str' and 'EnumType'`.

### Localização do arquivo no venv

```
~/SMC_Monitor/.venv-pynetest/lib/python3.11/site-packages/pynecore/core/data_converter.py
```

Linha 97 (no arquivo upstream original).

### Diff conceitual

```diff
- if detected_format not in SupportedFormats:
+ if detected_format not in [e.value for e in SupportedFormats]:
```

### Como reaplicar

```bash
DC=~/SMC_Monitor/.venv-pynetest/lib/python3.11/site-packages/pynecore/core/data_converter.py

# Backup
cp "$DC" "$DC.bak"

# Aplicar
python3 << 'PYEOF'
import os
path = os.path.expanduser("~/SMC_Monitor/.venv-pynetest/lib/python3.11/site-packages/pynecore/core/data_converter.py")
with open(path) as f:
    src = f.read()

old = "if detected_format not in SupportedFormats:"
new = "if detected_format not in [e.value for e in SupportedFormats]:"

if old in src:
    n = src.count(old)
    src = src.replace(old, new)
    with open(path, 'w') as f:
        f.write(src)
    print(f"Patch aplicado em {n} ocorrência(s).")
else:
    print("Padrão original não encontrado — talvez já patchado, ou versão diferente.")
PYEOF
```

### Como reverter

```bash
cp ~/SMC_Monitor/.venv-pynetest/lib/python3.11/site-packages/pynecore/core/data_converter.py.bak \
   ~/SMC_Monitor/.venv-pynetest/lib/python3.11/site-packages/pynecore/core/data_converter.py
```

### Verificação

Antes do patch:
```python
>>> from pynecore.core.data_converter import DataConverter
>>> DataConverter().convert_to_ohlcv(...)
TypeError: unsupported operand type(s) for 'in': 'str' and 'EnumType'
```

Depois do patch: a chamada prossegue até o próximo bloqueio (que é Bug 3 do `INVESTIGATION_LOG.md`, sem patch trivial).

---

## Patches NÃO aplicados (anotados para referência)

### Bug 2 também aparece em `cli/commands/data.py` linha 355

```
~/SMC_Monitor/.venv-pynetest/lib/python3.11/site-packages/pynecore/cli/commands/data.py
```

Linha 355: `if fmt not in InputFormats:`

Mesma classe de bug, mesma correção. **Não patchado** porque o caminho que estamos investigando é programático (não usa essa CLI).

### Bug 3 — `_old_input_values.clear()` em `core/script.py` linha 260

Patch potencial: comentar a linha. Risco: vazamento de estado entre múltiplos scripts no mesmo processo Python.

**Não aplicado.** A decisão depende da próxima rodada de testes baseada em `pynecore-examples/02-programmatic/` — pode ser que o padrão correto de override não passe por `_programmatic_inputs.update()` e o bug seja irrelevante.

---

## Versão do PyneCore patchada

```
$ pip show pynesys-pynecore
Name: pynesys-pynecore
Version: 6.4.2
Location: /home/ubuntu/SMC_Monitor/.venv-pynetest/lib/python3.11/site-packages
```

Python: `3.11.15`. Sistema: Ubuntu 22.04.5 LTS.
