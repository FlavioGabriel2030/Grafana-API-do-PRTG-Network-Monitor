"""Topologia viva da organização — servidor web.

Lê o PRTG em segundo plano e entrega a página e os dados. A chave do PRTG nunca vai para o navegador.

Configuração por variáveis de ambiente (é assim que roda em container), com padrões para o PC local:
  PRTG_URL            https://prtg.exemplo.local
  TOPO_PRTG_APIKEY    chave de LEITURA do PRTG (ou TOPO_PRTG_APIKEY_FILE com o caminho de um arquivo que a contém)
  GRAFANA_URL         http://localhost:3000   (usado só para checar se o Grafana está no ar)
  GRAFANA_PUBLICO     endereço do Grafana para os links da página (padrão: mesmo host da página, porta 3000)
  TOPO_BIND / TOPO_PORTA      0.0.0.0 / 8090
  TOPO_USUARIO / TOPO_SENHA_SHA256   login da página (ou o arquivo acesso.txt = usuario:sha256)
  TOPO_INTERVALO      segundos entre coletas (padrão 60)
  TOPO_DEMO=1         modo demonstração: dados fictícios, sem PRTG (ver demo.py)
  IPAM_CSV            exportação do phpIPAM (padrão ../ipam/ipam_servidores.csv)
"""
import base64, csv, gzip, hashlib, hmac, ipaddress, json, logging, os, re, socket, ssl, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PASTA = os.path.dirname(os.path.abspath(__file__))
PRTG = os.environ.get('PRTG_URL', 'https://prtg.exemplo.local').rstrip('/')
GRAFANA = os.environ.get('GRAFANA_URL', 'http://localhost:3000').rstrip('/')
GRAFANA_PUBLICO = os.environ.get('GRAFANA_PUBLICO', '')
BIND = os.environ.get('TOPO_BIND', '0.0.0.0')
PORTA = int(os.environ.get('TOPO_PORTA', '8090'))
INTERVALO = max(20, int(os.environ.get('TOPO_INTERVALO', '60')))
IPAM_CSV = os.environ.get('IPAM_CSV', os.path.join(PASTA, '..', 'ipam', 'ipam_servidores.csv'))
NOTA_LOCAL = os.environ.get('TOPO_NOTA', '')  # opcional: arquivo local com a chave (linha 4)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
log = logging.getLogger('topologia')
CTX = ssl._create_unverified_context()  # o PRTG usa certificado próprio
DEMO = os.environ.get('TOPO_DEMO') == '1'


def ler_chave():
    if DEMO:
        return 'demo'
    if os.environ.get('TOPO_PRTG_APIKEY'):
        return os.environ['TOPO_PRTG_APIKEY'].strip()
    arq = os.environ.get('TOPO_PRTG_APIKEY_FILE')
    if arq:
        return open(arq, encoding='utf-8-sig').read().strip()
    if os.path.exists(NOTA_LOCAL):
        return open(NOTA_LOCAL, encoding='utf-8-sig').read().splitlines()[3].strip()
    sys.exit('Defina TOPO_PRTG_APIKEY (chave de leitura do PRTG).')


def ler_login():
    if os.environ.get('TOPO_LOGIN') == '0' and BIND in ('127.0.0.1', 'localhost'):  # só para testes na própria máquina
        return None, None
    if os.environ.get('TOPO_USUARIO') and os.environ.get('TOPO_SENHA_SHA256'):
        return os.environ['TOPO_USUARIO'], os.environ['TOPO_SENHA_SHA256'].lower()
    arq = os.path.join(PASTA, 'acesso.txt')
    if os.path.exists(arq):
        u, h = open(arq, encoding='utf-8').read().strip().split(':', 1)
        return u, h.lower()
    return None, None


CHAVE = ler_chave()
USUARIO, HASH = ler_login()
if not USUARIO and BIND not in ('127.0.0.1', 'localhost'):
    sys.exit('Sem login configurado: defina TOPO_USUARIO e TOPO_SENHA_SHA256 ou use TOPO_BIND=127.0.0.1.')

estado = {'dados': None, 'json': None, 'gz': None, 'ok_em': 0, 'erro': None, 'falhas': 0,
          'config': None, 'config_mtime': 0, 'config_erro': None}
trava = threading.Lock()
_dns = {}  # cache host -> (ip, quando)


# ------------------------------------------------------------------ coleta
def baixar(url, timeout=60):
    with urllib.request.urlopen(url, context=CTX, timeout=timeout) as r:
        b = r.read()
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('cp1252')


