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

> **⚠️ Nota de Evolução:** Esta arquitetura cumpriu seu propósito, mas foi **descontinuada e substituída pela Versão 2.0** (documentada na raiz deste repositório). A versão atual conecta o Grafana diretamente à API do PRTG, entregando dados em tempo real e zerando os custos e a latência de um banco de dados intermediário.
