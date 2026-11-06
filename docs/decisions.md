# Decisões de projeto

Registro das decisões tomadas durante a implementação, com o raciocínio e o
custo estimado de cada uma estar errada. O histórico de commits mostra **o que**
mudou; este arquivo guarda **por que**.

Várias destas decisões corrigem erros do próprio plano de implementação: a
regra de concentração de mono, a seleção do quadro do minuto 14, o laço infinito
de rebusca de timeline e a derivação da lista de botas foram todas especificadas
de forma errada e corrigidas durante a execução. Elas estão aqui porque a
próxima pessoa a mexer nisto precisa saber que aquele caminho já foi tentado.

Decisões marcadas como "custo se errado" dizem o que se perde caso a escolha se
mostre equivocada — a maioria é barata de reverter; as que não são estão
sinalizadas.

- Task 3: Ruling: os tiers de apice (CHALLENGER, GRANDMASTER, MASTER) usam os endpoints dedicados `/lol/league/v4/{challenger|grandmaster|master}leagues/ by-queue/RANKED_SOLO_5x5`, que devolvem um LeagueListDTO unico com `entries` e NAO sao paginados. O endpoint paginado `/entries/{queue}/{tier}/{division}` nao atende tiers de apice — a issue 145 do repositorio developer-relations da Riot registra exatamente isso e segue aberta como pedido de recurso ha ~7 anos, logo nunca foi implementado. O plano estava errado ao mandar paginar o Mestre; o erro e meu, nao do implementador. A spec, que diz "poucas requisicoes" no estagio 1, concorda com os endpoints dedicados. Custo se errado: nenhum — os endpoints dedicados funcionam para tiers de apice em qualquer dos dois cenarios, enquanto o paginado pode nao funcionar.

- Task 3: Ruling: DIAMOND, que a configuracao permite como `min_tier` no caminho de recalibragem da Task 9, usa o endpoint paginado com as quatro divisoes I..IV. Deixar DIAMOND sem implementacao seria uma armadilha: a recalibragem e justamente o plano B se a Task 9 nao achar mono suficiente. Custo se errado: codigo de paginacao exercitado so quando baixarmos o elo.

- Task 3: Ruling: `puuid` e lido da entrada da escada. Se o campo faltar, levantar RiotError nomeando-o, em vez de devolver escada vazia. E uma escada vazia nunca pode ser silenciosa: um tier que devolva zero entradas no total e erro (uma pagina vazia, no caminho paginado, apenas encerra a paginacao). A Riot migrou de summonerId para puuid e removeu os endpoints por summonerId, mas eu nao tenho chave para confirmar o schema; falhar alto e a protecao. Custo se errado: uma excecao clara na primeira execucao real, em vez de uma coleta que termina com zero candidatos sem explicacao.

- Task 3: Ruling: `api_key` sai do construtor do RiotClient. Aceitar um parametro e nao usa-lo e pior que nao aceitar: sugere que o cliente guarda a chave quando so o transporte guarda. Custo se errado: nenhum.

- Task 4: Ruling: os dois Important entram em correcao. (1) `confirmed_player_count` conta confirmados sem partidas gravadas e alimenta tamanho de amostra na tela — superestimar amostra e exatamente a desonestidade que a spec proibe, entao passa a contar jogadores com ao menos uma partida. (2) a tabela `discard` nao tem chave e um INSERT simples dobra a contagem numa retomada; a taxa de descarte e a instrumentacao que a spec nomeia como sinal mais importante, e inflar silenciosamente a inutiliza. Vira (match_id, reason) unico com INSERT OR IGNORE. Custo se errado: baixo, sao mudancas de SQL.

- Task 4: Ruling: incluo neste round dois minors que normalmente ficariam de fora — os testes de reconfirmacao em outro par e de reject-depois-confirm — porque o round ja esta aberto, sao assercoes e nao redesenho, e fixam justamente o comportamento de retomada que eu levantei como risco. Custo se errado: dois testes a mais.

- Task 4: Ruling: adoto tambem o context manager `with db.batch():` (classificado Minor) em vez de deixar `commit()` solto. As Tasks 8, 9 e 10 sao os tres proximos consumidores e uma interface que perde dados quando o chamador esquece e uma armadilha mais barata de fechar agora que depois de tres chamadores escritos. Custo se errado: uma abstracao pequena a mais.

- Task 4: Ruling: o proprio implementador apontou que `batch()` nao faz rollback na excecao e que `close()` confirma o pendente — ou seja, um lote abortado pode ser gravado depois, que e o oposto da garantia pela qual eu pedi o bloco. Vira correcao: na excecao, rollback e re-raise; `close()` nao confirma nada. Isso e breakage introduzido pela propria correcao, entao entra como achado novo do round, nao como minor diferido. Custo se errado: `close()` passa a exigir commit explicito, e os testes que dependiam do commit implicito do fixture precisam ajuste — e e justamente esse commit implicito que escondia o problema.

- Task 5: Ruling: o trailer Co-Authored-By do commit ee382cc nomeia Claude Haiku 5.5 em vez de Claude Opus 5, porque foi o Haiku que escreveu o codigo. Mantenho como esta: reescrever o historico para atribuir a Opus seria menos exato, e atribuicao existe para registrar quem escreveu. Os demais commits seguem com a linha de Opus 5. Custo se errado: linhas de co-autoria heterogeneas no log, puramente cosmetico.

- Task 5: Ruling: mantenho o teste de fronteira extra (alvo em 7o lugar com top_n=7 ainda e suspeito). O raciocinio do implementador procede — o teste de 8o lugar do plano nao pegaria um corte off-by-one em top_n-1 — e esta funcao esta no topo do funil, onde um falso negativo remove um mono real do dataset para sempre, sem erro e sem rastro. Custo se errado: um teste a mais.

