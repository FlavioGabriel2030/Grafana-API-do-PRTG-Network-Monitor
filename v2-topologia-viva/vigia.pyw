"""Vigia da topologia viva: mantém o servidor.py no ar e o reinicia se ele cair ou parar de responder.
Roda sem janela (pythonw). Sobe pelo atalho "Topologia viva NOC" da pasta Inicializar do Windows.
Registro em vigia.log (na mesma pasta)."""
import datetime, os, subprocess, sys, time, urllib.request

PASTA = os.path.dirname(os.path.abspath(__file__))
SAUDE = 'http://127.0.0.1:8090/prtg/_status'
LOG = os.path.join(PASTA, 'vigia.log')


def registrar(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n')


def respondendo():
    try:
        urllib.request.urlopen(SAUDE, timeout=10).read()
        return True
    except Exception:
        return False


def iniciar():
    saida = open(os.path.join(PASTA, 'servidor.log'), 'a', encoding='utf-8')
    return subprocess.Popen([sys.executable, 'servidor.py'], cwd=PASTA, stdout=saida, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


proc = None
if respondendo():
    registrar('servidor já estava no ar; só vigiando')
else:
    proc = iniciar()
    registrar(f'servidor iniciado (pid {proc.pid})')
falhas = 0
while True:
    time.sleep(10)
    if proc is not None and proc.poll() is not None:
        registrar(f'servidor parou (código {proc.returncode}); reiniciando')
        proc, falhas = iniciar(), 0
        continue
    if respondendo():
        falhas = 0
        continue
    falhas += 1
    if falhas >= 3:  # 30 s sem responder: considera travado
        registrar('servidor sem resposta há 30 s; reiniciando')
        if proc is not None and proc.poll() is None:
            proc.kill()
        proc, falhas = iniciar(), 0
        time.sleep(20)