# ------------------------------------------------------------------ intermediário PRTG (cache + fila)
# O PRTG recusa com 401 parte das consultas quando recebe muitas ao mesmo tempo (medido em 22/10:
# 1 de 20 em paralelo). Aqui todas as consultas ao PRTG passam por uma fila de no máximo
# PROXY_PARALELO, com nova tentativa em 401/5xx/timeout e cache por endereço.
PROXY_PARALELO = int(os.environ.get('TOPO_PROXY_PARALELO', '4'))
PROXY_TOKEN = os.environ.get('TOPO_PROXY_TOKEN', '')  # para o Grafana em outro host/container
PROXY_PERMITIDOS = ('/api/table.json', '/api/table.csv', '/api/table.xml', '/api/historicdata.csv', '/api/historicdata.json',
                    '/api/status.json', '/api/getsensordetails.json', '/api/sensortypesinuse.json')
fila_prtg = threading.BoundedSemaphore(PROXY_PARALELO)
_cache_px, _trava_px, _em_voo = {}, threading.Lock(), {}
px_stats = {'consultas': 0, 'cache': 0, 'novas_tentativas': 0, 'falhas': 0}


def ttl_de(caminho):
    return 300 if 'historicdata' in caminho else 30


def prtg_bruto(caminho_query, timeout=90):
    """Busca no PRTG passando pela fila, com até 3 tentativas. Devolve (status, tipo, corpo)."""
    if DEMO:
        import demo
        return demo.responder(caminho_query, carregar_config)
    url = f"{PRTG}{caminho_query}{'&' if '?' in caminho_query else '?'}apitoken={CHAVE}"
    ultimo = None
    for tentativa in range(3):
        with fila_prtg:
            try:
                with urllib.request.urlopen(url, context=CTX, timeout=timeout) as r:
                    return r.status, r.headers.get('Content-Type', 'application/octet-stream'), r.read()
            except urllib.error.HTTPError as e:
                ultimo = (e.code, 'text/plain; charset=utf-8', f'PRTG respondeu {e.code}'.encode())
                if e.code not in (400, 401, 429, 500, 502, 503, 504):  # 400 e 401 aparecem de forma passageira sob carga
                    return ultimo
            except Exception as e:
                ultimo = (504, 'text/plain; charset=utf-8', f'Sem resposta do PRTG ({e.__class__.__name__})'.encode())
        px_stats['novas_tentativas'] += 1
        time.sleep((0.5, 1.5, 3)[tentativa])
    px_stats['falhas'] += 1
    return ultimo


def proxy_prtg(caminho_query):
    """Cache + agrupamento: consultas iguais ao mesmo tempo viram uma só ida ao PRTG."""
    px_stats['consultas'] += 1
    agora = time.time()
    with _trava_px:
        c = _cache_px.get(caminho_query)
        if c and agora - c[0] < ttl_de(caminho_query):
            px_stats['cache'] += 1
            return c[1:]
        evento = _em_voo.get(caminho_query)
        dono = evento is None
        if dono:
            evento = _em_voo[caminho_query] = threading.Event()
    if not dono:
        evento.wait(120)
        with _trava_px:
            c = _cache_px.get(caminho_query)
        if c:
            px_stats['cache'] += 1
            return c[1:]
    try:
        resp = prtg_bruto(caminho_query)
        if resp[0] == 200:
            with _trava_px:
                _cache_px[caminho_query] = (time.time(),) + resp
                if len(_cache_px) > 800:  # descarta os mais antigos
                    for k in sorted(_cache_px, key=lambda k: _cache_px[k][0])[:200]:
                        _cache_px.pop(k, None)
        elif c := _cache_px.get(caminho_query):  # PRTG falhou: serve o último bom, mesmo vencido
            return c[1:]
        return resp
    finally:
        if dono:
            with _trava_px:
                _em_voo.pop(caminho_query, None)
            evento.set()


def tabela(conteudo, colunas):
    st, _, corpo = prtg_bruto(f'/api/table.json?content={conteudo}&count=50000&columns={colunas}')
    if st != 200:
        raise RuntimeError(f'PRTG {st} em table.json content={conteudo}')
    try:
        txt = corpo.decode('utf-8')
    except UnicodeDecodeError:
        txt = corpo.decode('cp1252')
    return json.loads(txt)[conteudo]


def grafana_ok():
    if DEMO:
        return True
    try:
        return json.loads(baixar(f'{GRAFANA}/api/health', 5)).get('database') == 'ok'
    except Exception:
        return False


