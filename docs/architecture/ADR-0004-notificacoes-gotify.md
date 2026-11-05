# ADR-0004 — Notificações Gotify

## Contexto

O painel já registra alertas para palavras cadastradas. O usuário precisa receber esses alertas em um servidor Gotify escolhido por ele.

## Decisão

A URL, o token da aplicação e o estado de ativação ficam no SQLite no volume existente, em tabela aditiva. A tela autenticada configura, remove e testa a integração sem revelar o token salvo. Eventos e atualizações manuais tentam enviar ao Gotify o texto e o link quando uma oferta passa a ter alerta; mensagens repetidas não enviam novamente enquanto a oferta já possuir alerta. Ofertas ignoradas continuam gerando alertas e notificações. O envio usa Markdown com a indicação de conteúdo do Gotify, converte formatação e links seguros das entidades Telegram, mantém spoilers ocultos e indica mídias disponíveis no Telegram. Usa POST, token em cabeçalho, timeout e não segue redirecionamentos.

## Consequências

A renderização varia conforme o cliente Gotify; mídias não são anexadas e algumas entidades do Telegram não têm equivalente em Markdown. O token fica em texto legível no banco e seus backups exigem proteção. A entrega é uma tentativa, sem fila persistente ou repetição automática; falhas aparecem no log sem segredos e o alerta continua disponível no painel. Uma versão anterior ignora a tabela nova; proteger o volume também no rollback. Comunicação remota deve usar HTTPS.
