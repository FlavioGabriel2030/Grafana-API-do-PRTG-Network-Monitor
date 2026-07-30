import os
import requests
import sqlite3
import urllib3
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# Desativa o aviso de "certificado de segurança inválido" no terminal (já que usamos IP direto)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. CONFIGURAÇÕES DO PRTG
# ==========================================
PRTG_IP = os.getenv("PRTG_IP")
USERNAME = os.getenv("PRTG_USER")
PASSHASH = os.getenv("PRTG_PASS")

# A montagem da URL continua igualzinha, ela vai usar a variável PRTG_IP que veio do cofre!
API_URL = f"https://{PRTG_IP}/api/table.json?content=sensors&columns=objid,sensor,device,status,lastvalue&username={USERNAME}&passhash={PASSHASH}&count=*"

# ==========================================
# 2. CONFIGURAÇÕES DO BANCO DE DADOS
# ==========================================
NOME_BANCO = r"C:\Projeto_PRTG\dados_prtg.db"

def inicializar_banco():
    """Cria o banco de dados e a tabela caso ainda não existam."""
    conexao = sqlite3.connect(NOME_BANCO)
    cursor = conexao.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metricas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            horario DATETIME,
            id_sensor TEXT,
            equipamento TEXT,
            nome_sensor TEXT,
            status TEXT,
            valor TEXT
        )
    ''')
    conexao.commit()
    conexao.close()

# ==========================================
# 3. EXTRAÇÃO E CARGA (A Ponte)
# ==========================================
def rodar_extracao():
    horario_agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{horario_agora}] Iniciando coleta na API do PRTG...")

    try:
        # Extração (GET na API do PRTG)
        resposta = requests.get(API_URL, verify=False, timeout=15)
        resposta.raise_for_status() # Verifica se a conexão falhou
        
        # Transformação (Convertendo o texto em um dicionário Python)
        dados = resposta.json()
        sensores = dados.get("sensors", [])

        if not sensores:
            print("⚠️ Acesso bem-sucedido, mas nenhum sensor retornou. Verifique as permissões do usuário.")
            return

        # Carga (Conectando no banco para inserir os dados)
        conexao = sqlite3.connect(NOME_BANCO)
        cursor = conexao.cursor()
        
        linhas_inseridas = 0

        # Loop passando por cada sensor da rede e salvando no SQLite
        for s in sensores:
            id_sensor = str(s.get("objid", ""))
            equipamento = s.get("device", "Desconhecido")
            nome_sensor = s.get("sensor", "Desconhecido")
            status = s.get("status", "")
            valor = str(s.get("lastvalue", "0"))

            cursor.execute('''
                INSERT INTO metricas (horario, id_sensor, equipamento, nome_sensor, status, valor)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (horario_agora, id_sensor, equipamento, nome_sensor, status, valor))
            
            linhas_inseridas += 1

        conexao.commit()
        conexao.close()
        print(f"[{horario_agora}] Sucesso! {linhas_inseridas} sensores armazenados em {NOME_BANCO}.")

    except Exception as erro:
        print(f"❌ Falha crítica na comunicação com o PRTG: {erro}")

# ==========================================
# INÍCIO DO SCRIPT
# ==========================================
if __name__ == "__main__":
    inicializar_banco()
    rodar_extracao()
