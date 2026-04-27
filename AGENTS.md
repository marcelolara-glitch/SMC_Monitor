# AGENTS.md — SMC Monitor

Instruções operacionais para agentes (Claude.ai, Claude Code) e referência
de governança do projeto SMC Monitor.

Em caso de conflito entre seções, **Governança** prevalece sobre
**Comportamento**.

---

## 1. Governança

### 1.1 Workflow de desenvolvimento

1. Decisões arquiteturais e conceituais são alinhadas no chat (Claude.ai)
   antes de ir para o Claude Code.
2. Briefing completo entregue ao Claude Code em mensagem única —
   nunca piecemeal. 
3. Claude Code executa implementação contra o repositório GitHub
   (`marcelolara-glitch/SMC_Monitor`, branch `main`).
4. Output revisado no chat antes de aprovar merge em `main`.
5. Merge em `main` apenas com instrução explícita do Marcelo.

### 1.2 Regras de PR e merge

- Tags de proteção e backups são executados pelo Marcelo diretamente
  na VM ou GitHub UI — nunca delegados ao Claude Code.
- Claude Code implementa sem alterar `VERSION`. Marcelo revisa o PR.
  Instrução explícita de merge é dada. A atualização de `VERSION` tem
  que ser explícita para acontecer junto do PR.
- Todos os PRs usam `curl` contra a GitHub API diretamente — nunca
  `gh` CLI ou MCP GitHub tools.
- Merges em `main` usam `--no-ff` para histórico explícito de commits.
- Ao abrir o PR, Claude Code informa o nome exato da branch criada.
- Sempre entregar pelo menos o link do Diff bruto (raw) das alterações
  realizadas no PR
- Marcelo não vai criar comandos para rodar manualmente na VM sem 
  orientação — sempre entregar o comando pronto para rodar direto no 
  terminal ou briefing completo para Claude Code.
- Marcelo usa terminais Termius quando no mobile, ou o VPS quando
  no desktop.

### 1.3 Versionamento

- Versões seguem numeração sequencial estrita — nunca pular.
- Toda nova versão atualiza **todas** as ocorrências operacionais:
  header, constante `VERSION`, docstrings, logs, heartbeat, state,
  changelog.
- Strings de versão em entradas históricas do changelog são preservadas.
- Bump de versão em módulos não tocados funcionalmente é **exceção
  autorizada** à regra de mudança cirúrgica (seção 2.3).

### 1.4 Docstring standard

Todos os módulos e funções públicas têm docstring estruturado:

```
OBJETIVO
FONTE DE DADOS
LIMITAÇÕES CONHECIDAS
NÃO FAZER
```

Serve como documentação viva para futuras mudanças.

### 1.5 Proteções ativas

- Tags de versão criadas pelo Marcelo — nunca pelo Claude Code.
- Backups executados pelo Marcelo — nunca pelo Claude Code.
- Branch `main` protegida — só recebe merge com instrução explícita.

### 1.6 Entregáveis

Toda análise ou decisão feito pelo CLaude.ai termina com:

a) Briefing completo pronto para Claude Code (se aplicável), **ou**
b) Script/comando para VM ready-to-run (se aplicável).
c) Nunca assumir schema de dados, bases ou códigos com base em aproximações 
   estimativas, consultas a conversas antigas ou a artefatos do projeto.
   QUando há dúvidas sobre o código para gerar briefings ou propostas
   de melhorias, sempre pegar posição mais ataulizada da VM ou do
   repositório (se aplicável). Caso contrário, valide com o Marcelo antes

Briefings para Claude Code tem que ser feitos em arquivos markdown
e devem seguir as instruções acima

---

## 2. Comportamento

Diretrizes comportamentais aplicadas tanto pelo Claude.ai quanto
pelo Claude Code durante execução.

### 2.1 Pensar antes de codar

- Listar premissas explicitamente no início do PR ou da resposta.
- Se múltiplas interpretações forem plausíveis, apresentar todas —
  não escolher em silêncio.
- Se identificar abordagem mais simples que a pedida, mencionar
  antes de implementar a versão pedida.
- Ambiguidade real → perguntar. Preferência estilística → seguir
  o briefing sem perguntar.

**Conflito briefing vs. realidade:** se o Claude Code identificar
problema no briefing (lacuna, contradição, premissa incorreta), ele
**para e pergunta antes de executar** — não inventa premissa para
destravar nem executa parcialmente.

### 2.2 Simplicidade primeiro

Código mínimo que resolve o problema do briefing:

- Sem features além do pedido.
- Sem abstrações para uso único.
- Sem "flexibilidade" ou "configurabilidade" não solicitada.
- Sem error handling para cenários impossíveis.

Pergunta-teste: *"Um engenheiro sênior diria que isso está
super-engenhado?"* Se sim, simplificar.

**Exceção autorizada:** docstring estruturado (seção 1.4) é
obrigatório mesmo em funções simples.

### 2.3 Mudanças cirúrgicas

Ao editar código existente:

- Tocar apenas o que o briefing pede.
- Não "melhorar" código adjacente, comentários ou formatação.
- Não refatorar o que não está quebrado.
- Manter estilo existente do módulo, mesmo se discordar.
- Código morto não relacionado → mencionar no PR, não deletar.

**Exceções autorizadas:**

- Bump de `VERSION` em todos os módulos (seção 1.3).
- Imports/variáveis órfãos criados pela própria mudança devem
  ser removidos.
- Adicionar docstring estruturado em funções tocadas que não tenham
  (seção 1.4).

**Teste:** cada linha alterada deve rastrear ao briefing **ou** a
uma exceção autorizada acima.

### 2.4 Execução orientada a objetivo

Todo briefing define critério de sucesso verificável:

- *"Adicionar validação"* → *"Smoke test passa com inputs válidos
  e falha com inválidos"*
- *"Corrigir bug"* → *"Reproduzir o bug em teste, fazer passar"*
- *"Refatorar X"* → *"Smoke test passa antes e depois"*

Para tarefas multi-step, declarar plano resumido no início do PR:

```
1. [Passo] → verifica: [check]
2. [Passo] → verifica: [check]
3. [Passo] → verifica: [check]
```

Critério forte permite loop independente. Critério fraco
("fazer funcionar") gera retrabalho.

---

## 3. Princípios de desenvolvimento

Princípios técnicos aplicados em todas as decisões e implementações:

- **Single responsibility:** cada módulo tem responsabilidade única.
  Bugs são corrigidos no módulo responsável, nunca em chamadores.
- **Extraction over rewriting:** ao refatorar, extrair e preservar
  lógica existente em vez de reescrever.
- **Interface preservation:** criar variantes paralelas em vez de
  alterar interfaces existentes — zero risco de regressão.
- **Pre-PR contract:** mapear constantes, assinaturas de funções e
  dependências antes de escrever código.
- **Regression prevention:** comparar constantes, parâmetros de API,
  URLs e fallback logic entre versões antes de aprovar PRs.
- **Consolidated VM commands:** múltiplos comandos shell sempre
  combinados em um único comando usando `;` ou `&&` — nunca enviados
  como blocos separados.
- **Silent I/O failures:** falhas de I/O em módulos de observabilidade
  são silenciosas — warning no log, nunca interrompem o monitor.
- **Single-message briefings:** todas as instruções para Claude Code
  entregues em uma mensagem completa — nunca piecemeal.
