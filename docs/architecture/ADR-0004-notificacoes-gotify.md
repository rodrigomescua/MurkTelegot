# ADR-0004 — Notificações Gotify

## Contexto

O painel já registra alertas para palavras cadastradas. O usuário precisa receber esses alertas em um servidor Gotify escolhido por ele.

## Decisão

A URL, o token da aplicação e o estado de ativação ficam no SQLite no volume existente, em tabela aditiva. A tela autenticada configura, remove e testa a integração sem revelar o token salvo. Eventos e atualizações manuais tentam enviar ao Gotify o texto e o link quando uma oferta passa a ter alerta; mensagens repetidas não enviam novamente enquanto a oferta já possuir alerta. Regras novas também notificam correspondências retroativas, uma vez por oferta/álbum. Ofertas ignoradas continuam gerando alertas e notificações. O envio usa Markdown com a indicação de conteúdo do Gotify, converte formatação e links seguros das entidades Telegram e mantém spoilers ocultos. Quando `APP_PUBLIC_URL` configura origem HTTPS pública, a notificação inclui miniatura por link HMAC assinado, válido por 24 horas; o acesso à imagem dispensa login e fica disponível a quem possuir o link. Usa POST, token em cabeçalho, timeout e não segue redirecionamentos.

## Consequências

A renderização varia conforme o cliente Gotify; imagens privadas exigem `APP_PUBLIC_URL` HTTPS acessível pelo cliente. Links são bearer temporários; proxies podem registrá-los, então não compartilhe fora do público pretendido. O app filtra URLs assinadas dos logs Uvicorn. Sem imagem ou para spoilers, a notificação mantém texto e link Telegram. O token e a chave HMAC ficam em texto legível no banco; proteja o volume e backups. A entrega é uma tentativa, sem fila persistente ou repetição automática; falhas aparecem no log sem segredos e o alerta continua disponível no painel. Comunicação remota deve usar HTTPS.
