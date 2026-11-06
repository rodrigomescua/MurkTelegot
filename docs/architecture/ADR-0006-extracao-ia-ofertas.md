# ADR-0006: Extração de ofertas com IA

- Status: aceita
- Data: 2026-11-05

## Contexto

Ofertas podem conter título do produto, preço original, preço com desconto e cupom em texto não estruturado. A extração usa mais de um provedor/modelo em ordem de fallback e mantém resultados associados às mensagens. Como esse processamento pode gerar custos, ele só funciona com provedor configurado.

## Decisão

Permitir configuração de OpenAI e OpenRouter em Configurações. O catálogo é consultado sob demanda. O usuário escolhe vários modelos e ordena uma hierarquia única. Ofertas novas do Telegram são enfileiradas automaticamente quando não ignoradas; mensagens individuais criam um item e álbuns aguardam o evento completo, criando um único item para o álbum. Jobs automáticos evitam duplicar ofertas já extraídas ou pendentes. Um job manual captura as mesmas ofertas do feed padrão da Home, limitadas às 100 exibidas, e as processa sequencialmente em FIFO persistente. Antes de cada chamada, o worker consulta a ordem, os modelos e as chaves salvos; alterações valem na próxima chamada. Após reinício, itens em andamento retornam à fila. Falha de um modelo tenta o próximo. Resultados parciais válidos são aceitos; por padrão, jobs pulam ofertas já extraídas, com opção de substituição.

A extração considera todas as mensagens do álbum e retorna somente título do produto, preço original, preço com desconto e cupom; descrição não integra o prompt nem o resultado. Resultados ficam no SQLite e são invalidados quando uma mensagem muda ou chega nova parte do álbum. A gravação compara o texto atual ao texto enviado ao modelo para descartar respostas obsoletas. Cards na Home, Alertas e ofertas de termos priorizam os campos extraídos; o modal mantém a mensagem original.

Jobs na fila ou em andamento podem ser cancelados com autenticação e CSRF. Um job na fila cancela imediatamente. No lote em andamento, a chamada já enviada termina, mas sua resposta é descartada e as ofertas restantes são canceladas.

## Consequências

Ofertas novas podem gerar consumo de créditos automaticamente quando há provedor configurado. O texto integral enviado ao provedor pode conter dados privados; a interface avisa antes do processamento manual. Chamada em andamento não pode ser interrompida e ainda pode consumir créditos após cancelamento. Chaves ficam sem criptografia no SQLite do volume; não são renderizadas nem incluídas em logs, então volume e backups precisam ser protegidos. Bancos antigos podem manter uma coluna `description` sem uso, preservada para evitar rebuild destrutivo; extrator e cards não a leem nem exibem. Integração real e tarifas não foram verificadas. O worker pressupõe uma única instância conforme o contrato de implantação.
