# ADR-0011 — WAL e espera de locks SQLite

## Contexto

Em produção, leituras HTTP e claims de jobs falharam com `sqlite3.OperationalError: database is locked`. O app usa conexões SQLite independentes em threads e concorrência de escrita entre eventos Telegram, rotas, manutenção e workers. O journal padrão pode bloquear leitores durante commits de escrita.

## Decisão

Ativar `journal_mode=WAL` ao inicializar cada `Store` e usar timeout de 30 segundos nas conexões. Manter as transações de escrita existentes, curtas e atômicas.

## Consequências

Leitores podem continuar usando o snapshot anterior enquanto um escritor está ativo. SQLite ainda serializa escritores; disputas mais longas que o timeout continuam falhando. WAL cria arquivos auxiliares `-wal` e `-shm`, portanto backups devem parar o app e copiar o diretório de dados completo. WAL é apropriado para o volume local de uma única instância; não usar o banco em filesystem de rede sem validar os requisitos de locking do SQLite.
