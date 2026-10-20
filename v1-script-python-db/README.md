# 🕰️ Versão 1.0 (Legado) - Extração via Python e SQLite

Esta pasta contém a primeira versão da arquitetura do projeto de monitoramento.

## 📌 Sobre o Script
O arquivo `extrator_prtg.py` foi desenvolvido em Python para realizar requisições automáticas e seguras à API REST do PRTG Network Monitor. Ele extrai as métricas dos sensores (status, valores, dispositivos) e as armazena em um banco de dados local **SQLite**.

## 🛡️ Boas Práticas Aplicadas
* **Segurança:** Utilização da biblioteca `python-dotenv` para ocultar senhas, passhashes e IPs do código fonte.
* **Resiliência:** Tratamento de exceções (`try/except`) para garantir estabilidade em falhas de comunicação com a rede.

## ⚙️ Como testar localmente
1. Renomeie o arquivo `.env.example` para `.env` e preencha com as credenciais do seu servidor PRTG.
2. Instale as dependências necessárias: `pip install requests python-dotenv`
3. Execute o extrator: `python extrator_prtg.py`

## 📉 Por que esta versão foi descontinuada
* **Crescimento sem limite:** Rodando a cada 1 minuto, o script grava uma linha por sensor (cerca de 1.400 sensores, ou ~2 milhões de linhas por dia) e não tem rotina de limpeza. Em produção, o arquivo `.db` passou de **18 GB** em cerca de 3 meses, e as consultas do Grafana ficaram cada vez mais lentas.
* **Unidades misturadas:** O campo `lastvalue` do PRTG vem formatado como texto (`850 kbit/s`, `12 Mbit/s`, `35 %`). Remover a unidade com `REPLACE` no SQL faz `kbit/s` e `Mbit/s` virarem o mesmo número, e os gráficos de tráfego ficam errados. A API `historicdata` tem colunas `(RAW)` com o valor numérico puro, e foi isso que resolveu o problema na V2.
* **Dado duplicado:** O PRTG já guarda o histórico de todos os sensores. Copiar tudo para outro banco só aumentava o consumo de disco.

> **⚠️ Nota de Evolução:** Esta arquitetura cumpriu seu propósito, mas foi **descontinuada e substituída pela Versão 2.0** (documentada na raiz deste repositório). A versão atual conecta o Grafana diretamente à API do PRTG, entregando dados em tempo real e zerando os custos e a latência de um banco de dados intermediário.