- Task 5: Ruling: o Important entra em correcao. Nenhum teste passa entrada desordenada, entao `sorted(...)` nao esta fixado — apagando-o e usando `masteries[:top_n]` os 6 testes continuam verdes. E exatamente o caminho do falso negativo que eu havia sinalizado: um alvo com muitos pontos no indice 9 de uma lista desordenada seria descartado em silencio. Custo se errado: baixo, sao testes.

- Task 5: Ruling: incluo no mesmo round o teste da fronteira inclusiva da janela, classificado Minor. Eu decidi explicitamente por `>=` neste ledger, e um ruling sem teste e um ruling que reverte sozinho na primeira refatoracao. Tambem o rename de ZED_FILLER (ids 10-16 nao sao Zed), ja que o arquivo sera tocado. Custo se errado: dois testes e um nome.

- Task 6: Ruling: `platform` sai de `info.platformId` em minuscula, nao de parametro. E a fonte autoritativa e evita um parametro que o chamador poderia passar errado. PARA A TASK 9: nao passar platform ao extract_match. Custo se errado: baixo, e um campo derivavel de ambos os lados.

- Task 6: Ruling: teamPosition nao-vazio mas fora dos cinco nomes canonicos (ex. "Invalid") classifica como unpaired_lanes, nao missing_position. Nao esta faltando, esta quebrando o pareamento. Custo se errado: um descarte contado na categoria vizinha.

- Task 6: Ruling: payload sem `info` ou `perks` levanta KeyError, nao DiscardMatch — aceito NESTE modulo, porque classificar quebra estrutural e decidir se o run continua e politica do chamador. PARA A TASK 9: envolver extract_match e capturar KeyError/TypeError, registrando descarte com motivo "malformed_payload", para que um payload corrompido nao mate uma coleta de horas mas apareca no relatorio de descarte. Isso acrescenta um quinto motivo, de posse da Task 9. Custo se errado: um payload estranho aborta o estagio 3 em vez de ser contado.

- Task 6: Ruling: o Important entra em correcao. Os testes de chamariz existem so para `pair_lanes`; nenhum teste de `extract_match` define individualPosition/lane/role, e as fixtures nao tem essas chaves. Trocar `role = me["teamPosition"]` (matchparse.py:86) por `me.get("individualPosition", me["teamPosition"])` deixaria os 34 testes verdes. E a unica linha que grava a posicao armazenada, no modo de falha que a spec chama de mais perigoso. Custo se errado: baixo, e um teste.

- Task 6: Ruling: incluo dois minors no mesmo round, ambos aditivos. (a) a guarda de duplicata dentro do laco (matchparse.py:59-60) nao tem cobertura exclusiva — apagando-a tudo fica verde, porque a unica fixture de duplicata tambem falta JUNGLE; pedir um caso de time de seis. (b) a ordem dos pares por teamId ascendente esta documentada e nao afirmada, e a Task 7 pode depender dela — pinar antes de escrever a Task 7 e mais barato que depois. Mais um teste para o KeyError do ruling 3. Custo se errado: tres testes.

- Task 7: Ruling: a regra do quadro do minuto 14 que EU ditei (`timestamp <= 840_000`) esta errada, e o implementador pegou. Timestamps reais de quadro da Riot ficam um pouco acima da marca do minuto (840012, nao 840000), entao o "maior timestamp <= 840000" selecionaria o quadro do minuto 13 — em TODA partida, sistematicamente, e o ouro aos 14 e o diagnostico principal do produto. Troca: selecionar por indice, derivado de `info.frameInterval` (default 60000 se ausente), `idx = (14 * 60_000) // frameInterval`, exigindo `len(frames) > idx`, e percorrer ate `idx + 1` para nao perder eventos de 14-15 min. Quadros vem um por minuto a partir do indice 0, entao o indice e exato e imune a jitter. Custo se errado: se frameInterval variar de forma que eu nao preveja, o indice erra — mas a guarda de comprimento impede leitura de quadro inexistente.

- Task 7: Ruling: menos de 3 skill-ups NORMAL deixa de levantar ValueError e passa a devolver `skill_order = None`, como os campos do minuto 14. Uma excecao ali mataria o estagio 4 numa partida curta (remake de 3 min tem 1-2 pontos de habilidade), e preencher com dado falso e pior. Exige `TimelineRow.skill_order: tuple[int,int,int] | None` em rows.py — a Baseline da Task 11 ja preve esse campo opcional, entao fica consistente. Custo se errado: um campo a mais que o chamador precisa checar.

- Task 7: Ruling: ITEM_UNDO e ITEM_SOLD dentro do primeiro minuto passam a afetar tambem `starting_items`, nao so `item_order`. Desfazer compra no nivel 1 e comum, e hoje um item comprado-e-desfeito permanece nos itens iniciais — dado errado, nao dado faltante. Custo se errado: baixo.

- Task 7: Ruling: o implementador apontou que db.py NAO aceita skill_order=None — coluna `skill_order TEXT NOT NULL` e `json.dumps(list(...))` no insert, com o mesmo problema na leitura. E consequencia direta do meu ruling de tornar o campo opcional, e a Task 10 quebraria na primeira partida curta. Como isso e carga para a Task 10, corrijo agora em vez de diferir: coluna nullable, insert e leitura tratando None, e teste de round-trip com None. Autorizo a edicao de db.py (arquivo da Task 4) neste round, porque o defeito nasceu aqui. Custo se errado: alteracao de schema num banco que ainda nao existe em producao, entao praticamente nenhum.

- Task 7: Ruling: o Important entra em correcao. Timelines da Riot terminam com um quadro extra no instante do fim de jogo, fora da marca do minuto — entao uma partida encerrada as 13:40 teria esse quadro truncado no indice 14, a guarda `len(frames) > idx` passaria, e o ouro de 13:40 seria reportado como ouro aos 14 minutos. E a MESMA falha que o ruling do round 1 corrigiu, pelo angulo que faltava: o round 1 impediu escolher um quadro cedo demais, este impede escolher um quadro que nao e de minuto 14 nenhum. Acrescentar `frames[idx]["timestamp"] >= SNAPSHOT_MS` a guarda. Decisivo: a correcao e segura independentemente de quem esta certo sobre o formato do payload — se nao existir quadro truncado, a condicao extra nunca muda nada, porque um quadro de minuto 14 real sempre fica na marca ou acima; se existir, ela evita o numero errado. Logo a incerteza nao precisa ser resolvida antes, e nao preciso de chave de API para decidir. Custo se errado: nenhum, e uma condicao estritamente mais restritiva.