def carregar_config():
    arq = os.path.join(PASTA, 'config.json')
    if DEMO and not os.path.exists(arq):
        arq = os.path.join(PASTA, 'config.exemplo.json')
    try:
        m = os.path.getmtime(arq)
        if m != estado['config_mtime']:
            with open(arq, encoding='utf-8') as f:
                estado['config'] = json.load(f)
            estado['config_mtime'], estado['config_erro'] = m, None
            log.info('config.json carregado')
    except Exception as e:  # mantém a última config boa
        estado['config_erro'] = f'config.json com erro ({e}); usando a versão anterior'
        log.error(estado['config_erro'])
    return estado['config'] or {}


def carregar_ipam():
    ipam = {}
    try:
        with open(IPAM_CSV, encoding='utf-8') as f:
            for r in csv.DictReader(f, delimiter=';'):
                ipam.setdefault(r['ip'], {'nome': r['hostname'], 'desc': r['descricao'], 'rede': r['subrede']})
    except OSError:
        pass
    return ipam


def resolver(host):
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    c = _dns.get(host)
    if c and time.time() - c[1] < 1800:
        return c[0]
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        ip = ''
    _dns[host] = (ip, time.time())
    return ip


def tokens(t):
    return {x for x in re.split(r'[\W_]+', t.lower()) if len(x) > 3 and x not in ('local', 'firewall', 'aplicacao', 'aplicação', 'org')}


def versao_telas():
    """Muda quando alguém edita as telas ou o config: os navegadores abertos recarregam sozinhos."""
    try:
        return str(int(max(os.path.getmtime(os.path.join(PASTA, n)) for n in ('index.html', 'mosaico.html', 'fluxo.html', 'config.json'))))
    except OSError:
        return ''


TIPOS_TEMPO = ('http', 'httpadvanced')  # robôs e sensores HTTP: os que medem tempo de carregamento


def ultimas_medicoes(sid, n=3):
    """Últimas n medições (canal principal, em ms) de um sensor, pelo histórico bruto dos últimos 40 min."""
    agora = time.localtime()  # o PRTG lê horário LOCAL
    f = lambda t: time.strftime('%Y-%m-%d-%H-%M-%S', t)
    st, _, corpo = prtg_bruto(f'/api/historicdata.csv?id={sid}&avg=0&sdate={f(time.localtime(time.time() - 2400))}&edate={f(agora)}', timeout=30)
    if st != 200:
        return []
    linhas = list(csv.reader(corpo.decode('utf-8', 'replace').splitlines()))
    if not linhas:
        return []
    cab = linhas[0]  # coluna do tempo pelo nome; sem ela, o canal principal (4ª coluna)
    col = next((i for i, c in enumerate(cab) if re.match(r'(Tempo de carregamento|Loading Time|Tempo de resposta|Response Time)\(RAW\)$', c)), 3)
    vals = []
    for linha in linhas[1:]:
        if len(linha) > col and linha[1]:  # a última linha ("Médias") não tem data RAW
            try:
                vals.append(float(linha[col]))
            except ValueError:
                pass
    return vals[-n:]


