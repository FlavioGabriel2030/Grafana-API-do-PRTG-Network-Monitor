"""Modo demonstração (TOPO_DEMO=1): finge ser o PRTG com dados fictícios.

Serve para ver as telas funcionando sem ter um PRTG e para tirar prints sem expor dados reais.
Responde só ao que o servidor usa: table.json (groups, devices, sensors) e historicdata.csv.
Os valores variam um pouco a cada coleta, para a tela ter vida.
"""
import json, math, random, time
from datetime import datetime, timedelta

UP, AVISO, FORA, PAUSADO = 3, 4, 5, 7
STATUS = {UP: 'Ativo', AVISO: 'Aviso', FORA: 'Fora do ar', PAUSADO: 'Pausado'}

# tempo de resposta "típico" por item da config de exemplo (ms); links usam Mbit/s
BASE_MS = {'soea': 85, 'cpa': 22, 'fiscalizacao': 120, 'sei': 210, 'drupal': 4, 'banco_soea': 3, 'lai': 9, 'integradores': 2, 'normativos': 35, 'plenaria': 70, 'ged': 180, 'sic': 260, 'backup': 420, 'site': 95, 'consulta': 40, 'osticket': 140, 'virtual': 25, 'f5': 8, 'fortigate': 3, 'vpn': 6,
           'core1': 2, 'core2': 1, 'dns': 1}
# ocorrências inventadas para a lista "Ocorrências em aberto"
EXTRAS = [  # (device, sensor, status, mensagem, valor)
    ('srv-arquivos-01', 'Disk Free: D:\\', AVISO, 'Abaixo de 10% livre', '8 %'),
    ('srv-app-02', 'Memory', AVISO, 'Memória disponível baixa', '12 %'),
    ('srv-app-02', 'Windows Updates Status', AVISO, '14 atualizações pendentes', '14 #'),
    ('www.exemplo.org', 'Sensor do certificado SSL', AVISO, 'Vence em 21 dias', '21 dias'),
    ('consulta.exemplo.org', 'Verificação de segurança SSL', AVISO, 'TLS 1.0 habilitado', ''),
    ('impressora-3andar', 'Ping', FORA, 'Destination host unreachable', ''),
]


def _id_hash(s):
    return sum(ord(c) * (i + 1) for i, c in enumerate(str(s)))


def _onda(sid, amplitude):
    """Variação suave no tempo, diferente por sensor."""
    t = time.time() / 60
    return 1 + amplitude * math.sin(t / 3 + _id_hash(sid) % 7) + random.uniform(-amplitude, amplitude) / 3


def _montar(config):
    grupos = [{'objid': 0, 'name': 'Raiz', 'parentid': -1, 'position_raw': 0},
              {'objid': 50, 'name': 'Infraestrutura', 'parentid': 0, 'position_raw': 1},
              {'objid': 60, 'name': 'Bancos de dados', 'parentid': 0, 'position_raw': 2}]
    devices, sensores, prox_dev = [], [], [500]

    def device(nome, host, pai=50, st=UP):
        prox_dev[0] += 1
        devices.append({'objid': prox_dev[0], 'name': nome, 'host': host, 'parentid': pai, 'status_raw': st,
                        'tags': 'demo', 'position_raw': prox_dev[0]})
        return prox_dev[0]

    def sensor(sid, dev, nome, valor, st=UP, msg='OK', tipo='http'):
        sensores.append({'objid': sid, 'parentid': dev, 'name': nome, 'status_raw': st, 'message_raw': msg,
                         'lastvalue': valor, 'lastvalue_raw': None, 'priority_raw': 3, 'tags': 'demo', 'type_raw': tipo})

    for i, n in enumerate(config.get('nos', [])):
        ids = n.get('sensores', [])
        if not ids:
            continue
        dev = device(n.get('sub') or n['rotulo'], f'10.0.{i}.10')
        for sid in ids:
            if n.get('capacidadeMbit'):
                mb = 0.4 if 'backup' in n['id'] else 420 * _onda(sid, .35)
                sensor(sid, dev, 'Tráfego total', f'{mb:.1f} Mbit/s'.replace('.', ','), tipo='snmptraffic')
            elif n['id'] in ('core1', 'core2', 'dns', 'fortigate', 'vpn', 'f5'):
                st = AVISO if n['id'] == 'core1' else UP
                sensor(sid, dev, 'Ping', f"{max(1, round(BASE_MS.get(n['id'], 2) * _onda(sid, .3)))} ms", st,
                       'CPU acima de 80%' if st == AVISO else 'OK', 'ping')
            else:
                ms = BASE_MS.get(n['id'], 60) * _onda(sid, .25)
                sensor(sid, dev, 'Robô sentinela: página carregou', f'{round(ms)} ms')
    for j in range(3):  # o item "Bancos de dados" soma um grupo inteiro
        dev = device(f'banco-{j + 1:02d}', f'10.0.60.{j + 10}', pai=60)
        sensor(3000 + j, dev, 'Ping', f'{2 + j} ms', tipo='ping')
        sensor(3100 + j, dev, 'Disk Free', '41 %', AVISO if j == 2 else UP, 'Espaço baixo' if j == 2 else 'OK', 'wmidiskspace')
    devs_extra = {}
    for k, (dnome, snome, st, msg, val) in enumerate(EXTRAS):
        if dnome not in devs_extra:
            devs_extra[dnome] = device(dnome, f'10.0.90.{len(devs_extra) + 10}')
        sensor(4000 + k, devs_extra[dnome], snome, val, st, msg, 'outro')
    sensor(2999, device('srv-legado', '10.0.90.99'), 'Ping', '', FORA, 'Máquina desligada (já registrado)', 'ping')
    return grupos, devices, sensores


def _historico(sid):
    """CSV no formato do PRTG: 6 h em pontos de 10 min, com um pico no meio."""
    fim = datetime.now()
    linhas = ['"Data Hora","Data Hora(RAW)","Tempo de carregamento(ms)","Tempo de carregamento(RAW)"']
    base = 40 + _id_hash(sid) % 80
    for i in range(36):
        t = fim - timedelta(minutes=10 * (35 - i))
        v = base * (1 + .15 * math.sin(i / 4) + (1.8 if i == 24 else 0) + random.uniform(-.08, .08))
        linhas.append(f'"{t:%d/%m/%Y %H:%M:%S}","{t.timestamp():.0f}","{v:.0f} ms","{v:.1f}"')
    return '\n'.join(linhas).encode('utf-8')


def responder(caminho_query, carregar_config):
    caminho, _, query = caminho_query.partition('?')
    params = dict(p.split('=', 1) for p in query.split('&') if '=' in p)
    if caminho.endswith('/historicdata.csv'):
        return 200, 'text/csv; charset=utf-8', _historico(params.get('id', '0'))
    if caminho.endswith('/table.json'):
        grupos, devices, sensores = _montar(carregar_config())
        conteudo = params.get('content', '')
        dados = {'groups': grupos, 'devices': devices, 'sensors': sensores}.get(conteudo, [])
        filtro = params.get('filter_objid')
        if filtro:
            dados = [x for x in dados if str(x['objid']) == filtro]
        for x in dados:  # o PRTG devolve status em texto também
            if 'status_raw' in x:
                x['status'] = STATUS.get(x['status_raw'], '')
        return 200, 'application/json', json.dumps({'prtg-version': 'demo', conteudo: dados}, ensure_ascii=False).encode('utf-8')
    return 404, 'text/plain; charset=utf-8', b'Modo demo: endpoint nao simulado'