- Task 8: Ruling ANTECIPADO: o Step 5 do plano para a Task 8 manda rodar a peneira de verdade numa regiao, o que exige chave da Riot. NAO TEMOS CHAVE nesta sessao. Entao a Task 8 entrega implementacao + testes com cliente falso, e a execucao real fica como acao do usuario. O mesmo vale para o go/no-go da Task 9. Isso precisa ser dito ao usuario no fim: o portao que decide o projeto depende da chave dele. Custo se errado: nenhum, e uma limitacao de ambiente. JA COMUNICADO ao usuario nesta sessao, com a sugestao de providenciar a chave de desenvolvimento em paralelo (sai na hora, expira em 24h, basta pro go/no-go).

- Task 8: Ruling: PROMOVO a Important o achado do lock de escrita mantido durante chamadas de rede. O revisor classificou Minor assumindo execucao sequencial, "como no brief" — mas a SPEC manda rodar as quatro regioes em PARALELO, porque os limites da Riot sao por regiao e e so assim que a coleta cabe numa noite. O revisor nao tinha a spec, eu tenho. Com duas invocacoes no mesmo --db, a primeira mark_screened abre transacao de escrita que fica aberta por ~1 minuto esperando o rate limiter, e o timeout default do sqlite3 e 5 segundos: "database is locked" no caminho principal do projeto. Correcao: acumular o lote em memoria e gravar numa transacao curta. Custo se errado: nenhum, a mudanca tambem melhora o caso sequencial.

- Task 8: Ruling: incluo tambem o RiotError nao capturado no CLI. Chave de desenvolvimento expira a cada 24h e a coleta real e um job de horas, de madrugada — chave vencida no meio e a falha de runtime mais provavel que existe, e hoje ela sai como traceback. Dado nao se perde (lote faz rollback, anteriores ja commitados), mas uma linha de mensagem e exit 1 definido valem mais que um traceback. Custo se errado: baixo.

- Task 9: Ruling (o mais importante da sessao): o DIVISOR da concentracao. O implementador dividiu por `window_games` (60 fixo) porque so assim o teste 4 do MEU plano passa (26 TOP + 26 MIDDLE nao qualificar: 26/52 = exatamente 0.50, que satisfaz `>= 0.50`). Mas dividir por 60 esta ERRADO e o meu teste forcou a implementacao errada. Tres argumentos: (a) A spec diz "aquele campeao naquela funcao responde por >= 50% DAS PARTIDAS" — das partidas consideradas, nao de um 60 hipotetico. (b) Dividir por 60 rejeita sistematicamente mono de baixo volume: 25 Talon em 30 partidas e 83% de concentracao, mono de manual, e daria 25/60 = 41.7% — rejeitado. Isso e o OPOSTO do objetivo do projeto, que e justamente achar especialistas. (c) Sob /60, `min_games=25` fica REDUNDANTE (25/60 = 0.417 < 0.5, logo a proporcao sempre manda), e o meu proprio plano diz "os dois criterios juntos sao necessarios". O divisor /60 contradiz a intencao escrita do plano. DECISAO: share = alvo / len(janela efetiva). O teste 4 do plano esta errado e sai. Custo se errado: o go/no-go conta mais jogadores como mono; se vier frouxo demais, aperta-se min_share na configuracao, que e o parametro certo para isso — nao um divisor escondido.

- Task 9: Ruling: sob a spec (`>= 0.50`), um Gragas 26/26 entre topo e meio QUALIFICA para o primeiro alvo casado. Isso e consequencia do limiar da spec, nao bug. Se o usuario nao quiser isso, o ajuste e min_share > 0.5 na configuracao, explicito e visivel. Vai como teste documentando o comportamento mais um teste com min_share=0.6 rejeitando.

- Task 9: Ruling: incluo teste do caso que motiva a correcao (30 Talon em 40 partidas = 75% qualifica) e do que o min_games volta a fazer (8 em 12 = 67% de proporcao mas 8 < 25, rejeitado).

- Task 9: Ruling: a ressalva 4 do implementador (mutacao movendo riot_id para dentro do batch de escrita nao foi pega) vira teste: a mesma assercao de "nenhuma transacao de escrita aberta" tem de cobrir a chamada de riot_id.

- Task 9: Ruling: o Important entra em correcao. O catch e `(KeyError, TypeError)` so, mas extract_match tem caminhos que levantam IndexError (styles[1] com lista curta, primary_perks[0] com selections vazio), AttributeError (platformId nao-string) e StopIteration (next() do oponente). E a MESMA falha que o ruling existia para prevenir, pela porta nao olhada — e pior que a original: pending_suspects e ordenado por rowid e o jogador nunca e decidido, entao um payload deterministico com IndexError mata o run e mata TODA reexecucao no mesmo jogador. Loop de crash permanente. Custo se errado: o catch fica largo e um bug nosso de parsing viraria descarte em vez de excecao — mitigado porque discard_counts expoe a taxa.

- Task 9: Ruling: minha propria frase "com min_share >= 0.5 um empate e impossivel" e FALSA e eu a repeti no ruling e no docstring. O exemplo 26/26 contradiz: ambos qualificam a exatamente 0.5 e o vencedor depende da ORDEM da configuracao. Corrigir para "acima de 0.5" nos dois lugares. Custo se errado: nenhum, e correcao de documentacao sobre comportamento real.