def suavizar(sensores, config):
    """Para a TV: tempo = mediana das 3 últimas medições (um pico isolado não muda a cor).
    Queda e alerta continuam imediatos: vêm do status do PRTG, que não passa por aqui."""
    ids = {i for n in config.get('nos', []) for i in n.get('sensores', []) + [j for it in n.get('itens', []) for j in it.get('sensores', [])]}
    alvo = [s for s in sensores if s['id'] in ids and s['tipo'] in TIPOS_TEMPO and s['st'] in (3, 4, 10)]
    with ThreadPoolExecutor(4) as ex:
        for s, vals in zip(alvo, ex.map(lambda s: ultimas_medicoes(s['id']), alvo)):
            if vals:
                s['med'] = sorted(vals)[len(vals) // 2]
                s['ult'] = vals[-1]


def coletar():
    config = carregar_config()
    grupos = [{'id': g['objid'], 'nome': g['name'], 'pai': g['parentid'], 'pos': g.get('position_raw', 0)}
              for g in tabela('groups', 'objid,name,parentid,position')]
    if not any(g['id'] == 1 for g in grupos):
        grupos.append({'id': 1, 'nome': 'Sonda local', 'pai': 0, 'pos': 0})
    devs = tabela('devices', 'objid,name,host,parentid,status,tags,position')
    sens = tabela('sensors', 'objid,parentid,name,status,message,lastvalue,priority,tags,type')
    ipam = carregar_ipam()
    with ThreadPoolExecutor(16) as ex:
        ips = list(ex.map(resolver, [d['host'] for d in devs]))
    devices = []
    for d, ip in zip(devs, ips):
        ent = ipam.get(ip)
        diverge = False  # o nome do PRTG é a referência; o phpIPAM entra só com descrição e sub-rede
        devices.append({'id': d['objid'], 'nome': d['name'], 'host': d['host'], 'ip': ip, 'pai': d['parentid'], 'st': d['status_raw'],
                        'tags': d['tags'], 'pos': d.get('position_raw', 0), 'ipam': ent, 'diverge': diverge})
    sensores = [{'id': s['objid'], 'dev': s['parentid'], 'nome': s['name'], 'st': s['status_raw'], 'msg': s['message_raw'],
                 'val': s['lastvalue'], 'raw': s.get('lastvalue_raw'), 'pri': s['priority_raw'], 'tags': s['tags'], 'tipo': s['type_raw']}
                for s in sens]
    try:
        suavizar(sensores, config)
    except Exception as e:  # sem mediana, a tela usa o último valor
        log.warning('mediana dos tempos falhou: %s', e)
    # conferência: cada sensor citado no config existe? em qual device?
    por_id = {s['id']: s for s in sensores}
    dev_id = {d['id']: d for d in devices}
    conferencia = []
    for n in config.get('nos', []) + config.get('observadores', []):
        ids = list(n.get('sensores', [])) + [i for it in n.get('itens', []) for i in it.get('sensores', [])]
        for i in ids:
            s = por_id.get(i)
            d = dev_id.get(s['dev']) if s else None
            conferencia.append({'no': n['id'], 'rotulo': n['rotulo'], 'sensor': i, 'existe': bool(s),
                                'nome': s['nome'] if s else '', 'st': s['st'] if s else None,
                                'device': d['nome'] if d else '', 'ip': d['ip'] if d else '',
                                'ipam': (d['ipam'] or {}).get('nome', '') if d else ''})
        if n.get('grupoNome') and not any(g['nome'] == n['grupoNome'] for g in grupos):
            conferencia.append({'no': n['id'], 'rotulo': n['rotulo'], 'sensor': None, 'existe': False,
                                'nome': f"grupo '{n['grupoNome']}' não existe", 'st': None, 'device': '', 'ip': '', 'ipam': ''})
    return {'gerado': time.time(), 'versao': versao_telas(), 'intervalo': INTERVALO, 'prtg': PRTG, 'grafanaPublico': GRAFANA_PUBLICO,
            'grafanaOk': grafana_ok(), 'grupos': grupos, 'devices': devices, 'sensores': sensores,
            'config': config, 'conferencia': conferencia, 'ipamTotal': len(ipam)}


def publicar(dados):
    corpo = json.dumps(dados, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with trava:
        estado['dados'], estado['json'], estado['gz'] = dados, corpo, gzip.compress(corpo, 6)


def ciclo():
    while True:
        inicio = time.time()
        try:
            dados = coletar()
            estado['ok_em'], estado['falhas'], estado['erro'] = time.time(), 0, None
            dados['erro'] = estado['config_erro']
            publicar(dados)
            log.info('coleta ok: %d devices, %d sensores (%.1fs)', len(dados['devices']), len(dados['sensores']), time.time() - inicio)
        except Exception as e:
            estado['falhas'] += 1
            estado['erro'] = f'Falha ao ler o PRTG ({e.__class__.__name__}: {e})'
            log.error(estado['erro'])
            if estado['dados']:
                d = dict(estado['dados'])
                d['erro'] = estado['erro'] + ' — mostrando a última coleta boa'
                publicar(d)
        espera = INTERVALO if not estado['falhas'] else min(300, 15 * estado['falhas'])
        time.sleep(max(5, espera - (time.time() - inicio)))


# ------------------------------------------------------------------ web
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com data:; img-src 'self' data:; frame-src 'self'; connect-src 'self'")
ARQUIVOS = {'/': ('index.html', 'text/html; charset=utf-8'), '/index.html': ('index.html', 'text/html; charset=utf-8'),
            '/mosaico': ('mosaico.html', 'text/html; charset=utf-8'), '/fluxo': ('fluxo.html', 'text/html; charset=utf-8')}


class Handler(BaseHTTPRequestHandler):
    server_version = 'Topologia'
    sys_version = ''

    def log_message(self, *a):
        pass

    def responder(self, codigo, corpo, tipo, extra=None):
        self.send_response(codigo)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(corpo)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def autorizado(self):
        if not USUARIO:
            return True
        h = self.headers.get('Authorization', '')
        if h.startswith('Basic '):
            try:
                u, _, s = base64.b64decode(h[6:]).decode('utf-8').partition(':')
                if hmac.compare_digest(u, USUARIO) and hmac.compare_digest(hashlib.sha256(s.encode()).hexdigest(), HASH):
                    return True
            except Exception:
                pass
            time.sleep(1)  # freia tentativas de senha
            log.warning('login recusado de %s', self.client_address[0])
        self.responder(401, b'Login necessario', 'text/plain; charset=utf-8',
                       {'WWW-Authenticate': 'Basic realm="Topologia NOC", charset="UTF-8"'})
        return False

    def intermediario(self):
        """/prtg/api/... → PRTG, com a chave colocada aqui (o Grafana não precisa mais dela)."""
        local = self.client_address[0] in ('127.0.0.1', '::1', '::ffff:127.0.0.1')
        token_ok = PROXY_TOKEN and hmac.compare_digest(self.headers.get('X-Topo-Token', ''), PROXY_TOKEN)
        if not (local or token_ok or self.autorizado()):
            return
        caminho, _, query = self.path[len('/prtg'):].partition('?')
        if caminho == '/_status':
            corpo = json.dumps(dict(px_stats, paralelo=PROXY_PARALELO, itens_em_cache=len(_cache_px))).encode()
            return self.responder(200, corpo, 'application/json')
        if caminho not in PROXY_PERMITIDOS:  # só leitura, só o que os painéis usam
            return self.responder(403, b'Endpoint nao permitido pelo intermediario', 'text/plain')
        limpa = '&'.join(p for p in query.split('&') if p and p.split('=')[0].lower() not in ('apitoken', 'username', 'password', 'passhash'))
        st, tipo, corpo = proxy_prtg(caminho + ('?' + limpa if limpa else ''))
        self.responder(st, corpo, tipo, {'Cache-Control': 'no-store'})

    def do_GET(self):
        caminho = self.path.split('?', 1)[0]
        if caminho == '/saude':  # para o healthcheck do container; não expõe dados
            idade = time.time() - estado['ok_em'] if estado['ok_em'] else None
            ok = idade is not None and idade < INTERVALO * 5
            corpo = json.dumps({'ok': ok, 'ultima_coleta_ha_s': round(idade) if idade else None, 'falhas_seguidas': estado['falhas']}).encode()
            return self.responder(200 if ok else 503, corpo, 'application/json')
        if caminho.startswith('/prtg/'):
            return self.intermediario()
        if not self.autorizado():
            return
        if caminho == '/api/snapshot':
            with trava:
                corpo, gz = estado['json'], estado['gz']
            if corpo is None:
                msg = json.dumps({'erro': estado['erro'] or 'Primeira coleta em andamento, aguarde alguns segundos.'}, ensure_ascii=False).encode()
                return self.responder(503, msg, 'application/json; charset=utf-8', {'Retry-After': '5', 'Cache-Control': 'no-store'})
            if 'gzip' in self.headers.get('Accept-Encoding', ''):
                return self.responder(200, gz, 'application/json; charset=utf-8', {'Content-Encoding': 'gzip', 'Cache-Control': 'no-store'})
            return self.responder(200, corpo, 'application/json; charset=utf-8', {'Cache-Control': 'no-store'})
        if caminho == '/achados':
            arq = os.path.join(PASTA, 'achados.html')
            if not os.path.exists(arq):
                arq = os.path.join(PASTA, '..', 'topologia_achados.html')
            try:
                return self.responder(200, open(arq, 'rb').read(), 'text/html; charset=utf-8')
            except OSError:
                return self.responder(404, b'Achados nao encontrados', 'text/plain')
        if caminho in ARQUIVOS:
            nome, tipo = ARQUIVOS[caminho]
            return self.responder(200, open(os.path.join(PASTA, nome), 'rb').read(), tipo, {'Cache-Control': 'no-cache'})
        self.responder(404, b'Nao encontrado', 'text/plain')


def main():
    threading.Thread(target=ciclo, daemon=True, name='coletor').start()
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = '?'
    log.info('Topologia viva em http://localhost:%d e na rede em http://%s:%d (login: %s)', PORTA, ip, PORTA, 'sim' if USUARIO else 'não')
    srv = ThreadingHTTPServer((BIND, PORTA), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
