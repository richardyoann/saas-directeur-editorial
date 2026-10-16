
(() => {
'use strict';
// ARVOR / STUDIO: authenticated adapter being tested.
const ASSETS={forest:'/studio/assets/arvor_forest.jpg',sea:'/studio/assets/arvor_sea.jpg'};
const $=selector=>document.querySelector(selector);
const $$=selector=>[...document.querySelectorAll(selector)];
const ico=(name)=>`<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHtml=(value)=>String(value??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const escapeAttr=escapeHtml;
const formatDay=iso=>{const d=new Date((iso||'2026-10-09')+'T12:00:00');return Number.isFinite(d.getTime())?d.toLocaleDateString('fr-FR',{day:'numeric',month:'short',year:'numeric'}):'—';};
const today=()=>new Date().toISOString().slice(0,10);
let stories=[],events=[],adminData=null,commitsData=null,ciData=null,csrf=null,nextCursor=null,pendingCreation=null;
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
 state.route=route;state.storyId=storyId;state.panel=panel;state.sceneIndex=0;
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
 const cards=results.map(s=>`<article class="story-card"><div class="story-cover">${coverMarkup(s)}<span class="visual-tag">ILLUSTRATION D’AMBIANCE</span></div><div class="card-body"><div class="card-topline"><span class="place">${ico('map')}${escapeHtml(s.place)}</span>${statusPill(s.status)}</div><h3 class="card-title">${escapeHtml(s.title)}</h3><p class="card-summary">${escapeHtml(s.summary)}</p><div class="card-data"><span>${ico('film')}${s.scenes.length} scène${s.scenes.length>1?'s':''}</span><span>${ico('layers')}${s.scenes.length*7+s.characters.length} éléments</span></div></div><div class="card-bottom"><span>Modifiée le ${formatDay(s.updated)}</span><button type="button" data-open="${escapeAttr(s.id)}">Ouvrir l’histoire ${ico('arrow')}</button></div></article>`).join('');
 el.innerHTML=cards+`<div class="create-tile"><div class="create-icon">${ico('plus')}</div><h3>La prochaine légende ?</h3><p>Une idée, un lieu, une voix. Commencez un nouveau récit.</p>${btn('Créer une histoire','arrow','textual','data-action="new"')}</div>`;
}
const atelierMenu=[['overview','Vue d’ensemble','book'],['scenario','Scénario','file'],['scenes','Scènes','film'],['characters','Personnages','users'],['landscapes','Paysages','map'],['colors','Couleurs','palette'],['shots','Plans & cadrages','grid'],['emotions','Émotions','shield'],['sounds','Sons & voix','mic'],['media','Médias','image']];
function renderAtelier(){
 const s=story(state.storyId);if(!s)return '<div class="empty-state">Histoire introuvable.</div>';
 const counts={scenes:s.scenes.length,characters:s.characters.length,landscapes:s.scenes.length,colors:s.scenes.length,shots:s.scenes.length,emotions:s.scenes.length,sounds:s.scenes.length};
 return `<div class="backline"><button type="button" data-action="library">${ico('left')} Toutes les histoires</button><div class="right-tools">${btn('Exporter','download','', 'data-action="export"')}${btn('Modifier','edit','primary','data-action="edit-story"')}</div></div>
 <section class="story-banner">${coverMarkup(s)}<div class="banner-content"><span class="eyebrow">ATELIER / HISTOIRE</span><h1>${escapeHtml(s.title)}</h1><p>${escapeHtml(s.summary)}</p><div class="mini-meta"><span>⌖ ${escapeHtml(s.place)}</span><span>${s.scenes.length} scène${s.scenes.length>1?'s':''}</span><span>${escapeHtml(s.status)}</span></div></div></section>
 <div class="workshop"><aside class="outline" aria-label="Contenu de l’histoire"><div class="outline-title">COMPOSER LE RÉCIT</div><nav class="outline-nav">${atelierMenu.map(([k,n,ic])=>`<button type="button" class="outline-btn ${state.panel===k?'active':''}" data-panel="${k}">${ico(ic)}${n}${counts[k]!==undefined?`<span class="num">${counts[k]}</span>`:''}</button>`).join('')}</nav><div class="outline-sep"></div><div class="outline-hint">Chaque révision est conservée et nécessite une validation humaine.</div></aside><div class="workbench" id="workbench">${renderAtelierPanel(s)}</div></div>`;
}
const panelHeader=(label,title,desc,act='')=>`<div class="section-head"><div><div class="eyebrow">${label}</div><h2>${title}</h2><p>${desc}</p></div>${act}</div>`;
function sceneRows(s){return `<div class="scene-list">${s.scenes.map((sc,i)=>`<button class="scene-row" type="button" data-scene="${i}"><span class="scene-index">${String(i+1).padStart(2,'0')}</span><span><b>${escapeHtml(sc.title)}</b><small>${escapeHtml(sc.landscape)} · ${sc.duration} s</small></span><span class="arrow">${ico('arrow')}</span></button>`).join('')||'<p class="muted">Aucune scène pour le moment.</p>'}</div>`}
function renderAtelierPanel(s){
 const k=state.panel;
 if(k==='overview')return panelHeader('LA TRAME DE VOTRE RÉCIT','Une histoire, tout un univers.','Un aperçu clair de votre narration, de vos scènes et de votre distribution.')+`<div class="panel-grid"><div><section class="panel"><div class="eyebrow">SYNOPSIS</div><h3 style="margin-top:9px">L’essentiel du récit</h3><p>${escapeHtml(s.summary)}</p>${btn('Modifier le synopsis','edit','small','data-action="edit-story"')}</section><section class="panel"><div class="section-head"><div><div class="eyebrow">DÉCOUPAGE</div><h3 style="margin:7px 0">Le fil des scènes</h3></div>${btn('Ajouter une scène','plus','small','data-action="add-scene"')}</div>${sceneRows(s)}</section></div><div><section class="panel"><div class="eyebrow">FICHE ÉDITORIALE</div><h3 style="margin:9px 0">Repères</h3>${[['Univers',s.place],['Statut',s.status],['Scènes',s.scenes.length],['Dernière édition',formatDay(s.updated)]].map(([n,v])=>`<div class="mini-row"><b>${n}</b><span>${escapeHtml(v)}</span></div>`).join('')}</section><section class="panel"><div class="eyebrow">DISTRIBUTION</div><h3 style="margin:9px 0">Personnages</h3>${s.characters.map(p=>`<div class="mini-row"><b>${escapeHtml(p.name)}</b><span>${escapeHtml(p.role)}</span></div>`).join('')||'<p>Personnages à créer.</p>'}</section></div></div>`;
 if(k==='scenario')return panelHeader('ÉCRITURE','Le scénario','L’intention narrative et le découpage de votre histoire.',btn('Modifier','edit','small','data-action="edit-story"'))+`<section class="panel"><div class="eyebrow">SYNOPSIS DU RÉCIT</div><h3 style="margin-top:11px">${escapeHtml(s.title)}</h3><p>${escapeHtml(s.summary)}</p><div class="mini-row"><b>Cadre de l’histoire</b><span>${escapeHtml(s.place)}</span></div></section><section class="panel"><h3>Découpage scène par scène</h3>${sceneRows(s)}</section>`;
 if(k==='scenes'){
  const sc=s.scenes[state.sceneIndex];
  return panelHeader('SCÉNOGRAPHIE','Les scènes','Travaillez le récit plan par plan.',btn('Ajouter une scène','plus','small','data-action="add-scene"'))+`<section class="panel">${sceneRows(s)}</section>`+(sc?`<section class="panel"><div class="section-head"><div><div class="eyebrow">SCÈNE ${String(state.sceneIndex+1).padStart(2,'0')}</div><h3 style="margin:8px 0">${escapeHtml(sc.title)}</h3><p>${sc.duration} secondes · ${escapeHtml(sc.landscape)}</p></div>${btn('Modifier','edit','small','data-action="edit-scene"')}</div><div class="property-grid">${[['Narration',sc.narration],['Décor & atmosphère',sc.landscape],['Plan / cadrage',sc.shot],['Émotion',sc.emotion],['Sons / voix',sc.sound],['Palette',sc.colors],['Personnages',sc.characters.join(', ')],['Prompt image',sc.prompt]].map(([k,v])=>`<div class="property"><small>${k}</small><p>${escapeHtml(v||'À définir')}</p></div>`).join('')}</div></section>`:'<div class="empty-state">Ajoutez votre première scène.</div>');
 }
 if(k==='characters')return panelHeader('CONTINUITÉ NARRATIVE','Les personnages','Gardez une identité cohérente d’une scène à l’autre.')+(s.characters.length?`<div class="person-grid">${s.characters.map(p=>`<article class="person"><div class="initial">${escapeHtml(p.name[0])}</div><h3>${escapeHtml(p.name)}</h3><p><b>${escapeHtml(p.role)}</b></p><p style="margin-top:13px">${escapeHtml(p.appearance)}</p></article>`).join('')}</div>`:'<div class="empty-state">Aucun personnage enregistré.</div>');
 if(k==='media')return panelHeader('PRODUCTION','Médias et illustrations','Images, voix et vidéos reliées à vos scènes.')+`<div class="empty-state">${ico('image')}<h3>Vos créations auront leur place ici.</h3><p>Dans cette démonstration, seules les images de référence des deux récits sont présentées. Aucun rendu Qwen, image, voix ou vidéo n’est simulé comme une production réelle.</p></div>`;
 const map={landscapes:['PAYSAGES','Décors et paysages','landscape'],colors:['DIRECTION ARTISTIQUE','Palettes de couleurs','colors'],shots:['MISE EN SCÈNE','Plans et cadrages','shot'],emotions:['ÉMOTIONS','Intentions émotionnelles','emotion'],sounds:['BANDE SON','Voix et ambiances','sound']};
 if(map[k]){const [ey,title,field]=map[k];return panelHeader(ey,title,'Retrouvez ces éléments dans leur contexte narratif.')+`<div class="item-grid">${s.scenes.map((sc,i)=>`<article class="item-card"><span class="eyebrow">SCÈNE ${String(i+1).padStart(2,'0')}</span><strong>${escapeHtml(sc.title)}</strong><p>${escapeHtml(sc[field]||'À définir')}</p>${btn('Voir la scène','arrow','small','data-scene="'+i+'"')}</article>`).join('')||'<div class="empty-state">Aucun élément.</div>'}</div>`}
 return '';
}
function renderJournal(){
 const rows=events.filter(e=>(state.journalFilter==='Tout'||e.type===state.journalFilter)&&(e.title+' '+e.detail).toLowerCase().includes(state.journalQuery.toLowerCase())).sort((a,b)=>b.date.localeCompare(a.date)||b.id-a.id);
 return `<div class="page-heading"><div><div class="eyebrow">RIEN NE SE PERD</div><h1>La mémoire de vos créations.</h1><p>Retrouvez les décisions, les versions et les étapes de chaque récit.</p></div></div><div class="toolbar"><div class="filter-tabs">${[['Tout','Tout'],['Créations','creation'],['Révisions','revision'],['IA & visuels','ia']].map(([name,k])=>`<button class="filter-btn ${state.journalFilter===k?'active':''}" data-journal-filter="${k}">${name}</button>`).join('')}</div><label class="searchbox">${ico('search')}<input id="journal-search" aria-label="Rechercher dans le journal" placeholder="Rechercher une trace…" value="${escapeAttr(state.journalQuery)}"></label></div><section class="panel"><div class="eyebrow">HISTORIQUE LOCAL</div><div id="timeline" class="timeline">${rows.map(e=>`<article class="timeline-row"><time>${formatDay(e.date)}</time><h3>${escapeHtml(e.title)}</h3><p>${escapeHtml(e.detail)}</p>${statusPill(({creation:'Brouillon',revision:'En écriture',ia:'À relire'})[e.type]||'Brouillon')}</article>`).join('')||'<div class="empty-state">Aucune trace correspondante.</div>'}</div></section>`;
}
const demoEpics=[{title:'Parcours éditorial et navigation',percent:78,tag:'En cours'},{title:'Qualité, performance et MCO',percent:44,tag:'En cours'},{title:'Images, voix et production vidéo',percent:18,tag:'À construire'}];
const demoPR=[{number:103,title:'Atelier Composer et direction artistique',status:'Fusionnée'},{number:102,title:'Bibliothèque d’histoires',status:'Fusionnée'},{number:92,title:'Structure éditoriale et administration',status:'Fusionnée'}];
function renderAdmin(){
 const tab=state.adminTab;
 return `<div class="page-heading"><div><div class="eyebrow">CONCEPTION · CODE · TRAÇABILITÉ</div><h1>Le projet, en toute clarté.</h1><p>Pilotez la conception, les évolutions et les livraisons de l’atelier.</p></div></div><div class="demo-ribbon">${ico('shield')} Aperçu de l’interface — Données illustratives, aucune connexion GitHub.</div><div class="admin-tabs" role="tablist" aria-label="Sections administration">${['Vue d’ensemble','Epics & stories','Pull requests','Agenda'].map(t=>`<button role="tab" aria-selected="${tab===t}" class="admin-tab ${tab===t?'active':''}" data-admin-tab="${escapeAttr(t)}">${t}</button>`).join('')}</div><div id="admin-stage">${renderAdminTab(tab)}</div>`;
}
function renderAdminTab(tab){
 if(tab==='Vue d’ensemble')return `<div class="stats" style="margin-bottom:23px">${[['grid','03','Epics suivies'],['book','07','Stories illustratives'],['file','03','PR présentées'],['check','—','Livraison non connectée']].map(([i,n,t])=>`<div class="stat"><span class="stat-icon">${ico(i)}</span><div><span class="stat-number">${n}</span><span class="stat-label">${t}</span></div></div>`).join('')}</div><div class="admin-grid"><section class="panel"><div class="eyebrow">LE BESOIN, PUIS LA RÉALISATION</div><h3 style="margin:10px 0 17px">Avancement des epics</h3>${demoEpics.map(e=>`<div class="mini-row"><div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:8px"><span>${escapeHtml(e.title)}</span><b>${e.percent}%</b></div><progress class="progress" value="${e.percent}" max="100"></progress></div>`).join('')}</section><section class="panel"><div class="eyebrow">LES DERNIÈRES TRACES</div><h3 style="margin:10px 0 17px">Activité récente</h3>${demoPR.map(p=>`<div class="mini-row"><b>PR #${p.number} · ${escapeHtml(p.status)}</b><span>${escapeHtml(p.title)}</span></div>`).join('')}</section></div>`;
 if(tab==='Epics & stories')return `<section class="panel"><h3>La feuille de route éditoriale</h3><p>Exemples de suivi. Les véritables états devront provenir de GitHub.</p><table class="mini-table"><thead><tr><th>Epic</th><th>Avancement illustratif</th><th>État</th></tr></thead><tbody>${demoEpics.map(e=>`<tr><td>${escapeHtml(e.title)}</td><td>${e.percent}%</td><td>${escapeHtml(e.tag)}</td></tr>`).join('')}</tbody></table></section>`;
 if(tab==='Pull requests')return `<section class="panel"><h3>Historique de contribution</h3><p>Exemples de présentation, non synchronisés.</p><table class="mini-table"><thead><tr><th>Référence</th><th>Objet</th><th>Statut</th></tr></thead><tbody>${demoPR.map(p=>`<tr><td>#${p.number}</td><td>${escapeHtml(p.title)}</td><td>${statusPill('Validée')}</td></tr>`).join('')}</tbody></table></section>`;
 return renderCalendar();
}
function renderCalendar(){
 const mon=state.month,days=new Date(mon.getFullYear(),mon.getMonth()+1,0).getDate(),offset=(new Date(mon.getFullYear(),mon.getMonth(),1).getDay()+6)%7;
 const week=['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'];let dateList=[];
 if(state.calendarMode==='Jour'){dateList=[new Date(mon)]}
 else if(state.calendarMode==='Semaine'){let start=new Date(mon);start.setDate(start.getDate()-(start.getDay()+6)%7);for(let i=0;i<7;i++){const d=new Date(start);d.setDate(d.getDate()+i);dateList.push(d)}}
 else{for(let i=0;i<offset;i++)dateList.push(null);for(let n=1;n<=days;n++)dateList.push(new Date(mon.getFullYear(),mon.getMonth(),n));while(dateList.length%7)dateList.push(null)}
 const eventDate=new Date(2026,9,16);
 const toDay=d=>d?`${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`:'';
 return `<section class="panel"><div class="calendar-toolbar"><div class="cal-nav">${btn('','left','small','data-cal="prev"')}<strong>${mon.toLocaleDateString('fr-FR',{month:'long',year:'numeric'})}</strong>${btn('','arrow','small','data-cal="next"')}</div><div class="filter-tabs">${['Mois','Semaine','Jour'].map(v=>`<button class="filter-btn ${v===state.calendarMode?'active':''}" data-calendar-mode="${v}">${v}</button>`).join('')}</div></div><div class="calendar">${state.calendarMode==='Jour'?'':week.map(t=>`<div class="cal-week">${t}</div>`).join('')}${dateList.map(d=>`<div class="cal-day ${!d?'off':''}">${d?d.getDate():''}${toDay(d)===toDay(eventDate)?'<span class="cal-event">Exemple : revue du projet</span>':''}</div>`).join('')}</div><p class="muted" style="font-size:11px;margin-top:13px">Un calendrier réel pourra être alimenté par les événements GitHub et les livraisons validées.</p></section>`;
}
function bindContent(){
 $$('[data-action="new"]').forEach(x=>x.addEventListener('click',()=>openEditor('new')));
 $$('[data-action="library"]').forEach(x=>x.addEventListener('click',()=>navigate('stories')));
 $$('[data-action="edit-story"]').forEach(x=>x.addEventListener('click',()=>openEditor('story')));
 $$('[data-action="edit-scene"]').forEach(x=>x.addEventListener('click',()=>openEditor('scene')));
 $$('[data-action="add-scene"]').forEach(x=>x.addEventListener('click',()=>openEditor('add-scene')));
 $$('[data-action="export"]').forEach(x=>x.addEventListener('click',exportStory));
 $$('[data-open]').forEach(x=>x.addEventListener('click',()=>navigate('stories',x.dataset.open)));
 $$('[data-panel]').forEach(x=>x.addEventListener('click',()=>{state.panel=x.dataset.panel;render()}));
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
 const s=story(state.storyId),sc=s?.scenes[state.sceneIndex];editorAction=mode;
 let rows=[];let title='';let kick='ÉDITION LOCALE';
 if(mode==='new'){title='Créer une histoire';rows=[['topic','Sujet de la légende','','textarea'],['duration_seconds','Durée totale (s)',60,'number'],['scene_count','Nombre de scènes',3,'number']];}
 if(mode==='story'){title='Modifier le récit';rows=[['title','Titre de l’histoire',s.title,'text'],['place','Lieu / univers',s.place,'text'],['summary','Synopsis',s.summary,'textarea'],['status','Statut',s.status,'select',['Brouillon','En écriture','À relire','Validée']]];}
 if(mode==='scene'||mode==='add-scene'){title=mode==='scene'?'Modifier la scène':'Nouvelle scène';const v=mode==='scene'?sc:{};rows=[['title','Titre',v.title,'text'],['duration','Durée (secondes)',v.duration||20,'number'],['narration','Narration',v.narration,'textarea'],['landscape','Décor',v.landscape,'textarea'],['shot','Plan / cadrage',v.shot,'text'],['emotion','Émotion',v.emotion,'text'],['sound','Sons et voix',v.sound,'text'],['colors','Palette',v.colors,'text'],['prompt','Prompt d’image',v.prompt,'textarea']];}
 $('#editor-title').textContent=title;$('#editor-kicker').textContent=kick;fields(rows);$('#editor').showModal();
 $('#editor-fields input, #editor-fields textarea, #editor-fields select')?.focus();
}
async function saveRemoteEditor(input){
 try{
  if(editorAction==='new')await createRemote(input);
  else if(editorAction==='story'||editorAction==='scene')await reviseRemote(input);
  else showToast('Ajout autonome de scène non disponible : le nombre de scènes est fixé par le brief.');
 }catch(error){showToast('Enregistrement refusé : '+error.message)}
}
async function saveEditor(e){e.preventDefault();const input=Object.fromEntries(new FormData($('#editor-form')).entries());await saveRemoteEditor(input)}
function exportStory(){const s=story(state.storyId);if(!s)return;const blob=new Blob([JSON.stringify({format:'arvor-story-demo-v1',exported_at:new Date().toISOString(),story:s},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='arvor-'+s.id+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);showToast('Export JSON préparé.');}
$$('[data-route]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.route)));
$('#side-create').addEventListener('click',()=>{closeMobile();openEditor('new')});
$('#mobile-toggle').addEventListener('click',()=>{$('#sidebar').classList.toggle('open');$('#shade').classList.toggle('open')});
$('#shade').addEventListener('click',closeMobile);
$('#editor-close').addEventListener('click',()=>$('#editor').close());
$('#editor-cancel').addEventListener('click',()=>$('#editor').close());
$('#editor-form').addEventListener('submit',saveEditor);
$('#help').addEventListener('click',()=>showToast('Prototype autonome : aucun accès à PostgreSQL, Qwen, MinIO ou GitHub.'));
window.addEventListener('keydown',e=>{if(e.key==='Escape')closeMobile();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();navigate('stories');$('#story-search')?.focus()}});
launch();
})();
