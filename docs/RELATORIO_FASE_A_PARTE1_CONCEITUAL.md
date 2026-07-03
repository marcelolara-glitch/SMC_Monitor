# RELATÓRIO — FASE A / PARTE 1 — Revisão Conceitual do Canônico

> **Escopo:** confronto entre o canônico conceitual do projeto e fontes externas independentes,
> conforme `BRIEFING_FABLE5_FASE_A_DIAGNOSTICO.md §3`. Diagnóstico e proposta — nenhuma
> alteração foi feita em código ou documentos. **A Parte 2 não foi iniciada** (gate §4).
>
> **Estado do repositório lido:** `marcelolara-glitch/SMC_Monitor @ 9129333` (2026-06-08),
> clonado diretamente nesta sessão (o sandbox atual acessa `github.com` — o workaround de
> colagem está obsoleto para este ambiente).
>
> **Data do relatório:** 2026-07-02.
>
> **Status [v2.0]:** proposta P0–P10 **ratificada integralmente** pelo Marcelo em 2026-07-03;
> aplicada ao canônico na revisão v2.0.

---

## 0. Método e disciplina anti-autoengano

1. **Nenhum resultado de backtest foi consultado ou usado como evidência** em qualquer linha
   deste relatório. Nenhuma afirmação abaixo depende de P&L, expectancy, win rate ou retorno.
2. **Fontes lidas verbatim no repositório:** `docs/SMC_PRINCIPIOS_E_LEGADO.md` (523 linhas,
   íntegra), `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` (seções §5, §6-Ondas 4/8/9.5, §7.9, §7.10),
   `docs/CONCEITOS_LUXALGO_HOOKS.md` (íntegra das seções §0, §1, §10–§13),
   `tools/pynecore-validation/luxalgo_smc_compute_only.py` (lido como texto, nunca executado —
   inputs e estrutura de pivots/OB/EQ).
3. **Fontes externas:** corpus ICT via documentação textual (grading em §2), os dois
   repositórios do Anexo A clonados e lidos (`starckyang/smc_quant`,
   `manuelinfosec/profittown-sniper-smc`), e o blog LuxAlgo apenas onde documenta conceitos
   ICT (não como âncora de estratégia própria).
4. **Circularidade evitada:** o documento "Conceito Geral do Projeto" e o
   `VERIFICACAO_FREQTRADE.md` foram lidos apenas para entender intenção; nenhuma proposta se
   ancora neles.
5. **Fontes com promessa de performance** (win rates, metas de lucro) foram usadas
   exclusivamente para extrair *estrutura de regra*, nunca expectativa — e estão sinalizadas.

---

## 1. Sumário executivo — o desconfortável primeiro

**F0 — [Certo] A fonte de verdade é incompleta antes de ser errada.** O
`SMC_PRINCIPIOS_E_LEGADO.md` — o documento que a Fase A trata como pilar — **não contém**
definição de premium/discount, OTE, tempo/killzones, displacement, alvos por liquidez ou
inducement (verificado por busca literal no arquivo inteiro; a única ocorrência de "premium" é
o rótulo de qualidade "Setup A+ (premium)" em §2.3, linha 69). As assinaturas A7 e A10 não têm
especificação conceitual em **nenhum** documento canônico: existem como uma linha de tabela
(`CONCEITOS_LUXALGO_HOOKS.md §13`) e dois hooks (§10.3, §10.6). A spec operativa vive em
`setup_state.py`. Consequência direta: **a Parte 2 não tem coluna "conceito" para confrontar
A7, A10 e os filtros P/D** — auditar fidelidade a um conceito não-escrito é impossível. Isso
confirma a hipótese aberta ("o canônico pode estar errado **ou incompleto**") na segunda
alternativa, que é corrigível.