- Task 9: Ruling: incluo o fallback do riot_id. Um 404 ali aborta o estagio e descarta as ~60 requisicoes ja pagas daquele jogador, em toda reexecucao — mesmo principio do Important: dado cosmetico nao pode matar coleta de horas. Capturar RiotError, confirmar com nome vazio e registrar. Custo se errado: a lista de referencia da Tela 2 mostra um jogador sem nome.

- Task 9: Ruling: incluo dois minors baratos — o fake de match_ids passa a respeitar `count` (hoje devolve 85 ids onde a API devolveria 60, tornando o teste desonesto) e o teste de payload malformado passa a afirmar que o jogador recebeu veredito (pending_suspects == []).

- Task 9: Ruling: fecho a QUARTA encarnacao do mesmo perigo, que o re-revisor achou fora do diff: `client.riot_id` faz body['gameName'] e body['tagLine'], entao um corpo sem essas chaves levanta KeyError, que DESVIA do fallback de RiotError que acabamos de criar — e produz exatamente o loop de crash que este round fechou. Classificado abaixo de Important pelo revisor e fora do diff, mas eu promovi essa mesma classe de defeito duas vezes nesta task; deixar uma instancia conhecida aberta seria incoerente. Correcao: alargar o fallback do chamador para (RiotError, KeyError, TypeError), SEM tocar riot.py — mesmo principio de "a politica e do chamador" que rege o malformed_payload. Custo se errado: proximo de zero (uma excecao a mais tratada numa requisicao cosmetica) contra uma coleta morta.

- Task 9: Ruling (encerra o padrao): o re-revisor apontou uma QUINTA porta — json.JSONDecodeError, subclasse de ValueError, se o corpo nao for JSON — que tambem desviaria do tuple e reproduziria o loop. Diagnostico: a abordagem de ENUMERAR tipos de excecao esta perdendo; cada round acha outro tipo. Paro de jogar whack-a-mole e corrijo a CATEGORIA: a chamada do riot_id passa a `except Exception`. Justificativa de por que uma captura larga e CORRETA justamente ali: o valor e puramente cosmetico (so alimenta a lista de referencia da Tela 2), o fallback e bem definido e CONTADO (nome vazio + unnamed), e a alternativa e uma coleta morta. `except Exception` nao captura KeyboardInterrupt nem SystemExit, que sao BaseException, entao Ctrl+C segue funcionando. Custo se errado: um jogador confirmado sem nome por um motivo que nao investigamos — visivel no contador unnamed.

- Task 9: Ruling (assimetria deliberada): NAO alargo o catch do malformed_payload para `except Exception`. La a enumeracao fica. Diferenca: malformed_payload e por partida, e a instrumentacao de taxa de descarte (discard_counts) e a rede que expoe problema sistematico; uma captura larga ali esconderia bug NOSSO de parsing como "descarte" com menos visibilidade. riot_id e por jogador, cosmetico, e tem contador proprio. Custo se errado: um tipo novo de quebra estrutural em extract_match ainda derruba o run — mitigado porque o padrao agora esta documentado e a correcao e conhecida.

- Task 10: Ruling ANTECIPADO (defeito de plano que eu vi antes de dispatchar): `matches_awaiting_timeline()` devolve partidas SEM linha de timeline. Quando a Riot responde 404 (a spec registra que nao toda partida tem timeline), nao ha TimelineRow para inserir — entao a partida continua "pendente" e e pedida de novo em TODA execucao. E o loop de refetch no request MAIS CARO do projeto, e o plano nao previu. AUTORIZO editar db.py para marcar timeline ausente (tabela propria `timeline_missing(match_id, puuid)` ou equivalente), com matches_awaiting_timeline excluindo marcados. Inserir TimelineRow sentinela com zeros seria pior: poluiria a agregacao com dado falso. Custo se errado: uma tabela a mais num schema que ainda nao existe em producao.

- Task 10: Ruling: falha de PARSE do timeline (nao 404) tambem precisa ser marcada para nao ser repetida, mas contada em campo SEPARADO de `missing`, porque misturar bug nosso com ausencia da Riot esconderia o nosso. TimelineReport ganha (requested, extracted, missing, failed).

- Task 10: Ruling: PROMOVO o Minor dos valores de `reason` nunca afirmados. Trocar "not_found" por "parse_error" no codigo passaria em TODOS os testes — e a historia de recuperacao ("apague as linhas parse_error") depende inteiramente desse valor estar certo. E o mesmo padrao de "cobertura que parece cobrir" que promovi a sessao toda. Custo se errado: um teste.

- Task 10: Ruling: PROMOVO o Minor do bug sistematico de parser, e e o modo de falha mais caro que resta no projeto. Se o parser quebrar em todos os payloads, a coleta paga a noite inteira de timelines (o request mais caro), marca tudo como parse_error, NAO guarda nada, e sai com codigo 0. Sem --raw-sample-dir os payloads tambem se perdem. A economia inteira da spec e "timeline e viavel porque cada uma e baixada uma vez" — pagar uma vez e nao ficar com nada quebra essa premissa. Correcao: disjuntor por falhas CONSECUTIVAS que aborta, e crucialmente SEM MARCAR as falhas, para que o trabalho seja retentavel depois da correcao do parser. Custo se errado: um run legitimo com muitas partidas estranhas seguidas aborta antes do fim — preferivel a pagar tudo e nao ter nada.

- Task 11: Ruling: o Important entra em correcao. Nos dados do teste de ordenacao (Ekko 40g/30%, Sylas 35g/60%, Ahri 10g/100%, Zed 5g/0%) a ordem por taxa crescente COINCIDE com a ordem por partidas decrescente, dentro do grupo confiavel. Logo a chave primaria de ordenacao — a regra mais visivel do produto, que e a lista de matchups difíceis — nao esta fixada por teste nenhum. Uma chave errada daria saida plausivel sem falha. Custo se errado: baixo, e mudanca de dados de teste sem mudanca de comportamento.

