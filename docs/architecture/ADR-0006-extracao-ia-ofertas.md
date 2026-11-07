# ADR-0006: Extração de ofertas com IA

- Status: aceita
- Data: 2026-11-05

## Contexto

Ofertas podem conter título do produto, preço original, preço com desconto e cupom em texto não estruturado. A extração usa mais de um provedor/modelo em ordem de fallback e mantém resultados associados às mensagens. Como esse processamento pode gerar custos, ele só funciona com provedor configurado.

## Decisão

Permitir configuração de OpenAI e OpenRouter em Configurações. O catálogo é consultado sob demanda. O usuário escolhe vários modelos e ordena uma hierarquia única. Ofertas novas do Telegram são enfileiradas automaticamente quando não ignoradas; mensagens individuais criam um item e álbuns aguardam o evento completo, criando um único item para o álbum. Jobs automáticos evitam duplicar ofertas já extraídas ou pendentes. Um job manual captura as mesmas ofertas do feed padrão da Home, limitadas às 100 exibidas, processa os itens de cada job sequencialmente e inicia jobs simultâneos conforme limite configurável descrito na [ADR-0008](ADR-0008-fila-extracao-concorrente.md); a fila global permanece FIFO, inclusive após reenvio. Antes de cada chamada, o worker consulta a ordem, os modelos e as chaves salvos; alterações valem na próxima chamada. Após reinício, itens em andamento retornam à fila. Falha de um modelo tenta o próximo. Resultados parciais válidos são aceitos; por padrão, jobs pulam ofertas já extraídas, com opção de substituição.

A extração considera todas as mensagens do álbum e retorna somente título do produto, preço original, preço com desconto e cupom; descrição não integra o prompt nem o resultado. Resultados ficam no SQLite e são invalidados quando uma mensagem muda ou chega nova parte do álbum. A gravação compara o texto atual ao texto enviado ao modelo para descartar respostas obsoletas. Cards na Home, Alertas e ofertas de termos priorizam os campos extraídos; o modal mantém a mensagem original.

Jobs na fila ou em andamento podem ser cancelados com autenticação e CSRF. Um job na fila cancela imediatamente. No lote em andamento, cancelar a tarefa HTTP assíncrona fecha a conexão local, descarta a resposta e cancela as ofertas restantes. A conexão local encerrada não garante que o provedor interrompa a geração ou deixe de cobrar.

A página de jobs permite apagar apenas jobs terminais ou cancelar jobs e limpar todo o histórico. A ação total marca o job ativo para exclusão após o encerramento do worker; se o processo reiniciar antes, a recuperação conclui a limpeza. Itens e tentativas são removidos pela cascata das chaves estrangeiras. O novo marcador `clear_requested` é adicionado com valor padrão e cria snapshot do banco antes da migração.

## Consequências

Ofertas novas podem gerar consumo de créditos automaticamente quando há provedor configurado. O texto integral enviado ao provedor pode conter dados privados; a interface avisa antes do processamento manual. Cancelamento interrompe a conexão local, mas o provedor pode continuar e cobrar. Chaves ficam sem criptografia no SQLite do volume; não são renderizadas nem incluídas em logs, então volume e backups precisam ser protegidos. Bancos antigos podem manter uma coluna `description` sem uso, preservada para evitar rebuild destrutivo; extrator e cards não a leem nem exibem. Integração real e tarifas não foram verificadas. O worker pressupõe uma única instância conforme o contrato de implantação.
