# Identidade visual — MurkTelegot

Redesign com etiqueta de oferta como silhueta principal e avião de papel integrado em referência ao Telegram, sem radar ou bloco quadrado de fundo. Cores: azul `#2AABEE` e branco `#FFFFFF`. A marca horizontal combina “Murk” em branco e “Telegot” em azul, com tipografia de peso forte, pensada para superfícies escuras. Os PNGs têm fundo transparente. Esta revisão substitui as propostas anteriores nos mesmos arquivos; o painel usa a mesma identidade azul/branca sobre fundos escuros azulados.

- [Logo horizontal em SVG](murktelegot-logo/logo.svg): vetor escalável, com nome e fonte genérica Helvetica Neue/Arial/sans-serif.
- [Ícone quadrado em SVG](murktelegot-logo/logo-icon.svg): símbolo sem texto para avatar e favicon.
- [Logo PNG](murktelegot-logo/logo.png): 1600 px de largura; [ícone PNG](murktelegot-logo/logo-icon.png): 1024 × 1024 px.
- [Pacote ZIP](murktelegot-logo.zip): os dois SVGs e os dois PNGs.

Os SVGs são a fonte original; PNGs foram renderizados diretamente deles com CairoSVG. Não há imagens externas, scripts, fontes remotas, gradientes ou sombras. Cada SVG possui título acessível e `viewBox` sem dimensões fixas. A tipografia pode variar conforme as fontes instaladas no sistema que abre o SVG.

Este pacote contém a identidade visual aprovada pelo usuário. O painel usa o logo no cabeçalho e o ícone no favicon e no estado vazio. Os arquivos canônicos são servidos em `/brand/` por FastAPI e incluídos na imagem pelo Dockerfile. A integração é distribuída a partir da versão `0.0.2`; a versão `0.0.1` não a inclui. Para revisar o desenho, altere o SVG, rasterize novamente e atualize o ZIP para manter os formatos coerentes.