- Task 11: Ruling: a lacuna residual — "derrotas decrescente" (28, 20, 10) coincide com a regra certa — fica DIFERIDA, nao corrigida. Trabalhei a aritmetica: para quebra-la mantendo todas as outras seis regras quebradas e Ekko acima do piso de 30, e preciso comprimir as taxas para algo como Ekko 30g/17v/13d (56.7%), Sylas 60%, Yone 66.7%. Isso funciona, mas destroi a legibilidade dos dados (tres taxas coladas entre 57% e 67%) e, pior, destroi a narrativa do teste: Ekko deixa de ser o matchup difícil a 30% e passa a 57%. Troca ruim por uma chave que ninguem implementaria — a funcao calcula `win_rate` e ordena por ele; "ordene por derrotas absolutas" nao e um erro plausivel de digitacao, e o campo losses nem existe em MatchupSummary. Custo se errado: uma chave errada improvavel ficaria sem pino; o revisor final ve a anotacao.

- Task 12: Ruling: a ressalva 3 do implementador e VIOLACAO DA SPEC e entra em correcao antes da revisao. Ele acrescentou, por iniciativa propria e com razao, um piso de amostra para comparar itens iniciais e ordem de habilidades (exige min_per_side partidas COM timeline de cada lado). Mas deixou as medias de OURO AOS 14 MINUTOS sem piso algum e sem declarar quantas timelines as sustentam. O ouro aos 14 e o diagnostico principal do produto — foi por ele que decidimos pagar o custo altissimo de baixar timelines — e ele pode acabar apoiado em 3 timelines numa tela que anuncia 40 partidas. A promessa central da spec e que todo numero na tela declara honestamente quanto dado o sustenta. Correcao: mesmo piso das outras comparacoes, e o arquivo declara a contagem de timelines de cada lado. Custo se errado: o ouro aos 14 some em matchups com poucas timelines — que e exatamente o certo quando nao ha dado.

- Task 12: Ruling: ressalva 5 (arquivos orfaos de matchup ao reexportar) fica como documentacao, nao correcao. O arquivo por alvo carrega o ranking de matchups, entao o site navega a partir dele e nunca le um orfao — eles sao entulho inofensivo, nao dado velho servido. Custo se errado: lixo no diretorio.

- Task 12: Ruling: o Important entra em correcao. O `headline` embute ids crus na frase voltada ao jogador ("botas 3020", "runa 8347"), e o contrato manda o site "renderizar o headline". A excecao que eu aceitei cobre campos `label`, que o site resolve via Data Dragon — nao cobre uma frase livre que o site teria de reescrever com regex. Correcao: headline fica sem ids, e o site monta a frase a partir de divergences[0]. Custo se errado: o site precisa de uma linha de montagem de texto, que ele ja precisaria para os labels.

- Task 12: Ruling: PROMOVO o Minor do MIN_GAP nao fixado. O unico teste acima do limiar tem gap 0.2, e a assercao usa a constante importada — tautologica. Mudar o limiar para qualquer valor entre 0.16 e 0.19 passa a suite inteira. E o mesmo padrao de "cobertura que parece cobrir" que promovi em quase toda task. Custo se errado: um teste.

- Ruling: corrijo em vez de parkear, e NAO e uma segunda fix wave — e um achado load-bearing adjudicado, com correcao de duas linhas ja especificada e verificada por mim na fonte. Motivo: reproduz a MESMA frase falsa do Critical ("fizeram as escolhas de forma igual em botas") num dos cinco alvos, e a guarda e tudo-ou-nada, entao um unico jogo com bota de tier 2 sobrando basta para restaurar a mentira. Custo se errado: duas linhas e um teste.

- MEDICAO (coleta BR1, 05/11/2026): a conversao suspeito->mono e de 5 em 123, ou 4,1%. Sobre os 776 suspeitos de BR1 isso projeta ~32 monos na regiao. Os 5 confirmados sao Jax TOP x2, Talon MIDDLE x2, Gragas TOP x1; nenhum Renekton TOP, nenhum Gragas MIDDLE. Media de 39,4 jogos no campeao-role alvo por mono. Descarte acumulado: 14 missing_position em 7.366 partidas (0,19%), desprezivel.

- MEDICAO: dos 123 suspeitos triados, a distribuicao de share e BIMODAL e quase sem meio: 102 abaixo de 20%, 4 entre 40% e 50%, 5 acima de 50%. A peneira de maestria e lifetime; quem tem Jax no top 3 de maestria e esta abaixo de 20% simplesmente parou de jogar Jax. Consequencia pratica: o corte min_share=0.50 NAO esta mal posicionado. Baixa-lo para 0,40 renderia 4 jogadores a mais em 123 (um deles Talon JUNGLE, fora do escopo), ou seja, troca pouco volume por uma definicao de mono mais fraca. Fica em 0,50.

- MEDICAO: cinco jogadores com share acima de 60% foram corretamente REJEITADOS por serem SELVA (quatro Talon jungle, um Gragas jungle). Nao e defeito: a role nao esta nos targets. Mas o achado importa para a expectativa de volume — em BR1 a populacao de monos de Talon e majoritariamente de selva, nao de meio, o que reduz o rendimento para Talon MIDDLE especificamente.

- MEDICAO, e este e o achado estrutural do projeto: o leque de oponentes e largo demais para o piso de amostra. Talon MIDDLE tem 41 oponentes DISTINTOS em 73 jogos; o oponente mais frequente aparece em 8,2% dos jogos. Jax TOP tem 36 oponentes em 84 jogos, o lider com 11,9%. Projetando BR1 completa (~1.245 jogos alvo), o matchup LIDER de cada campeao-role chega a 25-63 jogos — na fronteira de matchup_min_games=30 — e todo o resto fica abaixo. Pior: delta_min_per_side=15 exige 15 vitorias E 15 derrotas no MESMO matchup, o que em matchup desequilibrado precisa de ~60-70 jogos. Jax vs KSante projeta 63 jogos a 80% de vitoria, isto e, ~13 derrotas: passa o piso de listagem e falha o de comparacao. O produto desenhado (vencedores vs perdedores dentro de um matchup) so se sustenta nos 3-5 oponentes mais comuns de cada campeao-role, e so depois de coletar as quatro regioes.

