from flask import Flask, render_template, request, jsonify, send_from_directory, session, abort
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from threading import Lock
import sqlite3, textwrap, logging, os, secrets, hashlib, smtplib, time
from email.message import EmailMessage
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

BASE=Path(__file__).resolve().parent
PDF_DIR=BASE/'comandas'; PDF_DIR.mkdir(exist_ok=True)
DB=BASE/'padaria.db'; app=Flask(__name__); lock=Lock()
KEYFILE=BASE/'.chave_sessao'
if not KEYFILE.exists():
    KEYFILE.write_text(secrets.token_hex(32),encoding='utf-8')
    try: KEYFILE.chmod(0o600)
    except OSError: pass
app.secret_key=KEYFILE.read_text(encoding='utf-8').strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),MAX_CONTENT_LENGTH=64*1024)
ATTEMPTS={}
def limit(action,maximum=6,window=900):
    key=(request.remote_addr,action); nowtime=time.time()
    with lock:
        ATTEMPTS[key]=[t for t in ATTEMPTS.get(key,[]) if nowtime-t<window]
        if len(ATTEMPTS[key])>=maximum: return False
        ATTEMPTS[key].append(nowtime)
        if len(ATTEMPTS)>2000:
            for k in list(ATTEMPTS)[:1000]: ATTEMPTS.pop(k,None)
    return True

def owner():
    with db() as c: return c.execute('SELECT * FROM responsavel WHERE id=1').fetchone()
def logged(): return bool(session.get('admin')) and bool(owner())
def guard(f):
    @wraps(f)
    def inner(*args,**kwargs):
        if not logged(): return jsonify(erro='Entre com a senha do responsável.'),401
        if request.method not in ('GET','HEAD') and request.headers.get('X-CSRF-Token')!=session.get('csrf'):
            return jsonify(erro='Sessão inválida. Entre novamente.'),403
        return f(*args,**kwargs)
    return inner

def send_code(email,code,subject):
    host=os.getenv('SMTP_HOST','').strip(); username=os.getenv('SMTP_USER','').strip(); password=os.getenv('SMTP_PASSWORD','').strip()
    sender=os.getenv('SMTP_FROM',username).strip(); port=int(os.getenv('SMTP_PORT','587'))
    if not host or not sender: raise RuntimeError('Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD e SMTP_FROM no notebook.')
    msg=EmailMessage(); msg['Subject']=subject; msg['From']=sender; msg['To']=email
    msg.set_content('Seu código de verificação da Padaria Bairro Jardins é: '+code+'\nVálido por 10 minutos. Não compartilhe este código.')
    if port==465:
        with smtplib.SMTP_SSL(host,port,timeout=12) as smtp:
            if username: smtp.login(username,password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host,port,timeout=12) as smtp:
            smtp.starttls()
            if username: smtp.login(username,password)
            smtp.send_message(msg)

def codehash(code): return hashlib.sha256(code.encode()).hexdigest()

