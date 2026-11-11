# ADR-0010: Observabilidade e métricas acumuladas dos jobs de IA

## Contexto

Os jobs guardavam tentativas concluídas, mas a página não identificava a etapa corrente. Falhas inesperadas fora do tratamento de cada item podiam encerrar um worker e deixar o job como `running`. Apagar jobs também apagava as tentativas, tornando-as inadequadas como fonte permanente de métricas.

## Decisão

Registrar logs de ciclo de vida do worker sem texto da oferta nem chaves; gravar etapa e horário da atualização no item em processamento; capturar exceções do worker com stack trace, finalizar o job como falho e manter o worker disponível. A interface consulta status e métricas a cada 2 segundos.

Persistir um rollup aditivo em SQLite por provedor, modelo, resultado e categoria fixa de falha. Atualizar rollup e tentativa na mesma transação. Mostrar contagens, taxas sobre chamadas concluídas e tempo médio por chamada; excluir cancelamentos, itens pulados e marcadores de retry. Preservar o rollup quando jobs e tentativas forem limpos. Na migração, importar tentativas existentes uma vez e identificar falhas antigas como `legacy`.

## Consequências

A tela distingue fila, oferta e etapa atual; uma etapa com tempo crescente indica onde a atividade parou, e erros inesperados deixam stack trace no log da aplicação. Métricas ficam disponíveis ao longo da vida do banco, mesmo após limpar histórico; falhas são categorizáveis sem registrar resposta privada do provedor. O tempo médio considera somente chamadas concluídas (`succeeded` e `failed`) e as taxas são acumuladas, sem janela temporal.

A categoria não substitui o detalhe textual da tentativa. Erros de infraestrutura que impedem acesso ao SQLite podem ainda impedir a gravação do estado terminal; o stack trace no log da aplicação é a evidência nesses casos.