**F1 — [Provável] O canônico funde duas famílias de setup sem declará-las — e a máquina de
estados só modela uma.** A literatura ICT/SMC contém duas arquiteturas de entrada distintas:
(i) **retest de POI pré-existente** — uma zona HTF (OB/FVG) já formada espera o retorno do
preço (é o que o PRINCIPIOS §2.2/§3.1 modela: zona detectada → ARMED → preço entra → confirma);
(ii) **modelo-2022 / zona-nascente** — o sweep dispara um MSS com deslocamento, e a zona de
entrada **nasce desse impulso** (o FVG/OB criado pelo displacement), não é uma zona antiga. As
fontes descrevem o 2022 model explicitamente como sequência sweep → MSS → retorno ao FVG *do
impulso*. O catálogo mistura as famílias (A1/A2/A5 são retest de POI; A7 e o espírito do §2.1
são zona-nascente) sem etiquetá-las, e a FSM do §3.1 (zona existe primeiro, catalisador
qualifica) descreve só a família (i). Não é um erro — as duas famílias são legítimas — mas a
ausência da distinção no canônico é uma divergência conceitual de primeira ordem contra o
corpus, porque muda **o que** a sequência precisa verificar.

**F2 — [Provável] Tempo é dimensão transversal no corpus ICT; no canônico é propriedade de uma
única assinatura.** No material ICT, killzones/sessões filtram *todos* os modelos (OTE tem
janela recomendada, OB/displacement têm "session timing" como filtro de qualidade, e o
alinhamento com sessões London/NY é descrito como marca registrada do 2022 model). No projeto,
tempo entrou apenas como gate da A7 (HOOKS §10.6 → Wave 9.5d). Caveat honesto e obrigatório:
killzones são calibradas para FX/índices; a transposição a cripto 24/7 é **questão empírica em
aberto** — o próprio §10.6 nota que a atividade institucional em cripto segue ondas
correlacionadas. A proposta correta não é copiar janelas: é elevar tempo a dimensão declarada
do modelo, com decisão explícita de adaptação (e a comunidade diverge sobre isso — mapeado em
§4.5).

**F3 — [Provável] Displacement é critério de validade no corpus; no canônico é hook opcional.**
Fontes convergem: um OB sem deslocamento subsequente "não é pegada institucional", e o MSS que
vale é o que quebra estrutura *com* impulso (idealmente deixando FVG). No projeto, displacement
está registrado como hook reservado (HOOKS §10.5, com fórmula do Pine `ICT Concepts` já
copiada) e **não aparece** no PRINCIPIOS. O terceiro repo do Anexo A exige literalmente
"Impulse from OB caused BOS" como condição dura — ou seja, até a referência de
operacionalização que o próprio canônico cita trata displacement como obrigatório.

**F4 — [Certo] O ancorador do Premium/Discount diverge do ICT.** A portagem deriva P/D dos
*trailing extremes* LuxAlgo (MAPA §6-Onda 4). O ICT ancora P/D e OTE no **dealing range** do
impulso relevante (swing low→high do movimento recente, tipicamente pós-raid), com EQ=50% e
OTE=62–79% (sweet spot 70,5%). São ranges diferentes que produzem zonas diferentes. O
PRINCIPIOS não define P/D em absoluto (F0), então a divergência hoje é entre a implementação e
o corpus, sem árbitro documental.