- MEDICAO: Talon vs Ekko, o matchup que o usuario final NOMEOU, apareceu 1 vez em 73 jogos (1,4%). Projetado para as quatro regioes da ~25-40 jogos, isto e, no melhor caso encosta no piso de 30 e nunca chega aos 15 por lado. A pergunta original do amigo e provavelmente a que este desenho NAO consegue responder, porque Ekko meio e raro. Registrar isso explicitamente importa mais que qualquer outro numero desta medicao: o pior resultado possivel do projeto e ficar silenciosamente errado, e prometer uma resposta sobre Ekko seria exatamente isso.

- MEDICAO (custo): triagem mediu 1,2 s por candidato (9.700 em 3h15). Estagio 3 mediu 1,25 min por suspeito (123 em 2h34). Logo os 653 suspeitos restantes de BR1 custam ~13,6 h. As outras tres regioes, cujas ladders apex somam na ordem de 5x BR1, custam ~18 h de triagem e ~81 h de estagio 3. Total restante ~113 h sequenciais; com as regioes em paralelo (orcamentos de rate independentes) o gargalo passa a ser a maior regiao, na ordem de 40 h de maquina ligada, com a chave de dev expirando a cada 24 h.

- OPERACIONAL (05/11/2026): `*> arquivo.txt` funciona no terminal interativo do operador, mas NAO dentro de um wrapper nao-interativo cujos fluxos ja estao redirecionados (o caso do agente rodando em background). No PowerShell 5.1 o `*>` reatribui cada fluxo e acaba abrindo o mesmo arquivo duas vezes, falhando com "cannot access the file because it is being used by another process". O comando morre no MEIO, nao no comeco: quatro execucoes assim ja tinham triado 250 candidatos e processado um suspeito antes de cair. Nao mexer no README, cuja instrucao e para o operador e esta correta; quem roda em background deve omitir o redirecionamento e deixar o harness capturar. Licao de segunda ordem: "o comando falhou" nao implica "nada aconteceu" — conferir com `status` antes de afirmar. Eu afirmei o contrario e estava errado.

- MEDICAO (05/11/2026, estagio 3 das quatro regioes em paralelo): o estagio 3 NAO paraleliza em quatro, so em tres. O limite de rate e por HOST, e `PLATFORM_TO_REGIONAL` manda br1 e na1 para o mesmo host `americas`. Triagem (maestria) usa host de plataforma e portanto paraleliza em quatro de verdade; match-v5 usa host regional, entao br1 e na1 dividem um unico orcamento de 100/120s. Medido: kr (asia) e euw1 (europe) rodaram a 1,23 min por suspeito, que e exatamente o teto de 50 req/min; br1 e na1 rodaram a 1,80 e 2,46 min, ou seja, metade do ritmo cada. Consequencia para o planejamento: acrescentar LAN ou LAS nao compra paralelismo nenhum, porque caem em americas tambem. As tres regioes rapidas possiveis sao uma de americas, kr e euw1.

- MEDICAO: a conversao suspeito->mono varia MUITO por regiao, e a diferenca e real, nao ruido. Sobre amostras de 107 a 348 suspeitos processados: kr 13,1%, na1 11,2%, br1 5,5%, euw1 4,2%. KR converte 3x mais que EUW1. Consequencia: a projecao de custo por mono de 37,6 min, medida em BR1, e PESSIMISTA para kr e na1 e otimista para euw1. Se houver uma proxima rodada, priorizar kr.

- MEDICAO: Gragas MIDDLE saiu do zero (4 monos de 68) depois de eu registrar que zero em cinco pares era compativel com azar. Era azar mesmo. Mas ele segue sendo o par mais pobre com folga, e e ele que limita o produto: projetado para o fim da janela, ~9 monos e ~341 jogos, o que poe o matchup lider dele em 28-41 jogos. Isso passa o piso de listagem (matchup_min_games=30) na margem e NAO alcanca delta_min_per_side=15 de cada lado, que precisa de ~60 jogos no mesmo matchup. Previsao honesta: Gragas MIDDLE tera base e lista de matchups, mas nao tera comparacao vencedor-vs-perdedor. Os outros quatro pares tem folga.

## Site estatico (05/11/2026) — execucao subagent-driven do plano 2026-11-05-site-estatico.md

- Ruling: `deno.lock` entra no repositorio. Fixa `jsr:@std/assert`, unica dependencia externa do harness de teste; sem ele um `deno task test` futuro resolve outra versao e a suite passa a medir outra coisa. Nao afeta o site publicado, que nunca carrega Deno. Custo se errado: um arquivo a mais.

- Ruling (repetido em quase toda task): PROMOVO ao loop de correcao todo teste cuja assertiva passa contra varias implementacoes plausiveis, quando o valor em jogo e load-bearing. Casos: o arredondamento de `pct`, cujo unico caso (0,5816 para 58%) passava identico sob round, floor e trunc, embora `pct` escreva TODA porcentagem das tres telas; `pct(undefined)` devolvendo "NaN%" quando o arquivo de matchup nao tem campo `win_rate`; as guardas de `vs` e de slug nao-vazio do roteador, cuja remocao faria `#/a/foo/245` virar matchup com a suite inteira verde; o `||` na assercao do Doran, que aceitava saida escapada OU nao escapada e portanto sobreviveria a remocao do escape de nomes de item; e o teste da secao separada, que provava que titulo e campeao apareciam mas nao que um estava DENTRO do outro. Custo se errado em cada: um teste.

- Ruling: DEFIRO o minor da taxa de vitoria ACIMA do piso sem teste, e a distincao importa porque promovi varios parecidos. No `pct` o teste passava sob round/floor/trunc, isto e, a correcao do codigo ATUAL estava nao verificada. Aqui o revisor leu o codigo e confirmou que esta certo hoje; a lacuna e protecao contra regressao futura de um display. Promover tudo que se PARECE com o padrao e tao ruim quanto nao promover nada.

