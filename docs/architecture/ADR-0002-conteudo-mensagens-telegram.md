# ADR-0002: Conteúdo original e mídia das mensagens Telegram

- Status: aceita
- Data: 2026-11-04
- Complementa a ADR-0001 e substitui sua decisão de não baixar mídias.

## Contexto

O usuário precisa ver ofertas próximas à apresentação do Telegram. A versão anterior guardava somente texto simples e descartava mensagens de mídia sem legenda. As entidades, o destino de links embutidos e os metadados perdidos não podem ser reconstruídos a partir do texto armazenado.

## Decisão

Persistir o JSON original da mensagem junto ao texto simples, usado por busca e alertas; adicionar o identificador do álbum. Uma migração aditiva e idempotente faz snapshot SQLite antes de alterar banco existente, sem remover ofertas, regras, alertas ou leitura. Dados antigos permanecem legíveis e podem ser recuperados individualmente no Telegram enquanto disponíveis. A recuperação inclui mensagens vizinhas do mesmo álbum e exige grupo selecionado.

Converter entidades de texto em HTML seguro, respeitando offsets UTF-16 e escapando conteúdo e URLs. Fotos, vídeos, áudios e anexos são recuperados do Telegram sob demanda por uma rota autenticada e armazenados em cache no volume. Downloads usam arquivos temporários e publicação atômica, dois slots simultâneos, limite de tempo e reserva de espaço em disco. Tipos não exibíveis são baixados como anexos, não interpretados como HTML. Mídia temporária não é baixada.

Mensagens de um álbum são mostradas juntas, inclusive quando apenas uma parte corresponde à busca ou regra. Marcar o álbum lido marca seus componentes. Prévia de link, enquete, resposta, encaminhamento, reações e botões são apresentados quando os dados existem; ações não suportadas devem ser feitas no Telegram.

## Consequências

O volume contém mais dados privados e pode crescer com o cache. Uma imagem ainda não acessada depende de sua disponibilidade no Telegram; uma cópia já acessada permanece no cache. Formatos especiais, animações, votos, ações de bot e atualizações de contadores podem não reproduzir toda a experiência nativa; metadados são preservados e a mensagem original continua acessível quando houver link.

O backup automático `offers.db.before-rich-messages.db` não substitui o backup integral do volume. Em rollback, preserve uma cópia do volume atual antes de restaurar imagem e backup anteriores; dados recebidos após o snapshot não constam nele. Veja [operação](../operacao.md).
