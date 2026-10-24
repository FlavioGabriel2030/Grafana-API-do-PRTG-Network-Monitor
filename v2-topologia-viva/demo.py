"""Modo demonstração (TOPO_DEMO=1): finge ser o PRTG com dados fictícios.

Serve para ver as telas funcionando sem ter um PRTG e para tirar prints sem expor dados reais.
Responde ao que o servidor e os painéis de demonstração do Grafana usam:
table.json, status.json, historicdata.csv e historicdata.json.
Os valores variam um pouco a cada coleta, para a tela ter vida.
"""
import json, math, random, time, urllib.parse
from datetime import datetime, timedelta

UP, AVISO, FORA, PAUSADO = 3, 4, 5, 7
STATUS = {UP: 'OK', AVISO: 'Aviso', FORA: 'Inativo', PAUSADO: 'Pausado'}

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


def _ole(t):
    """Data RAW do PRTG: dias desde 30/12/1899, em UTC (o texto ao lado fica no horário local)."""
    return t.timestamp() / 86400 + 25569
CANAIS_TRAFEGO = ['Tráfego total (velocidade)', 'Traffic Total (velocidade)', 'Tráfego de entrada (velocidade)', 'Tráfego de saída (velocidade)']
CANAIS_HTTP = ['Tempo de carregamento', 'Loading Time', 'Tempo de inoperância', 'Downtime']


def _data(txt, padrao):
    try:
        return datetime.strptime(txt, '%Y-%m-%d-%H-%M-%S')
    except (TypeError, ValueError):
        return padrao