- Ruling: o `throw` do `loadDdragon` em resposta nao-ok FICA, mas com teste que exija o status na mensagem. Sem ele, um `ddragon_version` velho viraria TypeError opaco dentro do indexador em vez de dizer o que houve.

- Ruling ANTECIPADO (defeito de plano visto antes de dispachar, verificado no CDN ao vivo): `runeName` tem que indexar tambem os cinco ids de ARVORE do topo do runesReforged.json. O contrato guarda `primary_style` e `secondary_style`, que sao ids de arvore e NAO estao em nenhum `slots` — um indice que so desca em slots renderiza dois campos da pagina de runas de todo campeao como numero cru, e os testes do brief nunca pegariam porque so exercitam a runa 8112.

- LACUNA FECHADA: os feiticos de invocador sairiam como id cru. `summoner.json` existe no CDN fixado com a mesma forma do champion.json. Ruling: carregar como quarto arquivo, sem tabela hardcoded — e fonte oficial, diferente dos fragmentos. O teste que afirmava 3 URLs passou a afirmar 4, ATUALIZADO e nao afrouxado, porque a contagem e parte do que ele pina.

- Ruling: a tabela de FRAGMENTOS de runa entra em `ddragon.js` com comentario dizendo que a fonte e o DONO DO PROJETO conferindo no cliente do jogo, nao o Data Dragon. Sondei runesReforged, perkstyles, perks, runes e statmods no CDN: os ids 5001, 5002, 5003, 5005, 5007, 5008, 5010, 5011 e 5013 nao existem em nenhum. Aquelas nove linhas envelhecem de forma diferente de todo o resto do modulo e quem ler depois precisa saber em que ordem desconfiar.

- Ruling: entra SO O NOME do fragmento, nunca a magnitude. O dono informou "+6 de Armadura" e "+8 de RM", deliberadamente excluidos: magnitude e especifica do patch, nao esta nos nossos dados, nao pode ser verificada pelo site, e seria numero na tela sem fonte e sem denominador, envelhecendo em silencio no proximo rebalanceamento. "Armadura" e verdade estavel.

- Ruling: o slug do link sai do campo `file` do indice, NUNCA de `champion_name` mais `role`. O exportador e dono dessa transformacao (guarda so minusculas e digitos, entao um nome com apostrofo perde o apostrofo). Nenhum dos cinco alvos tem pontuacao, logo o bug so nasceria quando alguem acrescentasse alvo meses depois.

- Ruling: a tela NAO afirma que a janela de coleta e larga. Imprimia "Uma janela larga mistura patches na mesma base" para QUALQUER janela nao-nula, inclusive de um dia — afirmacao sobre os dados feita sem olhar os dados. Passou a mostrar o vao em dias e enunciar a mistura como regra geral. Agravante medido: o vao real e de ~111 dias mas 85% das partidas estao nos ultimos 30, entao ate "larga" afirmava demais.

- Ruling: NAO guardo contra estados que o contrato declara impossiveis — meia-janela de coleta, `Number(null)` resolvendo como item 0, `comparable: true` com divergences vazio E headline nulo, `starting_items: []` nao-nulo. Guardar contra estado que o exportador nao produz dilui o contrato; se ele mudar, o contrato muda primeiro.

- Ruling: ESCALEI a Important numero 1 da Task 5 para Critical. O revisor marcou Important; abri o `jax-top.json` exportado de verdade e `starting_items` e `skill_order` estavam NULOS, porque o estagio 4 nunca rodou. A tela chamava `.map` neles, lancando TypeError nos CINCO alvos com os dados daquele dia. Nao era caso de borda, era o estado atual.

- Ruling: linha ABAIXO do piso nao imprime taxa de vitoria, so contagem de jogos. O denominador estar presente nao resgata numero que e ruido: 60% em 5 partidas logo abaixo de um titulo dizendo "dados insuficientes" e mensagem contraditoria. O piso e a declaracao do projeto de que abaixo dele nao se afirma nada, e porcentagem e afirmacao.

- Ruling: a linha do PONTO CEGO de botas imprime cada contagem contra seu denominador (`wins` e `losses`, que e o correto para esse campo, nao `timeline_games`). Imprimia "12 de vitoria e 11 de derrota" e deixava "alto" por conta do leitor: 12 de 12 e ponto cego total, 12 de 200 e ruido, e sem denominador os dois leem igual — o leitor nao distingue "houve concordancia" de "nao conseguimos ver".

- Ruling: corte da grade de itens em 5% das partidas da base, teto de 12 linhas, com nota declarando quantos ficaram de fora e o denominador. A tela renderizava a lista INTEIRA, ~130 linhas descendo ate item com uma unica partida; a spec pede grade de itens e o que estava na tela era a loja do jogo, com a build soterrada. SO A VERIFICACAO VISUAL PEGOU: 72 testes passando e cinco telas sem null nem NaN contra dado real, e a pagina principal inutilizavel por excesso — nenhuma assercao de string pega "tecnicamente correto e ilegivel".

- Ruling: a secao abaixo do piso (~80 linhas) e RECOLHIDA em `<details>` com a contagem no summary, nao truncada. E material de referencia: quem procura um matchup raro especifico tem que continuar achando. Recolher nao perde informacao, truncar perderia.

- Ruling: a onda de correcao final leva SO os dois Important da revisao de branch mais o link de volta na tela de erro. Ha exatamente UMA re-revisao da onda, e alargar o escopo reduz a chance de ela verificar o que importa.

- Ruling: a frase que declara ausencia de timeline cita o piso `min_per_side` e os denominadores de cada lado. Dizer que um piso nao foi atingido sem dizer qual e o piso e a regra central do projeto aplicada frouxamente exatamente na linha cuja unica funcao e explicar uma ausencia.

