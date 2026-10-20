# 📊 Integração Avançada: Grafana + API do PRTG Network Monitor

## 🎯 Objetivo do Projeto
Este projeto documenta a construção de dashboards dinâmicos no Grafana utilizando dados extraídos diretamente da API do PRTG Network Monitor, sem a necessidade de bancos de dados intermediários. O foco principal foi contornar as limitações nativas de formatação e realizar cálculos matemáticos de tráfego de rede (VLANs, VPNs e Firewalls) em tempo real.

## 🛠️ Tecnologias e Ferramentas Utilizadas
* **Grafana:** Criação dos Dashboards e visualização de dados.
* **Infinity Datasource Plugin:** Plugin utilizado para ler e interpretar a API Rest/CSV.
* **PRTG Network Monitor:** Fonte central de coleta de dados (SNMP, WMI, Ping, HTTP).
* **Infraestrutura e Serviços Monitorados:** 
  * **FortiGate (NGFW):** Monitoramento de tráfego de borda, VPNs e roteamento de VLANs.
  * **F5 Networks (WAF/ADC):** Segurança de aplicação, health checks e Balanceamento de Carga.
  * **Switches Cisco:** Tráfego de LAN interna, Uplinks e consumo de portas físicas.
  * **Servidores Windows:** Saúde do SO (CPU, RAM, Pagefile, Discos) para serviços críticos como WSUS e Qlik Sense (In-Memory).
  * **Virtualização (VMware):** Status e saúde (Health) das Máquinas Virtuais.
  * **Serviços Web (IIS):** Monitoramento de Application Pools e tempos de resposta HTTP/HTTPS.


## 🔗 API e Autenticação (PRTG)
A integração consome os dados históricos no formato CSV e JSON, utilizando o *endpoint* de `historicdata` da API nativa do PRTG.
> **📚 Documentação Oficial:** A documentação interativa (e completa) da API do PRTG é hospedada localmente no próprio servidor da aplicação. Ela pode ser acessada adicionando `/api.htm` à URL base do seu servidor (Ex: `https://<IP-DO-SEU-PRTG>/api.htm`).
> ### 🔒 Estrutura da Requisição Segura
A autenticação **não fica na URL dos painéis**. Ela é configurada uma única vez no datasource Infinity, com uma **Chave de API somente leitura** do PRTG, que o Grafana guarda criptografada:

1. No PRTG: **Setup → Configurações da conta → Chaves de API → Adicionar** (nível de acesso: **Acesso de leitura**).
2. No Grafana: **Connections → Data sources → Infinity → Authentication**
   * **Auth type:** `API Key`
   * **Key:** `apitoken`
   * **Value:** a chave gerada no PRTG
   * **Add to:** `Query parameter`
   * **Allowed hosts:** `https://<IP-DO-SERVIDOR>`

Com isso, a URL usada nos painéis fica sem nenhuma credencial:

```https://<IP-DO-SERVIDOR>/api/historicdata.csv?id=<ID-DO-SENSOR>&avg=0&sdate=${__from:date:YYYY-MM-DD-HH-mm-ss}&edate=${__to:date:YYYY-MM-DD-HH-mm-ss}```

> **Por que não `username` + `passhash` na URL?** Qualquer pessoa com acesso de visualização ao painel consegue ler a URL da consulta (em *Inspect → Query*) e, com ela, o passhash da conta. Na Chave de API guardada no datasource, isso não acontece. Ela também pode ser revogada a qualquer momento sem trocar a senha de ninguém.

## 🏗️ Arquitetura da Solução
Para fazer as ferramentas conversarem de forma estável, foi desenvolvida uma "esteira de tratamento de dados" dentro do próprio Grafana.

1. **Extração via API (CSV):** Requisição `GET` gerando um CSV histórico com variáveis de tempo nativas do Grafana (`${__from:date:...}`).
2. **Parsing Nativo:** Renomeação das colunas direto na raiz (ex: `raw_045`) para evitar conflitos de variáveis criadas pelo Grafana (Letras A, B, C nas queries).
3. **Transformações (O Segredo da Estabilidade):**
   * `Convert field type`: Conversão forçada de Strings para `Time` (com formato de input em branco para evitar conflitos com datas nulas/traços) e numéricos para `Number`.
   * `Filter data by values`: Bloqueio de valores de tempo nulos (`Is not null`).
   * `Add field from calculation`: Multiplicação de dados brutos para conversão de bits/bytes usando a "Regra da Legenda" para referenciar as colunas corretas.
   * `Filter fields by name`: Limpeza final para exibir no painel apenas as colunas com os *Aliases* limpos e amigáveis.

## 🚨 Troubleshooting & Lições Aprendidas
Durante o desenvolvimento, mapeamos e resolvemos "armadilhas" comuns dessa integração:
* **Erro de Data Nula:** O PRTG exporta datas com traços (`YYYY-MM-DD`). Forçar barras (`DD/MM/YYYY`) no Grafana quebra a leitura, gerando tabelas vazias e impedindo qualquer cálculo matemático subsequente.
* **Conflito de Letras nas Queries:** O Grafana insere prefixos alfabéticos em múltiplas consultas. A matemática só funciona se a variável no cálculo referenciar exatamente o nome exibido na legenda final.
* **Idioma do PRTG:** Sensores automáticos puxam colunas em inglês (*Traffic Total*), enquanto sensores manuais/templates locais puxam em português (*Tráfego total*). Inspecionar o CSV bruto foi essencial para evitar falhas de leitura de colunas.
* **Chave de API no cabeçalho não funciona (PRTG 25.1):** O PRTG respondeu `401 Unauthorized` para `Authorization: Bearer <chave>` e só aceitou a chave como parâmetro `apitoken=` na URL. Por isso, no Infinity, a chave é enviada como *Query parameter*, e não como *Bearer token*.
* **Encoding ao automatizar pela API do Grafana:** No Windows PowerShell 5.1, `Invoke-RestMethod` lê o JSON do Grafana com a codificação errada e corrompe acentos e emojis dos títulos. Se o painel for salvo de volta assim, os textos ficam estragados. A leitura precisa decodificar a resposta explicitamente como UTF-8.

## 📸 Screenshots
<img width="1598" height="763" alt="Painel-1" src="https://github.com/user-attachments/assets/0ff30b46-8ca3-4902-b4b6-813eb599ba60" />
<img width="1663" height="834" alt="Painel-2" src="https://github.com/user-attachments/assets/61d13062-c4bd-4a4e-9e70-b5d1e4d73684" />


