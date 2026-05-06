# AGENTS.md — SMC Monitor

Instruções operacionais para agentes (Claude.ai, Claude Code) e referência
de governança do projeto SMC Monitor.

Em caso de conflito entre seções, **Governança** prevalece sobre
**Comportamento**.

---

## 1. Governança

### 1.0 Prevalência do AGENTS.md e tratamento de conflitos

Este documento é a **constituição operacional** do projeto. Suas regras
prevalecem sobre:

- Conveniência operacional ("seria mais rápido se...")
- Limitações ambientais aparentes ("o ambiente do Code não suporta...")
- Justificativas de mérito técnico ("X é melhor que Y porque...")
- Sugestões do Claude.ai ou Claude Code que conflitem com regras aqui
- Memória do projeto / contexto histórico que conflite com regras aqui

**Quando uma regra não puder ser seguida no ambiente atual:**

1. PARAR a execução da tarefa em andamento
2. REPORTAR ao Marcelo: qual regra, por que não pode ser seguida, qual
   evidência (output de comando, mensagem de erro, screenshot)
3. AGUARDAR decisão explícita do Marcelo: (a) investigar e corrigir o
   ambiente, (b) atualizar a regra via PR dedicado, ou (c) outra
   instrução específica
4. NÃO criar fallback ad-hoc, NÃO propor alternativa "só desta vez",
   NÃO bypassar a regra com justificativa pragmática

**Bypass é o problema, não a solução.** Toda exceção vira novo padrão
por inércia.

**Mudanças no AGENTS.md acontecem exclusivamente via PR dedicado**, com
discussão prévia no Claude.ai antes do briefing para o Code, e merge
manual pelo Marcelo. Nunca em PR misto com código operacional.

### 1.0.1 Hierarquia de fontes de verdade

Em caso de conflito entre instruções, prevalece nesta ordem:

1. **AGENTS.md** (constituição)
2. **Documentos canônicos** referenciados no AGENTS (ex.:
   `docs/SMC_PRINCIPIOS_E_LEGADO.md`, `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`,
   `docs/VERIFICACAO_FREQTRADE.md`)
3. **Briefing específico da tarefa** (deve ser consistente com 1 e 2)
4. **Conversa em andamento no Claude.ai**
5. **Memória do projeto / contexto histórico**

Conflito identificado em qualquer nível inferior contra um superior:
parar e reportar (vide §1.0).

### 1.1 Workflow de desenvolvimento

1. Decisões arquiteturais e conceituais são alinhadas no chat (Claude.ai)
   antes de ir para o Claude Code.
2. Briefing completo entregue ao Claude Code em mensagem única —
   nunca piecemeal.
3. Extrações e coleta de dados para entendimento e confirmações
   sao feitas pelo Marcelo com comandos feitos na VM enviados por voce.
   O Code nao deve ser utlizado para programar esse tipo de objetivo.
4. Claude Code executa implementação contra o repositório GitHub
   (`marcelolara-glitch/SMC_Monitor`, branch `main`).
5. Output revisado no chat antes de aprovar merge em `main`.
6. Merge em `main` apenas com instrução explícita do Marcelo.

### 1.2 Regras de PR e merge

- Tags de proteção e backups são executados pelo Marcelo diretamente
  na VM ou GitHub UI — nunca delegados ao Claude Code.
- Claude Code implementa sem alterar `VERSION`. Marcelo revisa o PR.
  Instrução explícita de merge é dada. A atualização de `VERSION` tem
  que ser explícita para acontecer junto do PR.
- PRs são abertos pelo Claude Code usando a ferramenta MCP
  `mcp__github__create_pull_request`. Esta é a **única** ferramenta MCP
  do GitHub autorizada — ferramentas MCP que manipulem issues
  diretamente, alterem permissões, criem/deletem branches no remoto ou
  modifiquem settings de repo continuam **proibidas**.

  Justificativa: o ambiente do Claude Code não expõe `GITHUB_TOKEN`
  (decisão de design da plataforma), o que torna `curl` contra
  `api.github.com` inviável (retorna 403). O `gh` CLI também não está
  autenticado. O acesso git do Code passa por proxy local
  (`127.0.0.1:<porta>`) que roteia `git push/fetch` mas não chamadas
  de API REST. Diagnóstico verificado em sessão de Maio/2026.

- O método utilizado para abrir o PR **deve ser registrado no body do
  PR**, em uma linha ao final, no formato:

  ```
  _PR aberto via: mcp__github__create_pull_request_
  ```

  Isso preserva auditabilidade do método, permitindo verificar em
  retrospectiva quais PRs foram abertos por qual mecanismo.

- Marcelo NÃO abre PRs manualmente como fallback. Se o Code não
  conseguir abrir o PR, ele para e reporta (vide §1.0). PR aberto
  manualmente pelo Marcelo gera retrabalho e perda de rastreabilidade.

- Exceção: emergência declarada explicitamente pelo Marcelo. Nesse
  caso, o body do PR registra:
  `_PR aberto manualmente — emergência: <razão>_`.