**F5 — [Certo] A costura OB-primitivo vs OB-estratégico já está registrada no repo — e as
fontes externas confirmam que a definição dogmática é o consenso.** MAPA §7.9 registra: LuxAlgo
= extremo na janela `[pivot_idx, break_idx)`; dogma = última vela oposta antes do break. Todas
as fontes externas consultadas (incluindo o `smc_quant` do Anexo A: "last opposing candle
before a major move") usam a definição dogmática, com validade condicionada a displacement +
estrutura/liquidez tomada. A política §7.9 (fidelidade ao LuxAlgo gratuito para match do
golden) é legítima **para o primitivo de validação**; o problema é que o canônico estratégico
narra OB no sentido ICT enquanto a zona operacional vem do primitivo LuxAlgo, sem ponte
documentada declarando qual assinatura consome qual semântica.

**Resposta curta à pergunta-guia (§3.4):** a posição do canônico — SMC é narrativa sequencial e
MTF é hierarquia, não AND — **está correta e é consensual no corpus** [Certo]. Duas nuances de
primeira ordem: (a) confluência é legítima *dentro* do estágio de zona (OB+FVG+OTE na mesma
região fortalecem o POI — isso não é regressão ao scanner); (b) a hierarquia ICT dá ao HTF duas
funções, **direção E alvo** ("draw on liquidity") — o canônico usa o 4H só como gate
direcional. Detalhe completo em §5.

---

## 2. Grading de fontes

O corpus primário do ICT (Michael J. Huddleston) é audiovisual (mentorias no YouTube). Nenhuma
âncora textual usada aqui é primária no sentido estrito; a classificação abaixo declara a
distância. Onde a afirmação depende só de fontes T2/T3 convergentes, o item recebe [Provável],
nunca [Certo].

| Grau | Definição | Fontes usadas |
|---|---|---|
| **T1 — quase-primária** | Documentação dedicada a transcrever/organizar o material ICT, sem promessa de performance no trecho usado | `innercircletrader.net` (tutoriais 2022 model, OTE, fib, OB, breaker), `ictflow.com` |
| **T2 — secundária técnica** | Guias metodológicos com regras explícitas e método declarado | `backtrex.com` (MSS), `fxnx.com`, `fxopen.com`, `tradingfinder.com`/TFlab, `grandalgo.com`, `fluxcharts.com`, `tradingstrategyguides.com`, `strike.money`, `ebc.com` |
| **T3 — comentário/blog de vendor** | Documenta conceitos ICT mas vende produto adjacente | `luxalgo.com/blog` (usado só para conceitos ICT; **não** como âncora de estratégia — evita circularidade com a referência de primitivos), `thesimpleict.com`, `phidiaspropfirm.com` |
| **Implementação de terceiros** | Operacionalização, não autoridade conceitual | `starckyang/smc_quant`, `manuelinfosec/profittown-sniper-smc` (Anexo A) |

**Nota de integridade sobre o Anexo A do canônico:** o README do `profittown-sniper-smc`
promete "$1k → $3k per day" — exatamente o perfil de fonte que o briefing §3.2 manda
desconfiar. Foi mantido **apenas** como amostra de estrutura de regra (e é útil nisso: exige
sweep, fib 61,8–78,6% e impulso causal como condições duras). Recomendo rebaixá-lo no Anexo A
de "referência conceitual" para "amostra de operacionalização, expectativas não-confiáveis".

**Discrepância factual entre fontes (registrada):** os horários das janelas Silver Bullet
divergem entre T2s — a maioria (GrandAlgo, FXOpen, TFlab, innercircletrader.net) dá 3–4 AM /
10–11 AM / 2–3 PM **ET**; a EBC dá janelas em GMT que não batem com a conversão das demais.
Adoto como consensual o conjunto ET majoritário (que coincide com HOOKS §10.6). Fica o
registro de que até T2s erram fatos simples — mais um motivo para o grading.

---

## 3. Tabela de divergências — PRIMITIVOS (divergências objetivas)

| # | Conceito | (a) O que o canônico afirma | (b) O que as fontes externas afirmam | (c) Divergência |
|---|---|---|---|---|
| P-1 | **Swing / pivot** | Pivot por janela fixa: `swingsLengthInput=50` (swing) e `internalOrderBlocksSizeInput=5` (internal) — Pine ref. linhas 84–85; duas camadas internal/swing; camada IT registrada como hook reservado (HOOKS §10.4) | ICT usa fractal de 3 velas e hierarquia ST/IT/LT; o swing relevante para OTE/dealing range é o do **impulso recente**, não um pivot de lookback longo (innercircletrader.net/fibonacci; ictflow) | **Objetiva, já parcialmente registrada** (§10.4). Consequência nova: o swing-50 do LuxAlgo e o swing-de-impulso do ICT selecionam ranges diferentes → contamina P-7 e A10 |
| P-2 | **BOS/CHoCH — confirmação** | Body break, fechamento de vela, não wick (Conceito Geral; LuxAlgo `orderBlockMitigationInput`/estrutura por close) | Consensual: break válido usa a vela **confirmada** (`close[1]`), corpo, anti-repaint (backtrex) | **Sem divergência.** Alinhado |
| P-3 | **MSS/CHoCH — validade** | CHoCH estrutural puro; CHoCH+ exige HL/LH prévio (HOOKS §1: "regra estrutural pura — não envolve deslocamento") | O MSS que vale no corpus é o quebrado **com displacement**, idealmente deixando FVG (backtrex: o impulso que valida o MSS quase sempre cria imbalance; fxnx; thesimpleict) | **Objetiva.** Displacement é validade no corpus; no canônico é hook §10.5. Ver F3 e Proposta P2 |
| P-4 | **Order Block — origem** | LuxAlgo: vela de extremo (`parsed_low`/`parsed_high`) na janela `[pivot_idx, break_idx)` (MAPA §7.9, div. dogmática #1) | Consenso ICT/SMC: **última vela oposta antes do deslocamento**, válida só com displacement + estrutura/liquidez tomada + alinhamento HTF (innercircletrader.net/OB; strike.money; trinitytrading; tradingstrategyguides; `smc_quant` README) | **Objetiva, já registrada no MAPA §7.9.** Externo confirma que a definição dogmática é o consenso. A política de fidelidade-ao-LuxAlgo vale para o primitivo de match; falta a ponte estratégica (Proposta P3) |
| P-5 | **FVG** | 3 velas; mediana 50%; mitigação com semântica documentada (Onda 7; divergência intencional #1 do MAPA §7.10); IFVG segue PAC (HOOKS §4) | Consensual: imbalance de 3 velas; 50% (consequent encroachment) como nível operacional; entrada frequentemente no FVG **criado pelo displacement** (grandalgo usa midpoint; backtrex) | **Sem divergência no primitivo.** Nuance estratégica: no 2022 model importa *qual* FVG (o do impulso) — pertence a E-1/E-6, não ao primitivo |
| P-6 | **Liquidez (pools)** | EQH/EQL por threshold ATR (Pine linhas 89–90; Wave 8.1) — únicos pools modelados | Corpus inclui também PDH/PDL, highs/lows de sessão, old highs/lows semanais, trendline liquidity como pools varríveis (backtrex; TFlab 2022; innercircletrader.net/SB Q&A) | **Objetiva de escopo:** pools do canônico ⊂ pools ICT. Não é erro; é subconjunto não-declarado (Proposta P9) |
| P-7 | **Premium/Discount — ancorador** | Derivado de `trailing.top`/`trailing.bottom` (MAPA §6-Onda 4, absorvido em `trailing.py`); PRINCIPIOS não define P/D (F0) | ICT: dealing range = swing do impulso relevante; EQ=50%; comprar em discount, vender em premium; OTE=62–79% com 70,5% central; retração deve cruzar o EQ para o setup valer (innercircletrader.net/fib; ictflow; tradingstrategyguides) | **Objetiva.** Ranges de referência diferentes → zonas P/D diferentes. Ver F4 e Proposta P4 |
| P-8 | **Sweep — mecânica** | Ultrapassa o nível e fecha de volta; módulo novo fora do LuxAlgo (MAPA Conflito C, §6-Onda 8); parametrização X%·ATR pendente/calibrável | Consensual no núcleo: raid que toma stops e **rejeita** ("a amplitude importa menos que a reação" — backtrex); wick-beyond-close-back é a forma padrão | **Sem divergência no núcleo.** X%·ATR e janela são engenharia idiossincrática legítima — declarar como tal (entra em §7, não na proposta) |

---

## 4. Tabela de divergências — ESTRATÉGIA (interpretativas, com grau de consenso)

Legenda de consenso: **C** = consensual no corpus; **AL** = alternativa legítima (espaço com
mais de uma leitura defensável); **I** = idiossincrático do nosso canônico (escolha de
engenharia sem âncora externa — não é erro, mas deve ser declarada como escolha).

| # | Tema | (a) Canônico | (b) Fontes externas | (c) Classificação |
|---|---|---|---|---|
| E-1 | **Sequência vs confluência** | SMC é narrativa sequencial; co-presença sem ordem é ruído (PRINCIPIOS §2.1) | 2022 model é definido como sequência específica: sweep → MSS → retorno ao FVG (DivergentTrades; TradingFinder; fxnx). Repos do Anexo A operam em sequência (detect → zona → retração → entrada) | **C — canônico ratificado.** Nuance: confluência *intra-estágio* é consensual e legítima (OTE só vale com OB/FVG na zona — "o nível sozinho não é o trade", innercircletrader.net/fib) |
| E-2 | **MTF como hierarquia** | 4H direção, 1H zona, 15m gatilho; não vota em score (PRINCIPIOS §2.4) | Top-down consensual: HTF bias → LTF entrada alinhada (backtrex; TFlab; fxnx; tradingstrategyguides) | **C — ratificado.** Lacuna: no corpus o HTF também define o **alvo** (draw on liquidity — pools HTF não-mitigados como destino). O canônico usa HTF só como gate direcional → **AL ausente** (Proposta P5) |
| E-3 | **Papel do sweep** | Gate com qualidade A+/B: A+ exige sweep; B aceita ausência com confirmação extra (PRINCIPIOS §2.3) | No 2022/Silver Bullet o sweep é **estágio obrigatório** da sequência (grandalgo: setups de maior probabilidade começam com sweep; DivergentTrades). Mas o corpus também contém modelos de retest de POI HTF sem sweep explícito, condicionados a bias (innercircletrader.net/OB checklist) | **AL.** O desenho A+/B é uma síntese defensável das duas famílias (F1); não é consenso nem heresia. Deve ser declarado como escolha, com as famílias etiquetadas (Proposta P6) |
| E-4 | **Confirmação no TF menor** | ChoCH 15m **+** vela de rejeição (PRINCIPIOS §2.2, §3.2) | Consensual: MSS/CISD no LTF como gatilho de confirmação (fxnx; innercircletrader.net/OTE: "MSS ou CISD como trigger"); confirmação candlestick (engolfo/rejeição) aparece como **alternativa**, não como conjunção obrigatória (fxnx/fib) | **AL→I na conjunção.** Exigir os dois simultaneamente é composição idiossincrática — precedente interno da A3 sufocada aponta o risco. Reclassificar como escolha (Proposta P8) |
| E-5 | **Tempo / killzones** | Ausente do PRINCIPIOS; hook §10.6 aplicado só à A7 | Tempo é filtro transversal: alinhamento com sessões é marca do 2022 model (tradingfinder); OTE tem janela recomendada 8:30–11 NY (TFlab/tradingfinder); "session timing = quality filter" para displacement (thesimpleict); "trade exclusivamente na kill zone" (TFlab/OTE). **Contraponto mapeado:** parte da comunidade insiste que OTE é retração pura, não time-based (discussão em innercircletrader.net/OTE) | **AL de primeira ordem.** Consenso majoritário: tempo importa transversalmente. Divergência real na comunidade sobre obrigatoriedade. Cripto 24/7 exige decisão de adaptação explícita (Proposta P1) |
| E-6 | **A7 Silver Bullet — definição** | Catálogo: "Sweep+FVG window", tipo Continuação (HOOKS §13); janelas do §10.6; sem spec conceitual em doc | Maioria: sweep → **MSS/displacement** → primeiro FVG do impulso, dentro da janela, alinhado ao bias; deslocamento fora da janela não é SB (grandalgo — "não-negociável"; fxnx; tradingfinder). Minoria: sweep → FVG direto, sem MSS explícito (fluxcharts) | **AL com maioria clara.** A formulação do catálogo corresponde à variante minoritária. Direção: reversão-do-sweep alinhada ao bias diário — o rótulo "Continuação" só é verdadeiro em relação ao bias, não ao sweep. Explicitar (Proposta P7) |
| E-7 | **A10 OTE — definição** | Catálogo: "Fib 62–79%", Continuação, via hook DTFX (fib sobre MSS, §10.3); sem spec conceitual em doc | Consensual: 62–79% (70,5% central) sobre o swing do **impulso** que quebrou estrutura com deslocamento genuíno; setup só vale se a retração cruzar o EQ (50%); exige confluência (OB/FVG na zona) + confirmação; SL além do 100%; alvos nas extensões −0.27/−0.62 ou liquidez (innercircletrader.net/fib e /OTE; ictflow; tradingstrategyguides; fxnx) | **C no desenho** — e o hook DTFX (fib sobre MSS) é coerente com "swing do impulso". Divergência é a **lacuna** (F0): nada disso está escrito em canônico. Requisitos de EQ-cross e confluência precisam constar (Proposta P4/P0) |
| E-8 | **Alvos e gestão** | TP1 FVG/liquidez, TP2 Fibonacci 0.618, TP3 swing; R:R≥1:2; BE após TP1 (Conceito Geral — interno; PRINCIPIOS não define alvos) | Alvo primário consensual = **liquidez oposta / draw** (tradezella; fxopen; tradingfinder; innercircletrader.net/breaker); extensões −0.27/−0.62/−1 como framework de TP (innercircletrader.net/fib); R:R mínimo 1:2–1:3 consensual | **AL/I.** Fib **retracement** 0.618 como TP não tem âncora no corpus (ICT usa extensões negativas e pools); "draw on liquidity" está ausente do canônico. BE-após-TP1 é gestão idiossincrática legítima (declarar) |
| E-9 | **Invalidação** | Critérios explícitos por estado: mitigação, escape >2%, timeout 6h/N candles, mudança 4H (PRINCIPIOS §2.5, §3.2) | Princípio consensual (setups morrem; invalidação estrutural = close além do extremo/100% — fxnx/fib; tradingstrategyguides); **nenhuma fonte fixa 2%/6h/N** | **C no princípio; I nos parâmetros.** Manter, declarando 2%/6h/N como engenharia calibrável sem âncora (entra em §7) |
| E-10 | **Risk vs Confirmation entry** | Dois modos legítimos; começar por Confirmation (PRINCIPIOS §3.4) | Consensual: entrada agressiva/limit na zona vs conservadora pós-confirmação, ambas documentadas (luxalgo/blog OB: aggressive vs conservative; fxopen: limit na borda do FVG; `sniper`: limit no OB) | **C — ratificado.** Sem mudança |
| E-11 | **Inducement / IDM** | Ausente do PRINCIPIOS; presente só no doc interno "Conceito Geral" (Padrão de Indução) | Existe no corpus como refinamento (ICT Model 4 usa IDM entre POI e entrada — tradezella); terminologia mais forte na escola SMC-comunidade que no ICT original | **AL — lacuna mapeada.** Não proponho implementação; proponho apenas registro documental do conceito no espaço (evita redescoberta futura) |

---

## 5. Resposta à pergunta-guia (§3.4 do briefing)

**O canônico está certo: SMC no corpus ICT é sequência, e MTF é hierarquia decisória.**
[Certo, dentro do grading T1/T2] O 2022 model é definido pelas fontes como uma sequência
nomeada de eventos em ordem (sweep → MSS → retorno ao imbalance), não como interseção de
condições; o fluxo top-down (bias HTF → gatilho LTF alinhado) é unânime nas fontes
consultadas; e os dois repositórios do Anexo A operacionalizam sequências, não scores.
**Portanto: o que precisa ser testado é a sequência completa da máquina de estados — a posição
do §2.1/§2.4 sobrevive ao confronto.**

Três qualificações, em ordem de importância:

1. **A sequência do corpus não é exatamente a sequência da FSM atual.** A FSM §3.1 modela
   "zona pré-existente → preço retorna → confirma" (família retest-de-POI). O 2022 model
   modela "sweep → impulso cria a zona → preço retorna à zona recém-nascida" (família
   zona-nascente). São **duas sequências diferentes** com estados diferentes: na segunda, o
   ARMED não pode existir antes do sweep, porque a zona ainda não existe. Testar "a sequência"
   exige antes declarar **qual** sequência cada assinatura implementa (F1, Proposta P6).
2. **Confluência intra-estágio não é regressão ao scanner.** OB+FVG+OTE sobrepostos na mesma
   zona é qualificador de POI consensual. O dogma §8.1-1 ("não proponha score de confluência")
   continua válido para o *disparo*; não deve ser lido como proibição de qualificar a *zona*.
3. **Hierarquia tem duas saídas no corpus, não uma.** O HTF entrega direção **e** alvo (draw
   on liquidity). A FSM consome só a direção. A ausência do alvo-HTF não invalida a
   hierarquia; é uma função da hierarquia ainda não modelada.

---

## 6. Proposta de canônico revisado

Cada item cita a fonte que o motiva. Itens sem âncora externa **não** entram (ver §7).
Natureza: **[LACUNA]** = conceito ausente do canônico; **[DIVERGÊNCIA]** = conceito presente
mas em desacordo com o corpus; **[RECLASSIFICAÇÃO]** = manter conteúdo, mudar o status
epistêmico (de "regra SMC" para "escolha de engenharia declarada").

| ID | Proposta | Natureza | Fonte motivadora |
|---|---|---|---|
| **P0** | Completar o PRINCIPIOS com as definições ausentes: premium/discount + dealing range, OTE, displacement, tempo/killzones, alvos (draw on liquidity), e uma spec conceitual de 1 parágrafo por assinatura do catálogo (hoje só existe a tabela de 1 linha em HOOKS §13). Adicionar âncora bibliográfica por seção — hoje o Anexo A é bibliografia geral e nenhuma afirmação do §2.x cita fonte item-a-item. **Sem P0, a Parte 2 não tem coluna "conceito" para A7/A10/P-D** | [LACUNA] | F0 (verificação literal no repo) + todas as fontes de §3/§4 |
| **P1** | Elevar tempo a dimensão transversal declarada do modelo: cada assinatura ganha o campo "sensibilidade a tempo: obrigatória / qualificadora / nenhuma", com decisão explícita de adaptação a cripto 24/7 (janelas ET herdadas como hipótese, não como fato; A7 mantém as janelas como obrigatórias por definição) | [LACUNA] | tradingfinder (sessões como marca do 2022); TFlab/OTE ("exclusivamente na kill zone"); grandalgo (janela não-negociável na SB); thesimpleict (session timing como filtro); contraponto mapeado em E-5 |
| **P2** | Definir displacement formalmente no canônico (corpo > média de N e/ou FVG deixado — a fórmula do Pine `ICT Concepts` já está copiada em HOOKS §10.5) e promovê-lo de hook a **critério de validade** do MSS de confirmação e do OB estratégico de entrada | [DIVERGÊNCIA] | backtrex (impulso valida o MSS); thesimpleict (OB sem displacement não é pegada institucional); strike.money; tradingstrategyguides; `sniper` ("Impulse from OB caused BOS") |
| **P3** | Documentar a ponte OB-primitivo vs OB-estratégico: o primitivo LuxAlgo permanece a referência de match do golden (política §7.9 preservada); o canônico declara qual semântica cada assinatura consome e define o OB-estratégico ICT (última vela oposta + displacement + liquidez/estrutura tomada) como camada conceitual distinta | [DIVERGÊNCIA já registrada em MAPA §7.9; falta a ponte] | innercircletrader.net/OB; strike.money; trinitytrading; `smc_quant` README; MAPA §7.9 |
| **P4** | Ancorar P/D e OTE no **dealing range** ICT (swing do impulso relevante), documentando a diferença para o P/D-trailing LuxAlgo e declarando qual filtro/assinatura usa qual range. Incluir os requisitos consensuais do OTE: retração deve cruzar o EQ; zona só vale com confluência (OB/FVG) e confirmação; SL além do 100% | [DIVERGÊNCIA + LACUNA] | innercircletrader.net/fib e /OTE; ictflow; tradingstrategyguides; fxnx |
| **P5** | Introduzir "draw on liquidity" no canônico: o HTF define direção **e** alvo (pool oposto não-mitigado); alvos passam a citar liquidez oposta como primário; Fibonacci **retracement** 0.618 como TP2 sai ou é reclassificado (o framework ICT de alvos usa extensões −0.27/−0.62 e pools) | [LACUNA + RECLASSIFICAÇÃO] | tradezella (targets = liquidez externa); fxopen; tradingfinder; innercircletrader.net/fib (extensões) |
| **P6** | Declarar as duas famílias de setup no PRINCIPIOS (retest-de-POI vs zona-nascente/2022) e etiquetar cada assinatura do catálogo com a família; registrar que a FSM atual modela a família (i) e que a família (ii) implica ARMED só-pós-sweep | [DIVERGÊNCIA de primeira ordem — F1] | DivergentTrades; TradingFinder/2022; fxnx vs innercircletrader.net/OB; repos Anexo A |
| **P7** | A7: registrar o espaço de interpretações (com-MSS majoritária vs sweep+FVG minoritária) e a decisão adotada; explicitar a semântica de direção (reversão-do-sweep alinhada ao bias — "Continuação" só vale relativo ao bias) | [LACUNA + AL mapeada] | grandalgo; fxnx; tradingfinder (maioria) vs fluxcharts (minoria) |
| **P8** | Reclassificar "ChoCH 15m + vela de rejeição" de regra-SMC para escolha declarada: o consensual é MSS/CISD como gatilho; rejeição candlestick é alternativa, não conjunção obrigatória. (Sem propor mudança de código — Parte 2/Briefing 2 decidem) | [RECLASSIFICAÇÃO] | fxnx; innercircletrader.net/OTE (MSS/CISD); fxnx/fib (rejeição como alternativa) |
| **P9** | Documentar o escopo de liquidez: EQH/EQL implementado como subconjunto; pools ICT adicionais (PDH/PDL, session/old H-L) registrados como espaço não-coberto | [LACUNA de escopo] | backtrex; TFlab/2022; innercircletrader.net/SB |
| **P10** | Anexo A: rebaixar `profittown-sniper-smc` para "amostra de operacionalização; expectativas não-confiáveis" (viola o critério de confiabilidade do próprio briefing §3.2) e registrar o grading de fontes deste relatório como padrão | [RECLASSIFICAÇÃO] | README do próprio repo; briefing §3.2 |

**O que deliberadamente NÃO proponho:** nenhuma mudança motivada por "faria o sistema
funcionar"; nenhuma implementação de IDM/inducement, camada IT, pools adicionais ou macros de
tempo (apenas registro documental); nenhuma alteração da política §7.9 de fidelidade do
primitivo ao LuxAlgo gratuito — ela serve ao golden e deve ser preservada.

---

## 7. Itens sem âncora externa suficiente (honestidade — não entram na proposta)

- Escape >2%, timeout 6h (ARMED), N candles 15m (PENDING) — engenharia calibrável; nenhuma
  fonte fixa esses números.
- X%·ATR e janela temporal do sweep — idem (o núcleo wick-beyond-close-back tem âncora; os
  parâmetros não).
- BE após TP1 e a escada de parciais 20-30/40-50/20-30 — gestão idiossincrática legítima.
- R:R mínimo 1:2 — o corpus oscila entre 1:2 e 1:3; manter 1:2 é defensável, sem âncora única.
- A conjunção exata de gates por assinatura (quais filtros cada A# liga) — decisão de design;
  o que a Parte 2 confrontará é se os gates **declarados** estão implementados, não se são os
  "certos".

Esses itens devem constar do canônico revisado **rotulados como escolhas de engenharia**, para
que a Parte 2 não os trate como dogma nem os audite contra fonte inexistente.

---

## 8. Fontes externas consultadas (para o registro)

**Quase-primárias / documentação ICT:** innercircletrader.net (2022 strategy; silver bullet;
optimal-trade-entry; fibonacci-levels; order-block; breaker-block); ictflow.com/blog (OTE).
**Secundárias técnicas:** backtrex.com (MSS guide); fxnx.com (silver bullet 10-11; fib/OTE);
fxopen.com (silver bullet); tradingfinder.com + forexfactory/TFlab (2022 mentorship; OTE;
silver bullet); grandalgo.com (silver bullet); fluxcharts.com (silver bullet);
tradingstrategyguides.com (OTE; order blocks); strike.money (order block); ebc.com (silver
bullet — com discrepância de horários registrada em §2); tradezella.com (ICT Model 4).
**Vendor/blog:** luxalgo.com/blog (order blocks ICT; silver bullet — só conceitos);
thesimpleict.com (displacement); trinitytrading.io (order blocks); phidiaspropfirm.com (OB).
**Implementações:** github.com/starckyang/smc_quant; github.com/manuelinfosec/profittown-sniper-smc.

**Limitações declaradas:** (i) o material primário ICT é audiovisual e não foi transcrito
nesta sessão — todas as âncoras são T1–T3 e o grading limita a confiança a [Provável] onde só
há convergência secundária; (ii) a aplicabilidade de killzones a cripto 24/7 é questão
empírica **não resolvida** por este relatório — a proposta P1 pede a decisão, não a assume;
(iii) este relatório não olhou o comportamento do código (Parte 2) nem qualquer métrica de
P&L.

---

## 9. Próximo passo (gate §4 do briefing)

Este relatório é uma **proposta**. O Marcelo decide item a item (P0–P10: aceitar / rejeitar /
modificar). Após a decisão, o canônico revisado é salvo no repositório como nova referência, e
só então a Parte 2 começa — lendo o canônico ratificado **do repo**, não desta conversa.

**Fim do relatório. Parte 2 não iniciada, conforme §3.5.**
