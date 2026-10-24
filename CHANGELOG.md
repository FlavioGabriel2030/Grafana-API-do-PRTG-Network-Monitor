# Histórico de mudanças

## V2 (outubro/2026)
- **Topologia viva:** servidor Python sem dependências que lê o PRTG em segundo plano; a chave nunca vai para o navegador.
- **Intermediário Grafana → PRTG:** fila de 4 consultas, novas tentativas em 4xx/5xx/timeout e cache (histórico 300 s, demais 30 s). Fim dos erros 401/400 intermitentes.
- **Telas de TV:** Fluxo (tráfego animado), Mosaico (colmeia) e playlist automática.
- **Fluxo:** cor e velocidade pela mesma escala logarítmica de tempo de resposta; barra de informações fixa; lista "Ocorrências em aberto" filtrada.
- **Sincronização:** telas recarregam sozinhas quando o servidor muda de versão ou o login expira; aviso de dados atrasados.
- **Modo demonstração** (`TOPO_DEMO=1`) com dados fictícios e prints em `docs/prints/`.
- **Operação:** vigia que reinicia o servidor; deploy com `docker compose`.

## V1 (julho/2026)
- Painéis do Grafana lendo a API do PRTG pelo plugin Infinity (CSV/JSON).
- Autenticação por Chave de API somente leitura no datasource.
- Script Python + SQLite (descontinuado; ver `v1-script-python-db/`).