- Merges em `main` usam `--no-ff` para histórico explícito de commits.
- Ao abrir o PR, Claude Code informa o nome exato da branch criada.
- Sempre entregar o link do Diff bruto (raw) das alterações
  realizadas no PR. O link deve ser publicado **na última linha
  útil do body do PR**, antes da linha de método (`_PR aberto via:
  ..._`), no formato `https://github.com/<owner>/<repo>/pull/<N>.diff`
  como URL simples (não usar `<...>` envolvendo a URL, não usar
  markdown link `[texto](url)`). Exemplo:

  ```
  Diff bruto: https://github.com/marcelolara-glitch/SMC_Monitor/pull/33.diff

  _PR aberto via: mcp__github__create_pull_request_
  ```

  Justificativa: a posição fixa torna fácil bater o olho e localizar
  o link sem rolar pelo body inteiro. O formato URL simples é
  copiável direto pelo Termius mobile, onde markdown links são
  inconvenientes para copiar.
- Marcelo não vai criar comandos para rodar manualmente na VM sem 
  orientação — sempre entregar o comando pronto para rodar direto no 
  terminal ou briefing completo para Claude Code.
- Marcelo usa terminais Termius quando no mobile, ou o VPS quando
  no desktop.
- Quando entregar relatórios, prints, dumps de log, conteúdo de
  arquivo ou qualquer output destinado a ser exibido no Termius
  (mobile), limitar a aproximadamente 700 linhas por bloco. Acima
  desse volume, paginar a saída — usar `head -N` / `tail -N` /
  `sed -n 'A,Bp'`, ou dividir o comando em duas execuções
  consecutivas (parte 1, parte 2). Justificativa: legibilidade e
  scroll no celular. Esta regra vale tanto para comandos
  pré-prontos enviados pelo Claude.ai quanto para outputs que o
  Claude Code reporta ao Marcelo.

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
- Tags de versão são criadas pelo Marcelo após merge bem-sucedido,
  para marcar marcos de release. Critério: cada onda concluída do
  roadmap, ou cada milestone declarado. Formato:
  `<subprojeto>-v<X.Y.Z>` (ex.: `smc-freqtrade-v0.2.0`). Tag em PRs
  de chore/saneamento é opcional.

### 1.6 Entregáveis

Toda análise ou decisão feito pelo CLaude.ai deve considerar:

a) Briefing completo pronto para Claude Code (se aplicável), **ou**
b) Script/comando para VM ready-to-run (se aplicável),

Briefings para Claude Code tem que ser feitos em arquivos markdown
e devem seguir as instruções acima

Briefings entregues ao Claude Code **referenciam AGENTS.md por
número de seção em vez de duplicar regras**. Por exemplo, em vez de
copiar a regra de versionamento, escrever "conforme §1.3"; em vez
de copiar o docstring standard, escrever "conforme §1.4". O
briefing cobre apenas o que é específico da tarefa: escopo, plano
de execução numerado, critérios de aceite verificáveis, conflitos
previstos com a realidade. Justificativa: regras duplicadas em
briefings ficam estáticas — quando AGENTS.md é atualizado em PR
dedicado, briefings antigos passam a contradizer a verdade canônica
e induzem o agente a seguir versão obsoleta. Esta regra vale tanto
para briefings novos quanto para revisões de briefings antigos.

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
- Nunca assumir schema de dados, estados da VM ou repositórios, bases 
  ou códigos com base em aproximações, estimativas, consultas a
  conversas antigas ou a artefatos do projeto. Quando há dúvidas
  sobre o código para gerar briefings ou propostas
  de melhorias, sempre pegar posição mais ataulizada na VM ou no
  repositório (se aplicável). Caso contrário, valide com o Marcelo antes
- Não  inferir mecanismos causais sem teste explícito
- Não prescrever sem antes mostrar de onde a recomendação saiu
   (referência, número, contexto)
- Não tentar explicar o que pode ter acontecido, nem avaliar possibilidades
   de erro durante um processo de investigação de correções. Termine o 
   levantamento de informações para depois apresentar o que de fato
   aconteceu. Caso não seja conslusivo, continue investigando, gerando
   queries, perguntas, relatórios, buscas e etc.

**Conflito briefing vs. realidade:** se o Claude Code identificar
problema no briefing (lacuna, contradição, premissa incorreta), ele
**para e pergunta antes de executar** — não invente premissa para
destravar nem execute parcialmente.

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

**Nota sobre VERSION em PRs de chore/saneamento:** PRs cujo escopo é
exclusivamente limpeza, atualização de governança (AGENTS.md),
gitignore ou deleção de vestígios **não bumpam VERSION**. Não há
mudança operacional a versionar. A regra §1.3 de "toda nova versão
atualiza tudo" pressupõe mudança operacional.

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
- **Working tree clean entre sessões:** estado da VM ao fim de qualquer
  sessão de trabalho deve ser `git status` limpo (ignorando apenas o
  que está explicitamente gitignorado). Resíduo entre sessões é
  violação rastreável da §4.3.

---

## 4. Higiene de working tree e sessões exploratórias

