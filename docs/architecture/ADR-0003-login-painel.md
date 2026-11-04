# ADR-0003 — Login do painel com sessão

## Contexto

O HTTP Basic abre o diálogo de autenticação do navegador, que não segue o visual do painel e não oferece saída pelo app.

## Decisão

Usar página de login com as credenciais `APP_USER` e `APP_PASSWORD` existentes. Após validar as credenciais e o CSRF, o servidor gera uma sessão aleatória em memória e envia apenas seu identificador em cookie HttpOnly, SameSite estrito e Secure quando acessado via HTTPS. A sessão expira após 12 horas, é invalidada na saída e não sobrevive ao reinício. As rotas privadas continuam protegidas e mutações continuam exigindo CSRF. O HTTP Basic deixa de autenticar.

## Consequências

O painel tem login e saída integrados; um reinício exige novo login. A sessão em memória mantém a restrição de uma única instância. Use HTTPS ou túnel SSH para acesso remoto; o cookie não substitui o transporte seguro. A sessão do painel é independente da sessão Telegram persistida no volume.
