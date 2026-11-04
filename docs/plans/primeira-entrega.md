# Primeira entrega

Data: 2026-11-04. Estado: implementação inicial concluída. Distribuição inicial: release `v0.0.1` e imagem `ghcr.io/rodrigomescua/murktelegot:0.0.1`, somente AMD64.

## Escopo e aceite

- [x] Painel protegido e conexão pela conta pessoal, incluindo verificação em duas etapas; login real confirmado pelo usuário.
- [x] Seleção de grupos/canais com busca e seleção em lote; somente fontes selecionadas são armazenadas.
- [x] Regras por palavras-chave, ofertas unificadas e alertas no painel, com estado de leitura.
- [x] Compose de imagem pronta, variáveis no arquivo e dados em volume; script e testes locais sem Docker.
- [x] Workflow versionado para testes e publicação GHCR em release estável, documentação inicial e instruções de recuperação.

## Entrega Git

Repositório alvo: `rodrigomescua/MurkTelegot`, branch `main`, inicialmente privado. O primeiro commit inclui código, testes, configuração e documentação; exclui dados, credenciais, ambiente virtual e sessão Telegram. A confirmação do commit e push pertence ao histórico Git e à memória da tarefa.

## Verificação e limites

Consulte [verificação](../verificacao.md) para comandos e evidências. O workflow existe, mas a imagem só poderá ser considerada entregue após execução bem-sucedida da publicação de uma release. Monitoramento contínuo em grupos reais e carga de produção não foram validados automaticamente.