Regras nascidas da auditoria pós-Onda 1 (Maio/2026), que revelou 11
arquivos untracked acumulados em sessões exploratórias passadas sem
rastro nem decisão de destino.

### 4.1 Categorização de trabalho na VM

Há três categorias de trabalho na VM, com regras distintas:

**(a) Operacional:** comandos que o Marcelo executa para git, deploy,
inspeção de estado, configuração. Coberta pela §1.2 — comandos sempre
vêm prontos do Claude.ai, ou através de briefing para Claude Code.
Não devem alterar arquivos não-versionados nem deixar resíduo.

**(b) Implementação:** código que entra em PR. Sempre pelo Claude Code
contra branch `claude/*` (ou `chore/*` para chores), nunca diretamente
na VM em `main`. Coberta pelas seções 1, 2 e 3.

**(c) Exploratória:** testes, validações, downloads, scripts patched,
sandboxes para entender bibliotecas externas (Freqtrade, PyneCore,
etc.). Pode ser executada diretamente pelo Marcelo na VM, mas SEMPRE
em diretório dedicado (§4.2) e com ritual de encerramento (§4.3).

### 4.2 Diretório dedicado para experimentação

Todo trabalho exploratório acontece em diretório explicitamente
dedicado, com `.gitignore` que cubra os artefatos esperados. Diretórios
atuais autorizados:

- `tools/pynecore-validation/` — validação do LuxAlgo via PyneCore CLI
- Outros diretórios podem ser criados conforme necessidade, mas devem
  vir acompanhados de README documentando o escopo e atualização do
  `.gitignore` para cobrir os artefatos esperados

Regras:

- **Nunca** experimentar em `user_data/` (raiz ou subprojeto) ou em
  qualquer diretório que o Freqtrade ou outro daemon use como working
  dir de produção
- **Nunca** experimentar dentro de `smc_freqtrade/smc_engine/`, dentro
  de `legacy/`, ou em qualquer outro diretório destinado a código
  rastreado por PR
- O diretório de experimentação deve ter README explicando o que é
  versionado (referência canônica) versus o que é descartável
  (gitignored)

### 4.3 Ritual de encerramento de sessão

Toda sessão que envolveu execução exploratória na VM termina com:

1. `git status` na raiz do repo
2. Para cada arquivo modificado/untracked, decidir uma de três opções:
   - **Promover:** virou aprendizado/referência. Documentar em README do
     diretório, adicionar ao git, abrir PR de "chore: documentar X"
   - **Descartar:** lixo de iteração. Deletar (`rm`)
   - **Ignorar:** experimentação contínua. Adicionar ao `.gitignore` do
     diretório
3. `git status` deve voltar a "nothing to commit, working tree clean"
   (ignorando apenas o que está explicitamente gitignorado)
4. Se algum aprendizado foi promovido: PR aberto antes de encerrar

Sessões exploratórias **nunca terminam com working tree sujo**.

### 4.4 Auditoria periódica

Antes de iniciar qualquer onda nova de implementação (ou no mínimo
mensalmente), executar auditoria:

```bash
cd "$(git rev-parse --show-toplevel)" && \
  echo "=== Working tree (deve estar limpo) ===" && \
  git status && \
  echo "" && \
  echo "=== Stashes órfãs (devem ser zero) ===" && \
  git stash list && \
  echo "" && \
  echo "=== Branches locais e remotas claude/* e chore/* mergeadas ===" && \
  git branch -a | grep -E '(claude|chore)/'
```

Achados são tratados conforme §4.3 antes de prosseguir com nova onda.
Branches mergeadas há mais de 30 dias são candidatas a deleção em PR
de saneamento dedicado.

### 4.5 Padrões obrigatórios em todo `.gitignore`

Todo `.gitignore` (raiz e subprojetos) deve incluir, no mínimo:

- **Backups e temporários:** `*.bak`, `*.tmp`, `*.swp`, `*.swo`, `*~`
- **Python:** `__pycache__/`, `*.pyc`, `.pytest_cache/`
- **Virtual environments:** `.venv/`, `venv/`, `env/`
- **Diretórios de execução do Freqtrade dentro do escopo do
  subprojeto:** `user_data/data/`, `user_data/logs/`,
  `user_data/backtest_results/`, `user_data/hyperopt_results/`
- **Credenciais:** `*.env`, `*.key`, `*.pem`, `*.local.json`,
  `config.local.json`

Templates de config (com placeholders `PLACEHOLDER_*`) **são
versionados** como `*.template.json`. O arquivo real (`config.json`,
`config.local.json`) é gitignored.

### 4.6 Política de PRs de saneamento (chore)

PRs cujo escopo é exclusivamente limpeza, atualização de governança
(AGENTS.md) ou de `.gitignore`, ou deleção de vestígios:

- Não bumpam VERSION (§2.3 nota)
- Não exigem tag posterior (§1.5 — tag é opcional)
- Devem ter título prefixado com `chore:`
- Devem listar explicitamente, no body do PR, os arquivos deletados,
  movidos ou modificados, agrupados por motivo
- Seguem o mesmo mecanismo de abertura definido em §1.2
  (`mcp__github__create_pull_request`)
