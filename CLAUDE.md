# CLAUDE.md — SMC_Monitor

Regras de projeto que aplicam a TODAS as sessões do Claude Code neste repo.
Carregadas automaticamente pelo harness no início de cada sessão.

## Workflow de PR — sempre

Estas regras complementam (não substituem) `AGENTS.md`. Em caso de
conflito, `AGENTS.md` vence.

### Diff bruto no body do PR (AGENTS.md §117-128)

**Toda vez** que abrir ou atualizar um PR, o body **deve** terminar com
o link do diff bruto na penúltima linha útil e a linha de método na
última, exatamente neste formato:

```
Diff bruto: https://github.com/<owner>/<repo>/pull/<N>.diff

_PR aberto via: <tool>_
```

- URL simples (sem `<...>`, sem markdown link `[texto](url)`).
- `<tool>` = nome da ferramenta usada (ex.: `mcp__github__create_pull_request`,
  `curl`, etc.).
- Se atualizar um PR depois de criá-lo, **reverificar** que o bloco
  ainda está nas duas últimas linhas úteis.

Justificativa (AGENTS.md): posição fixa torna fácil bater o olho e
localizar o link sem rolar pelo body inteiro. Formato URL simples é
copiável direto pelo Termius mobile.

### Branch + nome no chat (AGENTS.md §116)

Ao abrir o PR, sempre informar no chat o **nome exato** da branch
criada e o número do PR.

## Proibição permanente
- NUNCA oferecer monitoramento de PR, inscrição em eventos ou autofix. Adjudicação e emendas ocorrem exclusivamente via chat com o Marcelo/analista.