- ERRO MEU, corrigido na revisao final: na Task 6 promovi o teste do par de medias meio-nulo pelo raciocinio certo — o contrato escopa o "tudo ou nada" a CADA par, e ouro e farm sao pares separados — e depois nao notei que a correcao escolheu OMITIR a metrica ausente em silencio, com dois testes carimbando o esconder ("omite o farm", "omite o ouro"). Precisei de um revisor olhando o branch inteiro para ver que eu tinha pedido a coisa certa e aceitado a resposta errada. Licao: uma assertiva que afirma AUSENCIA nao distingue "a tela explicou a lacuna" de "a tela ficou calada".

- ERRO MEU: a assertiva do plano que proibia a frase "0 de ouro" era VAZIA — o codigo nunca produz essa frase. Pior que ausente: a lacuna deixa de ser visivel e quem le o teste acredita que o caso esta coberto. Corrigida no plano e no teste.

- PARA A CONFERENCIA EXTERNA (pendente, do dono): a revisao final confirmou que nada no site quebra se `item_frequency` estiver errado e que nenhum denominador exibido vira falso. A exposicao e outra: se o exportador contar componente e consumivel, o site imprime fielmente uma contagem VERDADEIRA sob um titulo FALSO ("Itens finais"). Nos dados reais, componente e inicial ocupam cerca de um terco da grade principal (o primeiro item do Talon e 1055, Lamina de Doran). A correcao e no exportador ou no titulo, NUNCA uma lista de exclusao no site — isso inventaria semantica que o contrato nao define, o mesmo erro de inventar nome de fragmento.

## Ajustes de produto depois do merge (06/11/2026)

Decisoes tomadas com o site ja publicado, a pedido do dono. Ficam aqui porque
o historico guarda o que mudou e nao o porque — e porque o piso de amostra em
particular mudou duas vezes na mesma noite, por motivos diferentes.

- Ruling: o texto explicativo caiu de 129 para 82 palavras SEM remover nenhuma
  afirmacao. Cada frase existia contra um mal-entendido concreto (que a base e
  recomendacao, que a lista de itens e build pronta, que a taxa da pagina de
  runas foi o criterio); todas encurtaram, nenhuma saiu. A de itens foi de 41
  para 16 dizendo a mesma coisa. Preservei de proposito as frases que os testes
  de comportamento afirmam, entao nenhuma assertiva foi afrouxada.

- Ruling: itens exibidos do mais barato ao mais caro, mas a SELECAO continua por
  frequencia. Sao dois passos distintos de proposito: ordenar por preco e so
  entao cortar 12 mostraria os doze itens mais baratos do inventario, que nao
  diz nada. `itemGold` devolve null e nao 0 para id desconhecido, porque 0 e
  preco valido e poria o desconhecido antes do mais barato de verdade.

- ERRO MEU: o teste que prova que a selecao continua por frequencia nasceu com
  tres itens, abaixo do teto de 12 — entao ordenar antes ou depois do corte dava
  no mesmo e o bug classico passava com zero falhas. Assertiva com a ideia certa
  e fixture que nao exercita a regra, o mesmo padrao que promovi a sessao
  inteira. So apareceu porque rodei a mutacao. Refeito com 15 itens acima do
  piso.

- PISO DE AMOSTRA, primeira mudanca (30/15 -> 20/10): o pedido era pagina para
  confronto com mais de 10 partidas. Medi antes: baixar so `matchup_min_games`
  criaria 111 paginas e ZERO comparacoes, porque 15 por lado exige 30 partidas.
  O piso que importava era o outro. Criterio usado: o limiar de divergencia e
  15 pontos percentuais, entao com N partidas de um lado um jogador move 100/N
  — em 15 uma divergencia exige 3 jogadores, em 10 exige 2, em 5 exige UM e
  toda divergencia vira ruido por construcao.

- PISO DE AMOSTRA, segunda mudanca (20/10 -> 16/8): o dono pediu explicitamente
  o confronto Talon vs Ekko, 19 partidas divididas em 8 e 11, que originou o
  projeto. Feito como REGRA e nao como excecao para aquele confronto: escolher
  um padrao mais frouxo so para o caso cuja resposta se quer ver e raciocinio
  motivado virando configuracao.

- MEDICAO QUE PESA CONTRA ESSA ESCOLHA, e que o dono recebeu antes de decidir
  publicar: o numero de divergencias SOBE quando a amostra encolhe. Mediana de
  13 divergencias com 8-9 por lado, 9 com 10-14, 7 com 15-24, 4,5 com 25+. Isso
  e assinatura de ruido — efeito real daria mais diferenca confiavel com mais
  dado, nao menos. A pagina do Ekko tem 18 divergencias e as bem amostradas tem
  4 ou 5. O dono optou por publicar sabendo disso. Voltar e trocar dois numeros
  em config.toml e reexportar.

- Ruling: nenhum filtro de componente na lista de itens. Medi: o teste obvio
  (item com campo "into" no Data Dragon) marca botas de tier 2, que sao item
  final legitimo na maioria das partidas. Nao existe linha limpa entre
  componente sobrando e item barato que o jogador quis terminar segurando, e
  inventar uma seria regra minha virando verdade na tela. O que estava errado
  era o TITULO: "Itens finais" prometia build pronta, virou "Itens no
  inventario ao fim da partida".

- Ruling: fragmento de runa nao ganha icone. As imagens existem em
  perk-images/StatMods/, mas nenhum arquivo do Data Dragon mapeia id para nome
  de arquivo. Adivinhar nove nomes seria inventar dado, o mesmo erro que
  recusamos quando o dono forneceu os nomes em vez de eu chutar.

- OBSERVACAO DE PROCESSO: assistir deploy por "o run mais recente" e corrida de
  tempo — peguei o run anterior segundos depois de um push e conclui que
  arquivos novos estavam dando 404 por propagacao de CDN. Fixar pelo commit
  (`select(.headSha==$SHA)`) resolve. E a mesma licao do main.js buscar arquivo
  pelo nome que o JSON da em vez de montar: identificar pela coisa, nao pela
  posicao.