def _serie(sid, inicio, fim, avg):
    """Pontos (instante, valores por canal) entre início e fim. Tráfego em bytes/s, tempo em ms, inoperância em %."""
    passo = max(60, avg or 60)
    n = max(2, min(1500, int((fim - inicio).total_seconds() // passo)))
    passo = (fim - inicio).total_seconds() / n
    h = _id_hash(sid)
    escala = 1 + h % 9                       # cada sensor com um tamanho diferente
    for i in range(n + 1):
        t = inicio + timedelta(seconds=passo * i)
        dia = math.sin((t.hour + t.minute / 60 - 6) / 24 * 2 * math.pi)  # pico no meio do dia
        ruido = random.uniform(.85, 1.15)
        mbit = max(.2, (18 + 50 * max(0, dia)) * escala * ruido)
        ms = (40 + h % 120) * (1 + .25 * max(0, dia)) * ruido + (400 if random.random() < .01 else 0)
        fora = 0.0 if random.random() > .04 else round(random.uniform(.1, 1.5), 2)
        bps = mbit * 1e6 / 8
        yield t, {CANAIS_TRAFEGO[0]: bps, CANAIS_TRAFEGO[1]: bps, CANAIS_TRAFEGO[2]: bps * .68, CANAIS_TRAFEGO[3]: bps * .32,
                  CANAIS_HTTP[0]: ms, CANAIS_HTTP[1]: ms, CANAIS_HTTP[2]: fora, CANAIS_HTTP[3]: fora}


def _hist_csv(sid, inicio, fim, avg):
    canais = CANAIS_TRAFEGO + CANAIS_HTTP
    cab = ['Data e hora', 'Data e hora(RAW)'] + [x for c in canais for x in (c, c + '(RAW)')]
    linhas = [','.join(f'"{c}"' for c in cab)]
    for t, v in _serie(sid, inicio, fim, avg):
        cel = [t.strftime('%d/%m/%Y %H:%M:%S'), f'{_ole(t):.10f}']
        for c in canais:
            cel += [f'{v[c]:.2f}', f'{v[c]:.4f}']
        linhas.append(','.join(f'"{c}"' for c in cel))
    return '\n'.join(linhas).encode('utf-8')


def _hist_json(sid, inicio, fim, avg):
    itens = []
    for t, v in _serie(sid, inicio, fim, avg):
        bps = v[CANAIS_TRAFEGO[0]]  # o JSON do PRTG traz só o canal principal: value / value_raw
        it = {'datetime': t.strftime('%d/%m/%Y %H:%M:%S'), 'datetime_raw': _ole(t),
              'value': f'{bps * 8 / 1e6:.0f} Mbit/s', 'value_raw': round(bps, 4), 'coverage': '100 %', 'coverage_raw': 10000}
        itens.append(it)
    return json.dumps({'prtg-version': 'demo', 'treesize': len(itens), 'histdata': itens}, ensure_ascii=False).encode('utf-8')


def _status():
    return json.dumps({'Alarms': '3', 'AckAlarms': '1', 'WarnSens': '6', 'UpSens': '412', 'PausedSens': '9',
                       'UnusualSens': '4', 'TotalSens': 435, 'Version': 'demo', 'object': {}}).encode('utf-8')


def _linha_tabela(x, devs, grupos, n):
    """Acrescenta os campos que os painéis pedem (device, group, sensor, *_raw...)."""
    dev = devs.get(x['parentid'], {})
    st = x['status_raw']
    try:
        ms = float(str(x['lastvalue']).split()[0].replace(',', '.'))
    except (ValueError, IndexError):
        ms = ''
    up = 99.9 - (_id_hash(x['objid']) % 9) / 10  # o PRTG manda uptime_raw = % x 10000
    return dict(x, objid_raw=x['objid'], device=dev.get('name', f'Aplicação {n}'), sensor=x['name'],
                group=grupos.get(dev.get('parentid'), 'Serviços ao público'), status=STATUS.get(st, ''),
                lastvalue_raw=ms, uptime=f'{up:.1f} %', uptime_raw=round(up * 10000),
                downtimesince='12 min' if st == FORA else '', message=x.get('message_raw', ''))


def responder(caminho_query, carregar_config):
    caminho, _, query = caminho_query.partition('?')
    multi = urllib.parse.parse_qs(query)
    params = {k: v[-1] for k, v in multi.items()}
    agora = datetime.now()
    ini, fim = _data(params.get('sdate'), agora - timedelta(hours=6)), _data(params.get('edate'), agora)
    avg = int(params.get('avg', '0') or 0)
    if caminho.endswith('/historicdata.csv'):
        return 200, 'text/csv; charset=utf-8', _hist_csv(params.get('id', '0'), ini, fim, avg)
    if caminho.endswith('/historicdata.json'):
        return 200, 'application/json', _hist_json(params.get('id', '0'), ini, fim, avg)
    if caminho.endswith('/status.json'):
        return 200, 'application/json', _status()
    if caminho.endswith('/table.json'):
        grupos, devices, sensores = _montar(carregar_config())
        conteudo = params.get('content', '')
        dados = {'groups': grupos, 'devices': devices, 'sensors': sensores}.get(conteudo, [])
        if conteudo == 'sensors':
            devs = {d['objid']: d for d in devices}
            gnomes = {g['objid']: g['name'] for g in grupos}
            ids = [int(i) for i in multi.get('filter_objid', []) if i.isdigit()]
            if ids:  # os painéis pedem IDs do PRTG real: devolve um sensor fictício para cada um
                por_id = {x['objid']: x for x in dados}
                dados = [por_id.get(i) or {'objid': i, 'parentid': -1, 'name': 'Robô sentinela: página carregou',
                                           'status_raw': UP, 'message_raw': 'OK', 'lastvalue': f'{40 + _id_hash(i) % 160} ms',
                                           'tags': 'demo', 'type_raw': 'http'} for i in ids]
            sts = [int(v) for v in multi.get('filter_status', []) if v.isdigit()]
            if sts:
                dados = [x for x in dados if x['status_raw'] in sts]
            dados = [_linha_tabela(x, devs, gnomes, n + 1) for n, x in enumerate(dados)]
        for x in dados:  # o PRTG devolve status em texto também
            if 'status_raw' in x and 'status' not in x:
                x['status'] = STATUS.get(x['status_raw'], '')
        return 200, 'application/json', json.dumps({'prtg-version': 'demo', conteudo: dados}, ensure_ascii=False).encode('utf-8')
    return 404, 'text/plain; charset=utf-8', b'Modo demo: endpoint nao simulado'
