let products=[],tables=[],selected=1,quantities={},auth={configurado:false,autenticado:false,csrf:null},pendingTab=null,authMode='login';
const $=id=>document.getElementById(id), money=c=>(c/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function notify(msg,bad=false){const a=$('alert');a.className=bad?'error':'success';a.textContent=msg;setTimeout(()=>{if(a.textContent===msg){a.textContent='';a.className=''}},7000)}
async function api(path,options={}){options.headers={...(options.headers||{})};if(auth.csrf && options.method && !['GET','HEAD'].includes(options.method))options.headers['X-CSRF-Token']=auth.csrf;let res=await fetch(path,options);let d=await res.json();if(res.status===401&&path!='/api/auth/entrar'){auth.autenticado=false;auth.csrf=null;showAuth('login');}if(!res.ok)throw Error(d.erro||'Falha na operação');return d}
const json=(method,data)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function openPage(name){
  document.querySelectorAll('.tab[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===name));
  $('sair').hidden=name!=='caixa';$('sair-menu').hidden=!auth.autenticado;
  if(name==='inicio')loadDashboard();
  if(name==='gerenciar-mesas')loadAdminTables();
  if(name==='cozinha')loadKitchen();
  if(name==='caixa'){ $('mesas-caixa').textContent='Carregando caixa…';loadCash(); }
  if(name==='produtos')loadProducts().catch(e=>notify('Erro ao carregar produtos: '+e.message,true));
}
async function switchTab(name){
  setMenu(false);
  if(['inicio','caixa','produtos','gerenciar-mesas'].includes(name)){
    try{
      // Sempre consulta a sessão atual antes de abrir uma área protegida.
      const status=await api('/api/auth/status');
      auth=status;
      if(!status.autenticado){pendingTab=name;showAuth(status.configurado?'login':'setup');return;}
    }catch(e){notify('Não foi possível verificar o acesso: '+e.message,true);return;}
  }
  openPage(name);
}
document.querySelectorAll('.tab[data-tab]').forEach(b=>{
  b.type='button';
  b.addEventListener('click',()=>switchTab(b.dataset.tab));
});
const menuToggle=$('menu-toggle'),sideMenu=$('side-menu'),menuBackdrop=$('menu-backdrop');
function setMenu(open){sideMenu.classList.toggle('open',open);menuBackdrop.hidden=!open;sideMenu.setAttribute('aria-hidden',String(!open));menuToggle.setAttribute('aria-expanded',String(open));}
menuToggle.onclick=()=>setMenu(!sideMenu.classList.contains('open'));
$('menu-close').onclick=()=>setMenu(false);
menuBackdrop.onclick=()=>setMenu(false);
document.addEventListener('keydown',e=>{if(e.key==='Escape')setMenu(false)});

async function loadTables(){tables=await api('/api/mesas');if(!tables.some(t=>t.numero===selected)&&tables.length)selected=tables[0].numero;const root=$('mesas');root.replaceChildren();for(const t of tables){const b=el('button','mesa '+t.status+(selected===t.numero?' selected':''));b.append(el('strong','',String(t.numero).padStart(2,'0')),el('small','',t.status==='ocupada'?'Ocupada':'Livre'));b.onclick=()=>{selected=t.numero;renderTables();loadTableDetail()};root.append(b)}await loadTableDetail()}
function renderTables(){document.querySelectorAll('.mesa').forEach((b,i)=>b.classList.toggle('selected',tables[i].numero===selected))}
async function loadTableDetail(){const d=await api('/api/mesas/'+selected);$('titulo-mesa').textContent='Mesa '+String(selected).padStart(2,'0')+' • '+(d.status==='ocupada'?'Ocupada':'Livre');const root=$('historico');root.replaceChildren();if(d.pedidos.length){root.append(el('h3','','Pedidos já registrados'));for(const p of d.pedidos){const box=el('div','history');box.append(el('strong','',`Pedido #${p.id} • ${money(p.total_centavos)} • ${p.estado}`));for(const i of p.itens)box.append(el('p','',`${i.quantidade}x ${i.produto}`));root.append(box)}root.append(el('strong','','Total da mesa: '+money(d.total_centavos)))}}
async function loadProducts(){products=await api('/api/produtos');renderCatalog();renderProductsAdmin()}
function renderCatalog(){const root=$('catalogo');root.replaceChildren();for(const p of products.filter(p=>p.ativo)){const box=el('div','product');box.append(el('small','',p.categoria),el('h3','',p.nome),el('div','price',money(p.preco_centavos)));const ctrl=el('div','qty'),minus=el('button','','−'),count=el('strong','',quantities[p.id]||0),plus=el('button','','+');minus.onclick=()=>changeQty(p.id,-1);plus.onclick=()=>changeQty(p.id,1);count.id='q'+p.id;ctrl.append(minus,count,plus);box.append(ctrl);root.append(box)}updateTotal()}
function changeQty(id,delta){quantities[id]=Math.max(0,Math.min(30,(quantities[id]||0)+delta));$('q'+id).textContent=quantities[id];updateTotal()}
function updateTotal(){$('total').textContent='Total deste pedido: '+money(products.reduce((sum,p)=>sum+p.preco_centavos*(quantities[p.id]||0),0))}
$('enviar').onclick=async()=>{const items=products.filter(p=>quantities[p.id]>0&&p.ativo).map(p=>({id:p.id,quantidade:quantities[p.id]}));const garcom=$('garcom').value.trim();if(!garcom||!items.length){notify('Informe o garçom e selecione os produtos.',true);return}if(!confirm(`Confirmar novo pedido para mesa ${selected}?`))return;const b=$('enviar');b.disabled=true;try{const d=await api('/api/pedidos',json('POST',{mesa:selected,garcom,observacao:$('observacao').value,itens:items}));quantities={};$('observacao').value='';renderCatalog();await loadTables();notify(d.aviso||`Pedido #${d.numero} salvo! PDF: ${d.pdf||'indisponível'}`,!!d.aviso);if(d.pdf){const a=el('a','',` Abrir PDF do pedido #${d.numero}`);a.href=d.pdf;a.target='_blank';a.rel='noopener';$('alert').append(a)}}catch(e){notify(e.message,true)}finally{b.disabled=false}};
async function loadKitchen(){
 try{
  const data=await api('/api/cozinha'),root=$('pedidos-cozinha');root.replaceChildren();
  if(!data.length){root.append(el('p','muted','Nenhum pedido em aberto na cozinha.'));return}
  for(const p of data){
   const box=el('article','order kitchen-order');
   box.append(el('div','kitchen-mesa',`MESA ${String(p.mesa).padStart(2,'0')}`),el('h3','',`Pedido #${p.id}`),el('small','',`${p.garcom} • ${p.criado_em}`));
   const list=el('ul','order-items');
   for(const i of p.itens)list.append(el('li','',`${i.quantidade}x ${i.produto}`));
   box.append(list);
   if(p.observacao)box.append(el('p','obs',`OBSERVAÇÃO: ${p.observacao}`));
   const lbl=el('label','','Situação do pedido'),select=el('select');
   for(const st of ['pendente','preparando','pronto','entregue']){
    const o=el('option','',st[0].toUpperCase()+st.slice(1));o.value=st;o.selected=p.estado===st;select.append(o)
   }
   select.onchange=async()=>{try{await api(`/api/pedidos/${p.id}/estado`,json('PATCH',{estado:select.value}));notify('Pedido atualizado.');await loadKitchen()}catch(e){notify(e.message,true)}};
   box.append(lbl,select);
   if(p.pdf){const a=el('a','','Ver PDF da comanda');a.href='/comandas/'+encodeURIComponent(p.pdf);a.target='_blank';a.rel='noopener';const linkBox=el('p');linkBox.append(a);box.append(linkBox)}
   root.append(box)
  }
 }catch(e){notify(e.message,true)}
}
setInterval(()=>{if($('cozinha').classList.contains('active'))loadKitchen();if($('caixa').classList.contains('active'))loadCash();if($('inicio').classList.contains('active'))loadDashboard()},60000);
async function loadCash(){
 try{
  const ts=await api('/api/mesas'),root=$('mesas-caixa');root.replaceChildren();
  for(const t of ts.filter(t=>t.pedidos)){
   const detail=await api('/api/mesas/'+t.numero),box=el('article','order cash-order');
   box.append(el('h3','',`Mesa ${String(t.numero).padStart(2,'0')}`));
   for(const p of detail.pedidos){
    const order=el('div','cash-ticket');
    order.append(el('strong','',`Pedido #${p.id} • ${p.garcom}`));
    const list=el('ul','order-items');
    for(const i of p.itens){
     list.append(el('li','',`${i.quantidade}x ${i.produto} — ${money(i.quantidade*i.preco_centavos)}`));
    }
    order.append(list);
    if(p.observacao)order.append(el('p','obs',`Observação: ${p.observacao}`));
    order.append(el('p','',`Subtotal: ${money(p.total_centavos)}`));
    const label=el('label','check-line'),check=el('input');check.type='checkbox';check.checked=!!p.confirmado_caixa;
    label.append(check,document.createTextNode(' Conferi os itens deste pedido com o cliente'));
    check.onchange=async()=>{check.disabled=true;try{await api(`/api/pedidos/${p.id}/confirmar-caixa`,json('PATCH',{confirmado:check.checked}));notify(`Pedido #${p.id} ${check.checked?'confirmado':'desmarcado'}.`);await loadCash()}catch(e){notify(e.message,true);await loadCash()}};
    order.append(label);box.append(order)
   }
   box.append(el('div','cash-total',`TOTAL DA MESA: ${money(detail.total_centavos)}`));
   const allConfirmed=detail.pedidos.every(p=>p.confirmado_caixa),b=el('button','primary full',allConfirmed?'Confirmar pagamento e fechar mesa':'Confira todos os pedidos antes de fechar');b.disabled=!allConfirmed;
   b.onclick=async()=>{
    if(!confirm(`O pagamento da mesa ${t.numero} de ${money(detail.total_centavos)} foi recebido? Fechar a mesa?`))return;
    b.disabled=true;
    try{const d=await api(`/api/mesas/${t.numero}/fechar`,json('POST',{}));notify(`Mesa ${t.numero} fechada: ${money(d.total_centavos)}`);await loadCash();await loadTables()}
    catch(e){notify(e.message,true);await loadCash()}
   };
   box.append(b);root.append(box)
  }
  if(!root.children.length)root.append(el('p','muted','Nenhuma mesa aberta.'));
  const closings=await api('/api/fechamentos'),history=$('fechamentos');history.replaceChildren();
  for(const f of closings)history.append(el('div','row',`#${f.id} • Mesa ${f.mesa} • ${money(f.total_centavos)} • ${f.fechado_em}`))
 }catch(e){notify(e.message,true)}
}
function renderProductsAdmin(){const root=$('lista-produtos');root.replaceChildren();for(const p of products){const row=el('div','row'),info=el('div');info.append(el('strong','',p.nome),el('div','muted',`${p.categoria} • ${money(p.preco_centavos)} • ${p.ativo?'Ativo':'Inativo'}`));const b=el('button','',p.ativo?'Desativar':'Ativar');b.onclick=async()=>{try{await api(`/api/produtos/${p.id}`,json('PATCH',{ativo:!p.ativo}));await loadProducts()}catch(e){notify(e.message,true)}};row.append(info,b);root.append(row)}}
$('form-produto').onsubmit=async e=>{e.preventDefault();try{await api('/api/produtos',json('POST',{nome:$('nome-produto').value,categoria:$('categoria-produto').value,preco:$('preco-produto').value}));e.target.reset();notify('Produto cadastrado.');await loadProducts()}catch(err){notify(err.message,true)}};
$('atualizar-cozinha').onclick=loadKitchen;
(async()=>{try{await loadProducts();await loadTables()}catch(e){notify(e.message,true)}})();

// Login único para Caixa e Produtos. Sessão expira após 30 minutos de inatividade.
async function refreshAuth(){auth=await api('/api/auth/status');$('sair-menu').hidden=!auth.autenticado}
function showAuth(mode='login'){
 authMode=mode;$('auth-overlay').hidden=false;$('auth-form').reset();$('auth-msg').textContent='';
 const setup=mode==='setup',login=mode==='login',reset=mode==='reset',change=mode==='change-email',verify=mode==='verify-reset'||mode==='verify-email';
 $('auth-title').textContent=setup?'Primeiro cadastro do responsável':login?'Acesso ao caixa e produtos':reset?'Redefinir senha':change?'Alterar e-mail cadastrado':'Verificar código';
 $('auth-help').textContent=setup?'Cadastre o e-mail original e uma senha de pelo menos 10 caracteres.':login?'A mesma senha libera o caixa e o cadastro de produtos.':reset?'O código será enviado ao e-mail original cadastrado.':change?'O código de autorização será enviado ao e-mail original.':'Digite o código de 6 dígitos recebido por e-mail.';
 $('auth-email-wrap').hidden=!setup;$('auth-password-wrap').hidden=!(setup||login||mode==='verify-reset');$('auth-newemail-wrap').hidden=!change;$('auth-code-wrap').hidden=!verify;
 $('auth-password').required=setup||login||mode==='verify-reset';$('auth-code').required=verify;
 $('auth-password').placeholder=mode==='verify-reset'?'Nova senha (mínimo 10 caracteres)':'';
 $('auth-submit').textContent=setup?'Cadastrar responsável':login?'Entrar':reset||change?'Enviar código':'Confirmar alteração';
 $('forgot').hidden=!login;$('change-email').hidden=!login||!auth.autenticado;$('back-login').hidden=setup||login;
}
function hideAuth(){$('auth-overlay').hidden=true;$('auth-msg').textContent=''}
$('auth-close').onclick=()=>{pendingTab=null;hideAuth()};
$('back-login').onclick=()=>showAuth('login');
$('forgot').onclick=()=>showAuth('reset');
$('change-email').onclick=()=>showAuth('change-email');
async function logoutAdmin(){try{await api('/api/auth/sair',json('POST',{}));auth.autenticado=false;auth.csrf=null;openPage('atendimento');setMenu(false);notify('Área administrativa bloqueada. Para entrar novamente, informe a senha.')}catch(e){notify(e.message,true)}}
$('sair').onclick=logoutAdmin;$('sair-menu').onclick=logoutAdmin;
$('auth-form').onsubmit=async ev=>{
 ev.preventDefault();let d={};
 try{
  if(authMode==='setup'){d=await api('/api/auth/configurar',json('POST',{email:$('auth-email').value,senha:$('auth-password').value}));auth.configurado=true;auth.autenticado=true;auth.csrf=d.csrf}
  if(authMode==='login'){d=await api('/api/auth/entrar',json('POST',{senha:$('auth-password').value}));auth.autenticado=true;auth.csrf=d.csrf}
  if(authMode==='reset'){await api('/api/auth/solicitar-codigo',json('POST',{tipo:'senha'}));showAuth('verify-reset');$('auth-msg').textContent='Código enviado ao e-mail cadastrado.';return}
  if(authMode==='change-email'){await api('/api/auth/solicitar-codigo',json('POST',{tipo:'email',novo_email:$('auth-newemail').value}));showAuth('verify-email');$('auth-msg').textContent='Código enviado ao e-mail original.';return}
  if(authMode==='verify-reset'){await api('/api/auth/verificar-codigo',json('POST',{tipo:'senha',codigo:$('auth-code').value,nova_senha:$('auth-password').value}));auth.autenticado=false;auth.csrf=null;showAuth('login');$('auth-msg').textContent='Senha alterada. Entre com a nova senha.';return}
  if(authMode==='verify-email'){await api('/api/auth/verificar-codigo',json('POST',{tipo:'email',codigo:$('auth-code').value}));showAuth('login');$('auth-msg').textContent='E-mail alterado com sucesso.';return}
  hideAuth();let tab=pendingTab||'inicio';pendingTab=null;await switchTab(tab)
 }catch(e){$('auth-msg').textContent=e.message}
};
refreshAuth().then(()=>{if(!auth.configurado)notify('Cadastre o responsável no próprio notebook antes de usar o caixa e produtos.');}).catch(e=>notify(e.message,true));

// V6: painel inicial protegido e gestão dinâmica das mesas.
async function loadDashboard(){
 try{
  const d=await api('/api/dashboard'),k=$('dashboard-kpis');k.replaceChildren();
  for(const [label,value,icon] of [['Mesas cadastradas',d.mesas,'▦'],['Mesas ocupadas',d.ocupadas,'●'],['Pedidos na cozinha',d.pedidos_cozinha,'▤'],['Vendas de hoje',money(d.vendas_hoje_centavos),'R$']]){
   const card=el('div','kpi');card.append(el('div','kpi-icon',icon),el('div','kpi-label',label),el('strong','',value));k.append(card)
  }
  const mt=$('dashboard-mesas');mt.replaceChildren();const ts=await api('/api/mesas');
  for(const t of ts){const b=el('button','dashboard-mesa '+t.status,`Mesa ${String(t.numero).padStart(2,'0')} · ${t.status==='ocupada'?'Ocupada':'Livre'}`);b.onclick=()=>{selected=t.numero;switchTab('atendimento').then(loadTables)};mt.append(b)}
  const recent=$('dashboard-recentes');recent.replaceChildren();
  if(!d.recentes.length)recent.append(el('p','muted','Nenhum pedido registrado ainda.'));
  for(const p of d.recentes){const row=el('div','recent-row');row.append(el('strong','',`Mesa ${String(p.mesa).padStart(2,'0')} · Pedido #${p.id}`),el('span','',money(p.total_centavos)),el('small','muted',`${p.estado} · ${p.criado_em}`));recent.append(row)}
 }catch(e){notify('Não foi possível carregar a página inicial: '+e.message,true)}
}
async function loadAdminTables(){
 try{
  const ts=await api('/api/mesas'),root=$('lista-mesas-admin');root.replaceChildren();
  for(const t of ts){const row=el('div','admin-mesa'),info=el('span','',`Mesa ${String(t.numero).padStart(2,'0')} · ${t.status==='ocupada'?'Ocupada':'Livre'}`),b=el('button','danger-outline','Excluir');
   b.disabled=t.status==='ocupada'||t.pedidos>0;b.title=b.disabled?'Feche a comanda antes de excluir':'Retirar mesa do atendimento sem apagar o histórico';
   b.onclick=async()=>{if(!confirm(`Excluir a mesa ${t.numero}?`))return;try{await api('/api/mesas/'+t.numero,{method:'DELETE'});notify('Mesa excluída.');await loadAdminTables();await loadTables()}catch(e){notify(e.message,true)}};
   row.append(info,b);root.append(row)
  }
 }catch(e){notify(e.message,true)}
}
$('form-mesa').onsubmit=async e=>{
 e.preventDefault();try{const n=Number($('nova-mesa').value);await api('/api/mesas',json('POST',{numero:n}));e.target.reset();notify('Mesa cadastrada.');await loadAdminTables();await loadTables()}catch(err){notify(err.message,true)}
};
$('atualizar-inicio').onclick=loadDashboard;