FONT='Helvetica'
for path in [Path('C:/Windows/Fonts/arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]:
    if path.exists():
        try: pdfmetrics.registerFont(TTFont('ComandaFont',str(path))); FONT='ComandaFont'; break
        except Exception: pass

def db():
    c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=20000'); return c

def init_db():
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS produtos(id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL,categoria TEXT NOT NULL,preco_centavos INTEGER NOT NULL,ativo INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS mesas(numero INTEGER PRIMARY KEY,status TEXT NOT NULL DEFAULT 'livre' CHECK(status IN ('livre','ocupada')));
        CREATE TABLE IF NOT EXISTS pedidos(id INTEGER PRIMARY KEY AUTOINCREMENT,mesa INTEGER NOT NULL,garcom TEXT NOT NULL,observacao TEXT NOT NULL DEFAULT '',total_centavos INTEGER NOT NULL,criado_em TEXT NOT NULL,pdf TEXT,estado TEXT NOT NULL DEFAULT 'pendente' CHECK(estado IN ('pendente','preparando','pronto','entregue')),FOREIGN KEY(mesa) REFERENCES mesas(numero));
        CREATE TABLE IF NOT EXISTS itens(id INTEGER PRIMARY KEY AUTOINCREMENT,pedido_id INTEGER NOT NULL,produto TEXT NOT NULL,quantidade INTEGER NOT NULL,preco_centavos INTEGER NOT NULL,FOREIGN KEY(pedido_id) REFERENCES pedidos(id));
        CREATE TABLE IF NOT EXISTS fechamentos(id INTEGER PRIMARY KEY AUTOINCREMENT,mesa INTEGER NOT NULL,total_centavos INTEGER NOT NULL,fechado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fechamento_pedidos(fechamento_id INTEGER NOT NULL,pedido_id INTEGER NOT NULL UNIQUE,FOREIGN KEY(fechamento_id) REFERENCES fechamentos(id),FOREIGN KEY(pedido_id) REFERENCES pedidos(id));
        CREATE TABLE IF NOT EXISTS responsavel(id INTEGER PRIMARY KEY CHECK(id=1),email TEXT NOT NULL,senha_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS verificacoes(tipo TEXT PRIMARY KEY,codigo_hash TEXT NOT NULL,expira REAL NOT NULL,tentativas INTEGER NOT NULL DEFAULT 0,novo_email TEXT);''')
        if 'ativo' not in [col[1] for col in c.execute('PRAGMA table_info(mesas)')]:
            c.execute('ALTER TABLE mesas ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1')
        if 'confirmado_caixa' not in [col[1] for col in c.execute('PRAGMA table_info(pedidos)')]:
            c.execute('ALTER TABLE pedidos ADD COLUMN confirmado_caixa INTEGER NOT NULL DEFAULT 0')
        c.executemany('INSERT OR IGNORE INTO mesas(numero) VALUES(?)',[(i,) for i in range(1,11)])
        if not c.execute('SELECT 1 FROM produtos LIMIT 1').fetchone():
            c.executemany('INSERT INTO produtos(nome,categoria,preco_centavos) VALUES(?,?,?)', [('Café com leite','Bebidas',650),('Café expresso','Bebidas',450),('Suco de laranja','Bebidas',900),('Pão na chapa','Lanches',800),('Misto quente','Lanches',1200),('Pão de queijo','Lanches',500)])

def now(): return datetime.now().strftime('%d/%m/%Y %H:%M:%S')
def money(cents): return 'R$ '+f'{cents/100:,.2f}'.replace(',','X').replace('.',',').replace('X','.')
def pdf_for(pid,mesa,garcom,obs,items,created,total):
    lines=['PADARIA BAIRRO JARDINS','COMANDA - COZINHA',f'MESA {mesa:02d}',f'PEDIDO #{pid:05d}',f'Garcom: {garcom}',created,'-'*25]
    for it in items: lines+=textwrap.wrap(f"{it['quantidade']}x {it['nome']}",width=23) or ['']
    if obs: lines+=['-'*25,'OBSERVACOES:']+textwrap.wrap(obs,width=23)
    lines+=['-'*25,'TOTAL: '+money(total),'']
    width=58*mm; height=max(85*mm,(len(lines)*5+14)*mm)
    name=f'pedido_{pid:05d}_mesa_{mesa:02d}.pdf'; pdf=canvas.Canvas(str(PDF_DIR/name),pagesize=(width,height)); pdf.setTitle(f'Pedido {pid} - Mesa {mesa}')
    y=height-8*mm
    for line in lines:
        pdf.setFont(FONT,8 if len(line)>22 else 9); pdf.drawString(4*mm,y,line); y-=5*mm
    pdf.save(); return name

def open_orders(c,mesa):
    return c.execute('''SELECT p.*,COALESCE((SELECT SUM(i.quantidade) FROM itens i WHERE i.pedido_id=p.id),0) AS qtd FROM pedidos p WHERE p.mesa=? AND NOT EXISTS(SELECT 1 FROM fechamento_pedidos f WHERE f.pedido_id=p.id) ORDER BY p.id DESC''',(mesa,)).fetchall()

@app.get('/')
def index(): return render_template('index.html')
@app.get('/api/mesas')
def mesas():
    with db() as c:
        rows=c.execute('''SELECT m.numero,m.status,COALESCE(SUM(CASE WHEN f.pedido_id IS NULL THEN p.total_centavos ELSE 0 END),0) total_centavos,COUNT(CASE WHEN p.id IS NOT NULL AND f.pedido_id IS NULL THEN 1 END) pedidos FROM mesas m LEFT JOIN pedidos p ON p.mesa=m.numero LEFT JOIN fechamento_pedidos f ON f.pedido_id=p.id AND m.ativo=1 GROUP BY m.numero ORDER BY m.numero''').fetchall()
    return jsonify([dict(r) for r in rows])
@app.get('/api/produtos')
def produtos():
    with db() as c: return jsonify([dict(r) for r in c.execute('SELECT * FROM produtos ORDER BY categoria,nome')])
@app.post('/api/produtos')
@guard
def add_produto():
    data=request.get_json(silent=True) or {}; nome=str(data.get('nome','')).strip()[:90]; categoria=str(data.get('categoria','')).strip()[:50]
    try:
        preco=Decimal(str(data.get('preco','')).replace(',','.')); cents=int((preco*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        if not nome or not categoria or cents<=0 or cents>10000000: raise ValueError()
    except (InvalidOperation,ValueError,TypeError): return jsonify(erro='Informe nome, categoria e preço válido.'),400
    with db() as c:
        cur=c.execute('INSERT INTO produtos(nome,categoria,preco_centavos) VALUES(?,?,?)',(nome,categoria,cents)); return jsonify(id=cur.lastrowid),201
@app.patch('/api/produtos/<int:pid>')
@guard
def edit_produto(pid):
    d=request.get_json(silent=True) or {}
    if 'ativo' not in d or d['ativo'] not in (True,False): return jsonify(erro='Informe ativo: true ou false.'),400
    with db() as c:
        cur=c.execute('UPDATE produtos SET ativo=? WHERE id=?',(int(d['ativo']),pid))
        if not cur.rowcount: return jsonify(erro='Produto não encontrado.'),404
    return jsonify(ok=True)
@app.post('/api/mesas')
@guard
def add_mesa():
    data=request.get_json(silent=True) or {}
    try:
        numero=int(data.get('numero'))
        if not 1<=numero<=999:raise ValueError()
    except (ValueError,TypeError):return jsonify(erro='Informe um número de mesa entre 1 e 999.'),400
    with db() as c:
        existing=c.execute('SELECT ativo FROM mesas WHERE numero=?',(numero,)).fetchone()
        if existing and existing['ativo']:return jsonify(erro='Esta mesa já existe.'),409
        if existing:c.execute("UPDATE mesas SET ativo=1,status='livre' WHERE numero=?",(numero,))
        else:c.execute('INSERT INTO mesas(numero) VALUES(?)',(numero,))
    return jsonify(ok=True,numero=numero),201

@app.delete('/api/mesas/<int:numero>')
@guard
def remove_mesa(numero):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        mesa=c.execute('SELECT * FROM mesas WHERE numero=?',(numero,)).fetchone()
        if not mesa:return jsonify(erro='Mesa não encontrada.'),404
        if mesa['status']=='ocupada' or open_orders(c,numero):
            return jsonify(erro='Feche a comanda antes de excluir esta mesa.'),409
        # Soft delete: keeps historic orders and allows reactivating this number later.
        c.execute('UPDATE mesas SET ativo=0 WHERE numero=?',(numero,))
    return jsonify(ok=True)

@app.get('/api/dashboard')
@guard
def dashboard():
    with db() as c:
        total=c.execute('SELECT COUNT(*) FROM mesas WHERE ativo=1').fetchone()[0]
        occupied=c.execute("SELECT COUNT(*) FROM mesas WHERE ativo=1 AND status='ocupada'").fetchone()[0]
        pending=c.execute("SELECT COUNT(*) FROM pedidos p WHERE p.estado IN ('pendente','preparando','pronto') AND NOT EXISTS(SELECT 1 FROM fechamento_pedidos f WHERE f.pedido_id=p.id)").fetchone()[0]
        sales=c.execute('SELECT COALESCE(SUM(total_centavos),0) FROM fechamentos WHERE substr(fechado_em,1,10)=?',(datetime.now().strftime('%d/%m/%Y'),)).fetchone()[0]
        recent=[dict(r) for r in c.execute('SELECT id,mesa,garcom,total_centavos,estado,criado_em FROM pedidos ORDER BY id DESC LIMIT 6')]
    return jsonify(mesas=total,ocupadas=occupied,livres=total-occupied,pedidos_cozinha=pending,vendas_hoje_centavos=sales,recentes=recent)

@app.get('/api/mesas/<int:mesa>')
def mesa_detail(mesa):
    with db() as c:
        m=c.execute('SELECT * FROM mesas WHERE numero=? AND ativo=1',(mesa,)).fetchone()
        if not m:return jsonify(erro='Mesa não encontrada'),404
        orders=[dict(r) for r in open_orders(c,mesa)]
        for o in orders:o['itens']=[dict(i) for i in c.execute('SELECT produto,quantidade,preco_centavos FROM itens WHERE pedido_id=?',(o['id'],))]
        return jsonify(mesa=mesa,status=m['status'],pedidos=orders,total_centavos=sum(o['total_centavos'] for o in orders))
@app.post('/api/pedidos')
def create_order():
    d=request.get_json(silent=True) or {}
    try:
        mesa=int(d.get('mesa',0)); garcom=str(d.get('garcom','')).strip()[:60]; obs=str(d.get('observacao','')).strip()[:300]; chosen=d.get('itens')
        if not garcom or not isinstance(chosen,list) or not 1<=len(chosen)<=40: raise ValueError()
        if not 1<=mesa<=999: raise ValueError()
        ids=[]; quantities={}
        for item in chosen:
            pid=int(item['id']); qty=int(item['quantidade'])
            if qty<1 or qty>30 or pid in quantities:raise ValueError()
            ids.append(pid); quantities[pid]=qty
    except (ValueError,TypeError,KeyError):return jsonify(erro='Confira mesa, garçom e produtos.'),400
    with lock:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM mesas WHERE numero=? AND ativo=1',(mesa,)).fetchone():return jsonify(erro='Mesa inexistente.'),400
            placeholders=','.join('?' for _ in ids)
            products=c.execute(f'SELECT * FROM produtos WHERE ativo=1 AND id IN ({placeholders})',ids).fetchall()
            if len(products)!=len(ids):return jsonify(erro='Um produto está indisponível. Atualize o cardápio.'),400
            items=[dict(nome=p['nome'],quantidade=quantities[p['id']],preco_centavos=p['preco_centavos']) for p in products]
            total=sum(i['quantidade']*i['preco_centavos'] for i in items); created=now()
            cur=c.execute('INSERT INTO pedidos(mesa,garcom,observacao,total_centavos,criado_em) VALUES(?,?,?,?,?)',(mesa,garcom,obs,total,created)); pid=cur.lastrowid
            c.executemany('INSERT INTO itens(pedido_id,produto,quantidade,preco_centavos) VALUES(?,?,?,?)',[(pid,i['nome'],i['quantidade'],i['preco_centavos']) for i in items]); c.execute("UPDATE mesas SET status='ocupada' WHERE numero=?",(mesa,))
            # Save order first. A PDF failure never loses the order.
            c.commit()
            try:
                filename=pdf_for(pid,mesa,garcom,obs,items,created,total)
                c.execute('UPDATE pedidos SET pdf=? WHERE id=?',(filename,pid))
            except Exception:
                app.logger.exception('Falha no PDF do pedido %s',pid)
                return jsonify(numero=pid,aviso='Pedido salvo, mas o PDF falhou. Verifique a cozinha antes de reenviar.',pdf=None),201
    return jsonify(numero=pid,pdf=f'/comandas/{filename}'),201
@app.get('/api/cozinha')
def kitchen():
    with db() as c:
        orders=[dict(r) for r in c.execute("SELECT * FROM pedidos WHERE estado IN ('pendente','preparando','pronto') AND NOT EXISTS(SELECT 1 FROM fechamento_pedidos f WHERE f.pedido_id=pedidos.id) ORDER BY id DESC LIMIT 100")]
        for o in orders:o['itens']=[dict(i) for i in c.execute('SELECT produto,quantidade FROM itens WHERE pedido_id=?',(o['id'],))]
    return jsonify(orders)
@app.patch('/api/pedidos/<int:pid>/estado')
def state(pid):
    d=request.get_json(silent=True) or {}; state=d.get('estado')
    if state not in ('pendente','preparando','pronto','entregue'):return jsonify(erro='Estado inválido'),400
    with db() as c:
        cur=c.execute('UPDATE pedidos SET estado=? WHERE id=? AND NOT EXISTS(SELECT 1 FROM fechamento_pedidos WHERE pedido_id=?)',(state,pid,pid))
        if not cur.rowcount:return jsonify(erro='Pedido não encontrado ou mesa já fechada'),404
    return jsonify(ok=True)
@app.patch('/api/pedidos/<int:pid>/confirmar-caixa')
@guard
def confirm_cash(pid):
    data=request.get_json(silent=True) or {}
    if type(data.get('confirmado')) is not bool:
        return jsonify(erro='Informe confirmado: true ou false.'),400
    with lock:
        with db() as c:
            cur=c.execute("""UPDATE pedidos SET confirmado_caixa=? WHERE id=?
                AND NOT EXISTS(SELECT 1 FROM fechamento_pedidos WHERE pedido_id=?)""",
                (int(data['confirmado']),pid,pid))
            if not cur.rowcount:return jsonify(erro='Pedido não encontrado ou mesa já fechada.'),404
    return jsonify(ok=True)

@app.post('/api/mesas/<int:mesa>/fechar')
@guard
def close_table(mesa):
    with lock:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            orders=open_orders(c,mesa)
            if not orders:return jsonify(erro='Esta mesa não tem pedidos em aberto.'),400
            if any(not o['confirmado_caixa'] for o in orders):return jsonify(erro='Confira e confirme todos os pedidos da mesa antes de fechar.'),409
            total=sum(o['total_centavos'] for o in orders)
            cur=c.execute('INSERT INTO fechamentos(mesa,total_centavos,fechado_em) VALUES(?,?,?)',(mesa,total,now()))
            c.executemany('INSERT INTO fechamento_pedidos(fechamento_id,pedido_id) VALUES(?,?)',[(cur.lastrowid,o['id']) for o in orders]); c.execute("UPDATE mesas SET status='livre' WHERE numero=?",(mesa,))
            return jsonify(fechamento=cur.lastrowid,total_centavos=total)
@app.get('/api/fechamentos')
@guard
def closings():
    with db() as c:return jsonify([dict(r) for r in c.execute('SELECT * FROM fechamentos ORDER BY id DESC LIMIT 30')])

# O primeiro cadastro é permitido somente no próprio notebook (localhost).
@app.get('/api/auth/status')
def auth_status():
    o=owner()
    return jsonify(configurado=bool(o),autenticado=logged(),email_mascarado=(o['email'][:2]+'***@'+o['email'].split('@')[-1] if o else ''),csrf=session.get('csrf') if logged() else None)

@app.post('/api/auth/configurar')
def auth_setup():
    if request.remote_addr not in ('127.0.0.1','::1'):
        return jsonify(erro='Faça o primeiro cadastro pelo navegador do próprio notebook: http://127.0.0.1:5000'),403
    d=request.get_json(silent=True) or {}; email=str(d.get('email','')).strip().lower(); password=str(d.get('senha',''))
    if '@' not in email or '.' not in email.split('@')[-1] or len(email)>254 or len(password)<10:
        return jsonify(erro='Informe um e-mail válido e uma senha de pelo menos 10 caracteres.'),400
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM responsavel WHERE id=1').fetchone():return jsonify(erro='Responsável já cadastrado.'),409
        c.execute('INSERT INTO responsavel(id,email,senha_hash) VALUES(1,?,?)',(email,generate_password_hash(password)))
    session.clear();session['admin']=True;session['csrf']=secrets.token_urlsafe(32);session.permanent=True
    return jsonify(ok=True,csrf=session['csrf'])

@app.post('/api/auth/entrar')
def auth_login():
    if not limit('login'):return jsonify(erro='Muitas tentativas. Aguarde 15 minutos.'),429
    d=request.get_json(silent=True) or {}; o=owner()
    if not o or not check_password_hash(o['senha_hash'],str(d.get('senha',''))):
        return jsonify(erro='Senha incorreta.'),401
    session.clear();session['admin']=True;session['csrf']=secrets.token_urlsafe(32);session.permanent=True
    return jsonify(ok=True,csrf=session['csrf'])

@app.post('/api/auth/sair')
@guard
def auth_logout():session.clear();return jsonify(ok=True)

@app.post('/api/auth/solicitar-codigo')
def request_code():
    if not limit('codigo',3,900):return jsonify(erro='Limite de solicitações. Aguarde 15 minutos.'),429
    d=request.get_json(silent=True) or {}; typ=d.get('tipo')
    if typ not in ('senha','email'):return jsonify(erro='Operação inválida.'),400
    if typ=='email' and not logged():return jsonify(erro='Entre antes de alterar o e-mail.'),401
    o=owner()
    if not o:return jsonify(erro='Cadastre o responsável primeiro.'),400
    new_email=str(d.get('novo_email','')).strip().lower() if typ=='email' else None
    if typ=='email' and ('@' not in new_email or '.' not in new_email.split('@')[-1] or len(new_email)>254):
        return jsonify(erro='Informe um novo e-mail válido.'),400
    code=f'{secrets.randbelow(1000000):06d}'
    try:send_code(o['email'],code,'Código de verificação - Comanda Digital')
    except Exception:
        app.logger.exception('Falha no envio do e-mail de verificação')
        return jsonify(erro='Não foi possível enviar o código. Confira a configuração SMTP no notebook.'),503
    with db() as c:c.execute('INSERT OR REPLACE INTO verificacoes(tipo,codigo_hash,expira,tentativas,novo_email) VALUES(?,?,?,?,?)',(typ,codehash(code),time.time()+600,0,new_email))
    return jsonify(ok=True,mensagem='Código enviado ao e-mail do primeiro responsável.')

@app.post('/api/auth/verificar-codigo')
def verify_code():
    if not limit('verificar',10,900):return jsonify(erro='Muitas tentativas. Aguarde 15 minutos.'),429
    d=request.get_json(silent=True) or {};typ=d.get('tipo');code=str(d.get('codigo','')).strip()
    if typ not in ('senha','email') or len(code)!=6:return jsonify(erro='Código inválido.'),400
    if typ=='email' and not logged():return jsonify(erro='Entre antes de alterar o e-mail.'),401
    with db() as c:
        c.execute('BEGIN IMMEDIATE');v=c.execute('SELECT * FROM verificacoes WHERE tipo=?',(typ,)).fetchone()
        if not v or v['expira']<time.time() or v['tentativas']>=5:
            return jsonify(erro='Código expirado ou bloqueado. Solicite outro.'),400
        c.execute('UPDATE verificacoes SET tentativas=tentativas+1 WHERE tipo=?',(typ,))
        if not secrets.compare_digest(v['codigo_hash'],codehash(code)):
            return jsonify(erro='Código incorreto.'),400
        if typ=='senha':
            password=str(d.get('nova_senha',''))
            if len(password)<10:return jsonify(erro='A nova senha precisa ter pelo menos 10 caracteres.'),400
            c.execute('UPDATE responsavel SET senha_hash=? WHERE id=1',(generate_password_hash(password),))
            session.clear()
        else:c.execute('UPDATE responsavel SET email=? WHERE id=1',(v['novo_email'],))
        c.execute('DELETE FROM verificacoes WHERE tipo=?',(typ,))
    return jsonify(ok=True)

@app.get('/comandas/<path:name>')
def download_pdf(name):return send_from_directory(PDF_DIR,name)
if __name__=='__main__':
    init_db(); app.run(host='0.0.0.0',port=5000,debug=False)
