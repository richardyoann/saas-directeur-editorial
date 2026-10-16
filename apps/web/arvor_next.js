
(() => {
'use strict';
// ARVOR / STUDIO: authenticated adapter being tested.
const ASSETS={forest:'/studio/assets/arvor_forest.jpg',sea:'/studio/assets/arvor_sea.jpg'};
const $=selector=>document.querySelector(selector);
const $$=selector=>[...document.querySelectorAll(selector)];
const ico=(name)=>`<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHtml=(value)=>String(value??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const escapeAttr=escapeHtml;
const formatDay=iso=>{const d=new Date(iso||0);return iso&&!isNaN(d.getTime())?d.toLocaleDateString('fr-FR',{day:'numeric',month:'short',year:'numeric'}):'—';};
const today=()=>new Date().toISOString().slice(0,10);
let stories=[],events=[],adminData=null,commitsData=null,ciData=null,csrf=null,nextCursor=null,pendingCreation=null,historyData=null,mediaData=null;
const state={route:'stories',storyId:null,panel:'overview',sceneIndex:0,filter:'Toutes',query:'',journalFilter:'Tout',journalQuery:'',adminTab:'Vue d’ensemble',month:new Date(new Date().getFullYear(),new Date().getMonth(),1),calendarMode:'Mois'};
let editorAction=null,toastTimer;
const persist=()=>{};
const story=id=>stories.find(s=>s.id===id);
const showToast=msg=>{const el=$('#toast');el.textContent=msg;el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,4200)};
const log=()=>{};

const statusLabels={queued:'En écriture',running:'En écriture',waiting_validation:'À relire',approved:'Validée',changes_requested:'À retravailler',failed:'Échec'};
const mapSummary=r=>({id:r.id,title:r.title||r.topic||'Histoire sans titre',
 summary:r.synopsis||'',place:r.landscape||'',status:statusLabels[r.status]||'En écriture',
 rawStatus:r.status,created:r.created_at,updated:r.updated_at||r.created_at,sceneCount:r.scene_count||0,
 cover:/broc[eé]liande|for[eê]t/i.test(r.title||r.topic||'')?'forest':/\bys\b/i.test(r.title||r.topic||'')?'sea':'none',
 characters:[],scenes:[]});
async function api(path,method='GET',payload,extra={}){
 const headers={...extra};
 if(method!=='GET'&&csrf)headers['X-CSRF-Token']=csrf;
 if(payload!==undefined)headers['Content-Type']='application/json';
 let response;
 try{response=await fetch(path,{method,headers,credentials:'same-origin',cache:'no-store',body:payload===undefined?undefined:JSON.stringify(payload)})}
 catch{throw Error('Le serveur local est inaccessible.')}
 const body=await response.json().catch(()=>null);
 if(!response.ok){if(response.status===401){csrf=null;document.querySelector('#studio-shell').hidden=true;document.querySelector('#login-screen').hidden=false}
 const err=Error(typeof body?.detail==='string'?body.detail:'HTTP '+response.status);err.status=response.status;throw err}
 return body;
}
async function fetchStories(more=false){
 if(!more){stories=[];nextCursor=null}
 const result=await api('/studio/api/runs?limit=50'+(nextCursor?'&before='+encodeURIComponent(nextCursor):''));
 const known=new Set(stories.map(x=>x.id));
 for(const row of result.runs||[])if(!known.has(row.id)){stories.push(mapSummary(row));known.add(row.id)}
 nextCursor=result.next_before||null;
 events=stories.map(x=>({id:x.id,date:x.created,type:'creation',title:x.title,detail:'Histoire enregistrée · '+x.status}));
 render();
}

async function launch(){
 try{const session=await api('/studio/session');if(!session.authenticated)return;
 csrf=session.csrf;$('#login-screen').hidden=true;$('#studio-shell').hidden=false;await fetchStories();}
 catch(e){$('#login-error').textContent=e.message}
}
async function loginPrivate(e){
 e.preventDefault();const button=$('#login-submit');button.disabled=true;
 try{const result=await api('/studio/session','POST',{password:$('#login-password').value});
 csrf=result.csrf;$('#login-password').value='';$('#login-screen').hidden=true;$('#studio-shell').hidden=false;
 $('#login-error').textContent='';await fetchStories();
 }catch(err){$('#login-error').textContent=err.message}finally{button.disabled=false}
}
$('#login-form').addEventListener('submit',loginPrivate);
async function loadJournal(){await fetchStories();render()}
async function loadAdmin(){
 try{
  const parts=await Promise.allSettled([
   api('/studio/api/conception'),
   api('/studio/api/conception/commits?limit=70'),
   api('/studio/api/conception/ci?limit=80')
  ]);
  if(parts[0].status!=='fulfilled')throw parts[0].reason;
  adminData=parts[0].value;
  commitsData=parts[1].status==='fulfilled'?parts[1].value:null;
  ciData=parts[2].status==='fulfilled'?parts[2].value:null;
  render();
 }catch(err){adminData=null;$('#content').innerHTML='<div class="api-error">'+escapeHtml(err.message)+' — configuration de lecture GitHub requise.</div>'}
}
function closeMobile(){$('#sidebar').classList.remove('open');$('#shade').classList.remove('open')}
function mapRun(run){
 const board=run.storyboard||{};
 const item=mapSummary(run);
 item.title=board.title||run.brief?.topic||item.title;
 item.summary=board.synopsis||item.summary;
 item.run=run;
 item.characters=board.cast||[];
 item.scenes=(board.scenes||[]).map(scene=>({
 title:scene.title,duration:scene.duration_seconds,narration:scene.narration,
 landscape:scene.landscape,shot:scene.shot,emotion:scene.emotion,sound:scene.sound,
 colors:(scene.colors||[]).join(', '),characters:scene.characters||[],prompt:scene.image_prompt
 }));
 item.sceneCount=item.scenes.length;
 return item;
}
async function navigate(route,storyId=null,panel='overview'){
 state.route=route;state.storyId=storyId;state.panel=panel;state.sceneIndex=0;historyData=null;
 closeMobile();render();window.scrollTo({top:0,behavior:'auto'});
 if(route==='stories'&&storyId){
  try{
   const run=await api('/studio/api/runs/'+encodeURIComponent(storyId));
   const i=stories.findIndex(s=>s.id===storyId);
   if(i>=0)stories[i]=mapRun(run);
   if(state.storyId===storyId)render();
  }catch(e){showToast(e.message);state.storyId=null;render()}
 }
 if(route==='admin')await loadAdmin();
 if(route==='journal')await loadJournal();
}
const btn=(text,icon,cls='',extra='')=>`<button type="button" class="button ${cls}" ${extra}>${icon?ico(icon):''}${escapeHtml(text)}</button>`;
const statusClass=status=>({'En écriture':'writing','À relire':'review','Validée':'valid'}[status]||'');
const statusPill=status=>`<span class="pill ${statusClass(status)}">${escapeHtml(status)}</span>`;
const coverMarkup=(s)=>ASSETS[s.cover]?`<img src="${ASSETS[s.cover]}" alt="Paysage de référence de ${escapeAttr(s.place)}">`:'<div style="height:100%;background:linear-gradient(130deg,#1b4035,#aec4ad)"></div>';
function render(){
 $$('#sidebar .nav-btn').forEach(b=>b.classList.toggle('active',b.dataset.route===state.route));
 $('#nav-count').textContent=stories.length;
 const title=state.route==='stories'?(state.storyId?story(state.storyId)?.title:'Mes histoires'):state.route==='journal'?'Journal de création':'Administration';
 $('#breadcrumb').textContent=title||'Mes histoires';
 $('#content').innerHTML=(state.route==='stories'?(state.storyId?renderAtelier():renderLibrary()):state.route==='journal'?renderJournal():renderAdmin())+'<div class="footer-note"><span>ARVOR — Un atelier pour les histoires qui comptent.</span><span>Studio privé · Données réelles</span></div>';
 bindContent();
}
function renderLibrary(){
 const sceneCount=stories.reduce((a,s)=>a+(s.sceneCount||s.scenes.length),0),elementCount=stories.filter(s=>s.status==='À relire').length;
 return `<div class="page-heading"><div><div class="eyebrow">L’IMAGINAIRE BRETON, EN MOUVEMENT</div><h1>Vos histoires commencent ici.</h1><p>Du premier murmure au dernier plan, imaginez et façonnez chaque détail.</p></div>${btn('Nouvelle histoire','plus','primary','data-action="new"')}</div>
 <section class="stats" aria-label="Statistiques de l’atelier">
 ${[["book",stories.length,"Histoires dans l’atelier"],["film",sceneCount,"Scènes imaginées"],["layers",elementCount,"À valider"],["clock",events.length,"Traces de création"]].map(([ic,n,t])=>`<div class="stat"><div class="stat-icon">${ico(ic)}</div><div><span class="stat-number">${String(n).padStart(2,'0')}</span><span class="stat-label">${t}</span></div></div>`).join('')}</section>
 <div class="toolbar"><div class="filter-tabs" role="group" aria-label="Filtrer par état">${['Toutes','En écriture','À relire','Validée','À retravailler','Échec'].map(v=>`<button type="button" class="filter-btn ${v===state.filter?'active':''}" data-filter="${v}" aria-pressed="${v===state.filter}">${v}</button>`).join('')}</div><label class="searchbox">${ico('search')}<input id="story-search" aria-label="Rechercher une histoire" placeholder="Rechercher une histoire…" value="${escapeAttr(state.query)}" autocomplete="off"></label></div>
 <div id="library-grid" class="story-grid"></div>`;
}
function libraryCards(){
 const el=$('#library-grid');if(!el)return;
 const results=stories.filter(s=>(state.filter==='Toutes'||s.status===state.filter)&&(s.title+' '+s.summary+' '+s.place).toLocaleLowerCase('fr').includes(state.query.toLocaleLowerCase('fr')));
 const cards=results.map(s=>`<article class="story-card"><div class="story-cover">${coverMarkup(s)}<span class="visual-tag">ILLUSTRATION D’AMBIANCE</span></div><div class="card-body"><div class="card-topline"><span class="place">${ico('map')}${escapeHtml(s.place)}</span>${statusPill(s.status)}</div><h3 class="card-title">${escapeHtml(s.title)}</h3><p class="card-summary">${escapeHtml(s.summary)}</p><div class="card-data"><span>${ico('film')}${(s.sceneCount||s.scenes.length)} scène${s.scenes.length>1?'s':''}</span><span>${ico('layers')}${s.sceneCount||s.scenes.length} éléments</span></div></div><div class="card-bottom"><span>Modifiée le ${formatDay(s.updated)}</span><button type="button" data-open="${escapeAttr(s.id)}">Ouvrir l’histoire ${ico('arrow')}</button></div></article>`).join('');
 el.innerHTML=cards+`<div class="create-tile"><div class="create-icon">${ico('plus')}</div><h3>La prochaine légende ?</h3><p>Une idée, un lieu, une voix. Commencez un nouveau récit.</p>${btn('Créer une histoire','arrow','textual','data-action="new"')}</div>`;
}
const atelierMenu=[['overview','Vue d’ensemble','book'],['scenario','Scénario','file'],['scenes','Scènes','film'],['characters','Personnages','users'],['landscapes','Paysages','map'],['colors','Couleurs','palette'],['shots','Plans & cadrages','grid'],['emotions','Émotions','shield'],['sounds','Sons & voix','mic'],['media','Médias','image'],['history','Historique IA','clock']];
function renderAtelier(){
 const s=story(state.storyId);if(!s)return '<div class="empty-state">Histoire introuvable.</div>';
 const counts={scenes:s.scenes.length,characters:s.characters.length,landscapes:s.scenes.length,colors:s.scenes.length,shots:s.scenes.length,emotions:s.scenes.length,sounds:s.scenes.length};
 return `<div class="backline"><button type="button" data-action="library">${ico('left')} Toutes les histoires</button><div class="right-tools">${btn('Exporter','download','', 'data-action="export"')}${btn('Modifier','edit','primary','data-action="edit-story"')}</div></div>
 <section class="story-banner">${coverMarkup(s)}<div class="banner-content"><span class="eyebrow">ATELIER / HISTOIRE</span><h1>${escapeHtml(s.title)}</h1><p>${escapeHtml(s.summary)}</p><div class="mini-meta"><span>⌖ ${escapeHtml(s.place)}</span><span>${s.scenes.length} scène${s.scenes.length>1?'s':''}</span><span>${escapeHtml(s.status)}</span></div></div></section>
 <div class="workshop"><aside class="outline" aria-label="Contenu de l’histoire"><div class="outline-title">COMPOSER LE RÉCIT</div><nav class="outline-nav">${atelierMenu.map(([k,n,ic])=>`<button type="button" class="outline-btn ${state.panel===k?'active':''}" data-panel="${k}">${ico(ic)}${n}${counts[k]!==undefined?`<span class="num">${counts[k]}</span>`:''}</button>`).join('')}</nav><div class="outline-sep"></div><div class="outline-hint">Chaque révision est conservée et nécessite une validation humaine.</div></aside><div class="workbench" id="workbench">${renderAtelierPanel(s)}</div></div>`;
}
const panelHeader=(label,title,desc,act='')=>`<div class="section-head"><div><div class="eyebrow">${label}</div><h2>${title}</h2><p>${desc}</p></div>${act}</div>`;
function sceneRows(s){return `<div class="scene-list">${s.scenes.map((sc,i)=>`<button class="scene-row" type="button" data-scene="${i}"><span class="scene-index">${String(i+1).padStart(2,'0')}</span><span><b>${escapeHtml(sc.title)}</b><small>${escapeHtml(sc.landscape)} · ${sc.duration} s</small></span><span class="arrow">${ico('arrow')}</span></button>`).join('')||'<p class="muted">Aucune scène pour le moment.</p>'}</div>`}
function renderMedia(st){
 const visuals=mediaData?.visuals?.scenes||[],catalog=mediaData?.media?.media||[];
 const images=visuals.map(item=>`<article class="item-card"><div class="eyebrow">SCÈNE ${item.scene_number}</div>
  <strong>${escapeHtml(item.title)}</strong>
  ${item.image_status==='ready'?`<img style="width:100%;border-radius:7px" loading="lazy" alt="Illustration privée" src="/studio/api/runs/${encodeURIComponent(st.id)}/scenes/${item.scene_number}/image">`:'<p>Image non générée ou indisponible.</p>'}
  <small>${escapeHtml(item.image_status)}</small></article>`).join('');
 const records=catalog.map(x=>`<div class="mini-row"><b>${escapeHtml(x.kind)}</b><span>${Number(x.size_bytes)||0} octets · SHA256 ${escapeHtml((x.sha256||'').slice(0,16))}…</span></div>`).join('');
 return panelHeader('PRODUCTION','Images et médias','Uniquement les fichiers réellement associés à cette histoire.')
 +`<div class="panel"><h3>Illustrations</h3><div class="item-grid">${images||'<p>Images absentes du catalogue.</p>'}</div></div>
 <div class="panel"><h3>Catalogue des médias</h3>${records||'<p>Aucune voix, vidéo ou sous-titre répertorié.</p>'}</div>`;
}
async function loadMedia(){
 const id=state.storyId;if(!id)return;
 try{
  const [visuals,media]=await Promise.all([api('/studio/api/runs/'+encodeURIComponent(id)+'/visuals'),api('/studio/api/runs/'+encodeURIComponent(id)+'/media')]);
  if(state.storyId===id&&state.panel==='media'){mediaData={visuals,media};render()}
 }catch(e){showToast('Catalogue indisponible : '+e.message)}
}
function renderHistory(){
 const steps=historyData?.steps||[];
 return panelHeader('MÉMOIRE ÉDITORIALE','Historique des traitements','Prompts, résultats et erreurs issus de la chaîne IA.')
  +`<section class="panel">${steps.length?steps.map((item,i)=>`<details class="mini-row"><summary>Étape ${i+1} · ${escapeHtml(item.order===0?'Analyse':'Storyboard')}</summary><h4>Prompt</h4><pre>${escapeHtml(typeof item.prompt==='string'?item.prompt:JSON.stringify(item.prompt,null,2))}</pre><h4>Sortie structurée</h4><pre>${escapeHtml(typeof item.parsed==='string'?item.parsed:JSON.stringify(item.parsed,null,2))}</pre></details>`).join(''):'<p>Aucun traitement chargé.</p>'}</section>`;
}
async function loadHistory(){
 const id=state.storyId;
 try{const response=await api('/studio/api/runs/'+encodeURIComponent(id)+'/history');
 if(state.storyId===id&&state.panel==='history'){historyData=response;render()}
 }catch(err){showToast(err.message)}
}
function renderAtelierPanel(s){
 const k=state.panel;
 if(k==='overview')return panelHeader('LA TRAME DE VOTRE RÉCIT','Une histoire, tout un univers.','Un aperçu clair de votre narration, de vos scènes et de votre distribution.')+`<div class="panel-grid"><div><section class="panel"><div class="eyebrow">SYNOPSIS</div><h3 style="margin-top:9px">L’essentiel du récit</h3><p>${escapeHtml(s.summary)}</p>${btn('Modifier le synopsis','edit','small','data-action="edit-story"')}</section><section class="panel"><div class="section-head"><div><div class="eyebrow">DÉCOUPAGE</div><h3 style="margin:7px 0">Le fil des scènes</h3></div>${btn('Ajouter une scène','plus','small','data-action="add-scene"')}</div>${sceneRows(s)}</section></div><div><section class="panel"><div class="eyebrow">FICHE ÉDITORIALE</div><h3 style="margin:9px 0">Repères</h3>${[['Univers',s.place],['Statut',s.status],['Scènes',s.scenes.length],['Dernière édition',formatDay(s.updated)]].map(([n,v])=>`<div class="mini-row"><b>${n}</b><span>${escapeHtml(v)}</span></div>`).join('')}</section><section class="panel"><div class="eyebrow">DISTRIBUTION</div><h3 style="margin:9px 0">Personnages</h3>${s.characters.map(p=>`<div class="mini-row"><b>${escapeHtml(p.name)}</b><span>${escapeHtml(p.role)}</span></div>`).join('')||'<p>Personnages à créer.</p>'}</section></div></div>`;
 if(k==='scenario')return panelHeader('ÉCRITURE','Le scénario','L’intention narrative et le découpage de votre histoire.',btn('Modifier','edit','small','data-action="edit-story"'))+`<section class="panel"><div class="eyebrow">SYNOPSIS DU RÉCIT</div><h3 style="margin-top:11px">${escapeHtml(s.title)}</h3><p>${escapeHtml(s.summary)}</p><div class="mini-row"><b>Cadre de l’histoire</b><span>${escapeHtml(s.place)}</span></div></section><section class="panel"><h3>Découpage scène par scène</h3>${sceneRows(s)}</section>`;
 if(k==='scenes'){
  const sc=s.scenes[state.sceneIndex];
  return panelHeader('SCÉNOGRAPHIE','Les scènes','Travaillez le récit plan par plan.',btn('Ajouter une scène','plus','small','data-action="add-scene"'))+`<section class="panel">${sceneRows(s)}</section>`+(sc?`<section class="panel"><div class="section-head"><div><div class="eyebrow">SCÈNE ${String(state.sceneIndex+1).padStart(2,'0')}</div><h3 style="margin:8px 0">${escapeHtml(sc.title)}</h3><p>${sc.duration} secondes · ${escapeHtml(sc.landscape)}</p></div>${btn('Modifier','edit','small','data-action="edit-scene"')}</div><div class="property-grid">${[['Narration',sc.narration],['Décor & atmosphère',sc.landscape],['Plan / cadrage',sc.shot],['Émotion',sc.emotion],['Sons / voix',sc.sound],['Palette',sc.colors],['Personnages',sc.characters.join(', ')],['Prompt image',sc.prompt]].map(([k,v])=>`<div class="property"><small>${k}</small><p>${escapeHtml(v||'À définir')}</p></div>`).join('')}</div></section>`:'<div class="empty-state">Ajoutez votre première scène.</div>');
 }
 if(k==='characters')return panelHeader('CONTINUITÉ NARRATIVE','Les personnages','Gardez une identité cohérente d’une scène à l’autre.')+(s.characters.length?`<div class="person-grid">${s.characters.map(p=>`<article class="person"><div class="initial">${escapeHtml(p.name[0])}</div><h3>${escapeHtml(p.name)}</h3><p><b>${escapeHtml(p.role)}</b></p><p style="margin-top:13px">${escapeHtml(p.appearance)}</p></article>`).join('')}</div>`:'<div class="empty-state">Aucun personnage enregistré.</div>');
 if(k==='history')return renderHistory();
 if(k==='media')return renderMedia(s);
 const map={landscapes:['PAYSAGES','Décors et paysages','landscape'],colors:['DIRECTION ARTISTIQUE','Palettes de couleurs','colors'],shots:['MISE EN SCÈNE','Plans et cadrages','shot'],emotions:['ÉMOTIONS','Intentions émotionnelles','emotion'],sounds:['BANDE SON','Voix et ambiances','sound']};
 if(map[k]){const [ey,title,field]=map[k];return panelHeader(ey,title,'Retrouvez ces éléments dans leur contexte narratif.')+`<div class="item-grid">${s.scenes.map((sc,i)=>`<article class="item-card"><span class="eyebrow">SCÈNE ${String(i+1).padStart(2,'0')}</span><strong>${escapeHtml(sc.title)}</strong><p>${escapeHtml(sc[field]||'À définir')}</p>${btn('Voir la scène','arrow','small','data-scene="'+i+'"')}</article>`).join('')||'<div class="empty-state">Aucun élément.</div>'}</div>`}
 return '';
}
function renderJournal(){
 const rows=events.filter(e=>(state.journalFilter==='Tout'||e.type===state.journalFilter)&&(e.title+' '+e.detail).toLowerCase().includes(state.journalQuery.toLowerCase())).sort((a,b)=>b.date.localeCompare(a.date)||b.id-a.id);
 return `<div class="page-heading"><div><div class="eyebrow">RIEN NE SE PERD</div><h1>La mémoire de vos créations.</h1><p>Retrouvez les décisions, les versions et les étapes de chaque récit.</p></div></div><div class="toolbar"><div class="filter-tabs">${[['Tout','Tout'],['Créations','creation'],['Révisions','revision'],['IA & visuels','ia']].map(([name,k])=>`<button class="filter-btn ${state.journalFilter===k?'active':''}" data-journal-filter="${k}">${name}</button>`).join('')}</div><label class="searchbox">${ico('search')}<input id="journal-search" aria-label="Rechercher dans le journal" placeholder="Rechercher une trace…" value="${escapeAttr(state.journalQuery)}"></label></div><section class="panel"><div class="eyebrow">ÉVÉNEMENTS CHARGÉS</div><div id="timeline" class="timeline">${rows.map(e=>`<article class="timeline-row"><time>${formatDay(e.date)}</time><h3>${escapeHtml(e.title)}</h3><p>${escapeHtml(e.detail)}</p>${statusPill(({creation:'Brouillon',revision:'En écriture',ia:'À relire'})[e.type]||'Brouillon')}</article>`).join('')||'<div class="empty-state">Aucune trace correspondante.</div>'}</div></section>`;
}
function renderAdmin(){
 const tab=state.adminTab;
 return `<div class="page-heading"><div><div class="eyebrow">CONCEPTION · CODE · TRAÇABILITÉ</div><h1>Le projet, en toute clarté.</h1><p>Épics, pull requests, commits et livraisons issus de GitHub.</p></div></div>
 <div class="admin-tabs" role="tablist" aria-label="Sections administration">
 ${['Vue d’ensemble','Epics & stories','Pull requests','Commits','Agenda'].map(t=>`<button type="button" role="tab" aria-selected="${tab===t}" class="admin-tab ${tab===t?'active':''}" data-admin-tab="${escapeAttr(t)}">${t}</button>`).join('')}</div>
 <div id="admin-stage">${adminData?renderAdminTab(tab):'<div class="loading-view">Chargement du suivi GitHub privé…</div>'}</div>`;
}
function renderAdminTab(tab){
 const epics=adminData?.epics||[],issues=adminData?.issues||[],prs=adminData?.pull_requests||[],deliveries=adminData?.deliveries||[];
 const commits=commitsData?.commits||[];
 if(tab==='Vue d’ensemble'){
  const stats=[['grid',epics.length,'Epics'],['book',issues.length,'Issues chargées'],['file',prs.filter(x=>x.state==='open').length,'PR ouvertes'],['check',deliveries.filter(x=>x.conclusion==='failure').length,'Livraisons en échec']];
  return `<section class="stats">${stats.map(([ic,n,label])=>`<div class="stat"><span class="stat-icon">${ico(ic)}</span><div><span class="stat-number">${n}</span><span class="stat-label">${label}</span></div></div>`).join('')}</section>
  <div class="admin-grid"><section class="panel"><div class="eyebrow">AVANCEMENT VÉRIFIABLE</div><h3>Les epics</h3>${epics.slice(0,12).map(e=>`<div class="mini-row"><b>#${e.number} · ${escapeHtml(e.title)}</b><small>${Number.isInteger(e.progress_pct)?e.checklist_done+'/'+e.checklist_total+' critères · '+e.progress_pct+' %':'Aucune checklist mesurable'}</small>${Number.isInteger(e.progress_pct)?`<progress class="progress" value="${e.progress_pct}" max="100"></progress>`:''}</div>`).join('')}</section>
  <section class="panel"><div class="eyebrow">LES DERNIÈRES TRACES</div><h3>Pull requests</h3>${prs.slice(0,9).map(p=>`<div class="mini-row"><b>PR #${p.number} · ${p.merged_at?'Fusionnée':p.state==='open'?'Ouverte':'Fermée'}</b><span>${escapeHtml(p.title)}</span></div>`).join('')}</section></div>`;
 }
 if(tab==='Epics & stories')return adminTable('Épics et tâches GitHub',['Ticket','Titre','État'],issues.map(i=>['#'+i.number,i.title,i.state]));
 if(tab==='Pull requests')return adminTable('Pull requests',['PR','Objet','État'],prs.map(p=>['#'+p.number,p.title,p.merged_at?'Fusionnée':p.draft?'Brouillon':p.state]));
 if(tab==='Commits')return adminTable('Commits réels de main',['SHA','Message','Date'],commits.map(c=>[(c.sha||'').slice(0,10),c.message,formatDay(c.when)]));
 return renderCalendar();
}
function adminTable(title,cols,rows){
 return `<section class="panel"><h3>${escapeHtml(title)}</h3><div class="admin-table-wrap"><table class="mini-table"><thead><tr>${cols.map(x=>`<th>${escapeHtml(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${escapeHtml(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${!rows.length?'<p>Aucune donnée disponible dans les résultats chargés.</p>':''}</section>`;
}
function renderCalendar(){
 const month=state.month;
 const events=[];
 for(const p of adminData?.pull_requests||[]){
  if(p.created_at)events.push({date:p.created_at,text:'PR #'+p.number+' ouverte'});
  if(p.merged_at)events.push({date:p.merged_at,text:'PR #'+p.number+' fusionnée'});
 }
 for(const d of adminData?.deliveries||[])if(d.updated_at&&d.conclusion==='success')
  events.push({date:d.updated_at,text:'Livraison vérifiée '+(d.sha||'').slice(0,8)});
 for(const c of commitsData?.commits||[])if(c.when)events.push({date:c.when,text:'Commit '+(c.sha||'').slice(0,8)});
 const days=[];
 if(state.calendarMode==='Jour')days.push(new Date(month));
 else if(state.calendarMode==='Semaine'){
  const d=new Date(month);d.setDate(d.getDate()-((d.getDay()+6)%7));
  for(let n=0;n<7;n++){days.push(new Date(d));d.setDate(d.getDate()+1)}
 }else{
  const d=new Date(month.getFullYear(),month.getMonth(),1);
  d.setDate(d.getDate()-((d.getDay()+6)%7));
  const end=new Date(month.getFullYear(),month.getMonth()+1,0);
  while(d<=end||days.length%7){days.push(new Date(d));d.setDate(d.getDate()+1)}
 }
 const key=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
 return `<section class="panel"><div class="calendar-toolbar"><div class="cal-nav">${btn('','left','small','data-cal="prev"')}<strong>${month.toLocaleDateString('fr-FR',{month:'long',year:'numeric'})}</strong>${btn('','arrow','small','data-cal="next"')}</div><div class="filter-tabs">${['Mois','Semaine','Jour'].map(v=>`<button class="filter-btn ${v===state.calendarMode?'active':''}" data-calendar-mode="${v}">${v}</button>`).join('')}</div></div>
 <div class="calendar">${state.calendarMode==='Jour'?'':['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'].map(x=>`<div class="cal-week">${x}</div>`).join('')}${days.map(d=>`<div class="cal-day">${d.getDate()}${events.filter(e=>key(new Date(e.date))===key(d)).slice(0,4).map(e=>`<span class="cal-event">${escapeHtml(e.text)}</span>`).join('')}</div>`).join('')}</div>
 <p class="muted">Événements datés renvoyés par GitHub. Historique potentiellement partiel.</p></section>`;
}
function bindContent(){
 $$('[data-action="new"]').forEach(x=>x.addEventListener('click',()=>openEditor('new')));
 $$('[data-action="library"]').forEach(x=>x.addEventListener('click',()=>navigate('stories')));
 $$('[data-action="edit-story"]').forEach(x=>x.addEventListener('click',()=>openEditor('story')));
 $$('[data-action="edit-scene"]').forEach(x=>x.addEventListener('click',()=>openEditor('scene')));
 $$('[data-action="add-scene"]').forEach(x=>x.addEventListener('click',()=>openEditor('add-scene')));
 $$('[data-action="export"]').forEach(x=>x.addEventListener('click',exportStory));
 $$('[data-open]').forEach(x=>x.addEventListener('click',()=>navigate('stories',x.dataset.open)));
 $$('[data-panel]').forEach(x=>x.addEventListener('click',()=>{state.panel=x.dataset.panel;mediaData=null;render();if(state.panel==='media')loadMedia();if(state.panel==='history')loadHistory()}));
 $$('[data-scene]').forEach(x=>x.addEventListener('click',()=>{state.sceneIndex=Number(x.dataset.scene);state.panel='scenes';render()}));
 $$('[data-filter]').forEach(x=>x.addEventListener('click',()=>{state.filter=x.dataset.filter;render()}));
 if($('#story-search')){libraryCards();bindLibraryOpen();$('#story-search').addEventListener('input',e=>{state.query=e.target.value;libraryCards();bindLibraryOpen()})}
 if($('#journal-search'))$('#journal-search').addEventListener('input',e=>{state.journalQuery=e.target.value;const active=document.activeElement;const caret=e.target.selectionStart;render();const inp=$('#journal-search');inp.focus();inp.setSelectionRange(caret,caret)});
 $$('[data-journal-filter]').forEach(x=>x.addEventListener('click',()=>{state.journalFilter=x.dataset.journalFilter;render()}));
 $$('[data-admin-tab]').forEach(x=>x.addEventListener('click',()=>{state.adminTab=x.dataset.adminTab;render()}));
 $$('[data-calendar-mode]').forEach(x=>x.addEventListener('click',()=>{state.calendarMode=x.dataset.calendarMode;render()}));
 $$('[data-cal]').forEach(x=>x.addEventListener('click',()=>{const d=state.month;const delta=x.dataset.cal==='prev'?-1:1;if(state.calendarMode==='Mois')d.setMonth(d.getMonth()+delta);else d.setDate(d.getDate()+delta*(state.calendarMode==='Semaine'?7:1));state.month=new Date(d);render()}));
}
function bindLibraryOpen(){ $$('[data-open]').forEach(x=>{const b=x.cloneNode(true);x.replaceWith(b);b.addEventListener('click',()=>navigate('stories',b.dataset.open))});$$('#library-grid [data-action="new"]').forEach(x=>{const b=x.cloneNode(true);x.replaceWith(b);b.addEventListener('click',()=>openEditor('new'))}) }
function fields(rows){$('#editor-fields').innerHTML=rows.map(([k,label,value,kind,choices])=>`<div class="field"><label for="edit-${k}">${escapeHtml(label)}</label>${kind==='select'?`<select id="edit-${k}" name="${k}">${choices.map(c=>`<option value="${escapeAttr(c)}" ${value===c?'selected':''}>${escapeHtml(c)}</option>`).join('')}</select>`:kind==='textarea'?`<textarea id="edit-${k}" name="${k}" rows="4" required>${escapeHtml(value||'')}</textarea>`:`<input id="edit-${k}" name="${k}" value="${escapeAttr(value||'')}" ${kind==='number'?'type="number" min="1" max="180"':'type="text"'} required maxlength="300">`}</div>`).join('');}
function openEditor(mode){
 if(mode==='add-scene'){showToast('Le nombre de scènes est fixé par le brief initial. Révisez les scènes existantes.');return}
 const current=story(state.storyId);
 if(mode!=='new'&&(!current?.run?.storyboard||!['approved','waiting_validation','changes_requested'].includes(current.rawStatus))){
  showToast('Révision indisponible avant la génération du storyboard.');return
 }
 const s=story(state.storyId),sc=s?.scenes[state.sceneIndex];editorAction=mode;
 let rows=[];let title='';let kick='RÉVISION HISTORISÉE';
 if(mode==='new'){title='Créer une histoire';rows=[['topic','Sujet de la légende','','textarea'],['duration_seconds','Durée totale (s)',60,'number'],['scene_count','Nombre de scènes',3,'number']];}
 if(mode==='story'){title='Modifier le récit';rows=[['title','Titre de l’histoire',s.title,'text'],['place','Lieu / univers',s.place,'text'],['summary','Synopsis',s.summary,'textarea']];}
 if(mode==='scene'||mode==='add-scene'){title=mode==='scene'?'Modifier la scène':'Nouvelle scène';const v=mode==='scene'?sc:{};rows=[['title','Titre',v.title,'text'],['duration','Durée (secondes)',v.duration||20,'number'],['narration','Narration',v.narration,'textarea'],['landscape','Décor',v.landscape,'textarea'],['shot','Plan / cadrage',v.shot,'text'],['emotion','Émotion',v.emotion,'text'],['sound','Sons et voix',v.sound,'text'],['colors','Palette',v.colors,'text'],['prompt','Prompt d’image',v.prompt,'textarea']];}
 $('#editor-title').textContent=title;$('#editor-kicker').textContent=kick;fields(rows);$('#editor').showModal();
 $('#editor-fields input, #editor-fields textarea, #editor-fields select')?.focus();
}
async function createRemote(input){
 const brief={topic:(input.topic||'').trim(),genre:'legend',duration_seconds:Number(input.duration_seconds),
 scene_count:Number(input.scene_count),audience:'Grand public',tone:'Narratif et accessible',sources:[]};
 if(!brief.topic||brief.duration_seconds<15||brief.duration_seconds>180||brief.scene_count<1||brief.scene_count>6)throw Error('Brief invalide : 15 à 180 secondes et 1 à 6 scènes.');
 const fingerprint=JSON.stringify(brief);
 if(!pendingCreation||pendingCreation.fingerprint!==fingerprint)pendingCreation={fingerprint,key:crypto.randomUUID()};
 const run=await api('/studio/api/runs','POST',brief,{'Idempotency-Key':pendingCreation.key});
 if(!['queued','running'].includes(run.status))pendingCreation=null;
 $('#editor').close();await fetchStories();await navigate('stories',run.id);
 showToast('Histoire enregistrée. Vérifiez et validez les propositions de l’IA.');
}
function revisionDocument(run){
 const board=run.storyboard||{};
 return {
 title:board.title||'',synopsis:board.synopsis||'',
 cast:(board.cast||[]).map(x=>({name:x.name,appearance:x.appearance,personality:x.personality,role:x.role})),
 scenes:(board.scenes||[]).map(x=>({
  title:x.title,duration_seconds:x.duration_seconds,narration:x.narration,
  visual_description:x.visual_description,characters:x.characters||[],
  landscape:x.landscape,colors:x.colors||[],shot:x.shot,emotion:x.emotion,
  sound:x.sound,image_prompt:x.image_prompt
 }))
 };
}
async function reviseRemote(input){
 const st=story(state.storyId),run=st?.run;
 if(!run?.storyboard||!['approved','waiting_validation','changes_requested'].includes(run.status))throw Error('Aucune version éditable.');
 const board=revisionDocument(run);
 if(editorAction==='story'){
  board.title=(input.title||'').trim();board.synopsis=(input.summary||'').trim();
  if(input.place?.trim()&&board.scenes.length)board.scenes[0].landscape=input.place.trim();
 }else{
  const scene=board.scenes[state.sceneIndex];if(!scene)throw Error('Scène introuvable.');
  scene.title=input.title.trim();scene.duration_seconds=Number(input.duration);
  scene.narration=input.narration.trim();scene.landscape=input.landscape.trim();
  scene.shot=input.shot.trim();scene.emotion=input.emotion.trim();scene.sound=input.sound.trim();
  scene.colors=(input.colors||'').split(',').map(x=>x.trim()).filter(Boolean);
  scene.image_prompt=input.prompt.trim();
 }
 const duration=board.scenes.reduce((total,x)=>total+x.duration_seconds,0);
 if(duration!==run.brief.duration_seconds)throw Error('La durée totale doit rester à '+run.brief.duration_seconds+' secondes.');
 const payload={action:'revise',expected_revision:run.review_revision||0,comment:'Révision depuis le Studio Arvor',revised_output:board};
 const saved=await api('/studio/api/runs/'+encodeURIComponent(st.id)+'/steps/storyboard/review','POST',payload);
 stories[stories.findIndex(x=>x.id===st.id)]=mapRun(saved);
 $('#editor').close();render();showToast('Nouvelle version enregistrée. Validation requise.');
}
async function saveRemoteEditor(input){
 try{
  if(editorAction==='new')await createRemote(input);
  else if(editorAction==='story'||editorAction==='scene')await reviseRemote(input);
  else showToast('Ajout autonome de scène non disponible : le nombre de scènes est fixé par le brief.');
 }catch(error){showToast('Enregistrement refusé : '+error.message)}
}
async function saveEditor(e){e.preventDefault();const input=Object.fromEntries(new FormData($('#editor-form')).entries());await saveRemoteEditor(input)}
function exportStory(){
 const st=story(state.storyId);if(!st?.run?.storyboard){showToast('Aucun scénario généré à exporter.');return}
 const data={format:'arvor-storyboard-v1',exported_at:new Date().toISOString(),run_id:st.id,
  status:st.rawStatus,review_revision:st.run.review_revision,brief:st.run.brief,storyboard:st.run.storyboard};
 const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob),link=document.createElement('a');
 link.href=url;link.download='arvor-'+st.id+'.json';document.body.append(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1000);showToast('Export du storyboard courant préparé.');
}
$$('[data-route]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.route)));
$('#side-create').addEventListener('click',()=>{closeMobile();openEditor('new')});
$('#mobile-toggle').addEventListener('click',()=>{$('#sidebar').classList.toggle('open');$('#shade').classList.toggle('open')});
$('#shade').addEventListener('click',closeMobile);
$('#editor-close').addEventListener('click',()=>$('#editor').close());
$('#editor-cancel').addEventListener('click',()=>$('#editor').close());
$('#editor-form').addEventListener('submit',saveEditor);
$('#help').addEventListener('click',()=>showToast('Atelier privé connecté à vos services. Les créations nécessitent votre validation.'));
window.addEventListener('keydown',e=>{if(e.key==='Escape')closeMobile();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();navigate('stories');$('#story-search')?.focus()}});
launch();
})();
