
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
let stories=[],events=[],adminData=null,commitsData=null,ciData=null,csrf=null,nextCursor=null,pendingCreation=null,historyData=null,mediaData=null,prodData=null,prodError=null,journalData=null,journalError=null,journalPage=1,journalBeforeRevision=null,journalHasMoreReviews=false,journalLoadingOlder=false,adminError=null;
const state={route:'stories',storyId:null,panel:'overview',sceneIndex:0,filter:'Toutes',query:'',journalFilter:'Tout',journalQuery:'',adminTab:'Vue d’ensemble',month:new Date(new Date().getFullYear(),new Date().getMonth(),1),calendarMode:'Mois'};
let editorAction=null,toastTimer;
const persist=()=>{};
const story=id=>stories.find(s=>s.id===id);
const editorialStories=()=>stories.filter(s=>!/^Contrôle technique privé de la chaîne éditoriale/i.test(s.title||''));
const storyDuration=(s)=>(s.scenes||[]).reduce((a,x)=>a+(Number(x.duration)||0),0);
const storyDurationText=(s)=>{const d=storyDuration(s);return d>0?d+' s':'—'};
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
$('#logout-next').addEventListener('click',async()=>{
 try{await api('/studio/logout','POST');csrf=null;stories=[];adminData=null;journalData=null;journalError=null;adminError=null;journalPage=1;journalBeforeRevision=null;journalHasMoreReviews=false;journalLoadingOlder=false;
 $('#studio-shell').hidden=true;$('#login-screen').hidden=false;}
 catch(e){showToast('Déconnexion non confirmée : '+e.message)}
});
async function loadJournal(){
 const id=state.storyId;
 if(!id){journalData=null;journalError=null;journalBeforeRevision=null;journalHasMoreReviews=false;journalLoadingOlder=false;journalPage=1;render();return}
 journalBeforeRevision=null;journalHasMoreReviews=false;journalLoadingOlder=false;
 try{
  const [history,reviews]=await Promise.allSettled([
   api('/studio/api/runs/'+encodeURIComponent(id)+'/history'),
   api('/studio/api/runs/'+encodeURIComponent(id)+'/reviews?limit=50')
  ]);
  const failures=[];
  if(history.status==='rejected')failures.push('Historique des traitements indisponible.');
  if(reviews.status==='rejected')failures.push('Historique des décisions indisponible.');
  if(failures.length===2){journalError=failures.join(' · ');journalData=null;render();return}
  const rows=[];
  if(history.status==='fulfilled'){
   (history.value?.steps||[]).forEach(st=>{
    const failed=!!st.error_code;
    rows.push({date:st.finished_at||'',kind:'ia',title:'Traitement IA — '+(st.order===0?'Analyse':'Storyboard'),
     detail:'Prompt : '+(st.prompt||''),status:failed?'Échec':(st.parsed?'Sortie reçue':'En cours'),
     version:st.prompt_version||'',provenance:st.response_metadata?.model||'',agent:st.response_metadata?.provider||'',human:false});
   });
  }
  const reviewPage=reviews.status==='fulfilled'?(reviews.value?.reviews||[]):[];
  rows.push(...journalReviewRows(reviewPage));
  journalBeforeRevision=journalReviewCursor(reviewPage);
  journalHasMoreReviews=journalBeforeRevision!==null;
  if(reviewPage.length>=50&&!journalHasMoreReviews)failures.push('Pagination des décisions antérieures indisponible.');
  journalData={rows:rows.sort((a,b)=>String(b.date).localeCompare(String(a.date)))};
  journalError=failures.length?failures.join(' · '):null;journalPage=1;render();
 }catch(e){journalError=e.message;journalData=null;render()}
}
function journalReviewRows(reviews){
 return (reviews||[]).map(r=>({date:r.created_at||'',kind:'decision',
  title:'Décision humaine — '+(r.step==='analysis'?'Analyse':'Storyboard'),detail:r.comment||'',
  action:r.action,actionLabel:{accept:'Acceptée',reject:'Rejetée',revise:'Révisée'}[r.action]||r.action,
  status:r.valid?'Décision acceptée':'Décision refusée',version:'Rev. '+(r.revision||''),
  provenance:r.source_result_id||'',agent:r.actor_id||'',human:true,
  revision:Number.isSafeInteger(Number(r.revision))&&Number(r.revision)>0?Number(r.revision):null}));
}
function journalReviewCursor(reviews){
 if(!Array.isArray(reviews)||reviews.length<50)return null;
 const revisions=reviews.map(r=>Number(r.revision)).filter(n=>Number.isSafeInteger(n)&&n>0);
 return revisions.length===reviews.length?Math.min(...revisions):null;
}
async function loadOlderJournalReviews(){
 const id=state.storyId,beforeRevision=journalBeforeRevision;
 if(!id||!journalData||!journalHasMoreReviews||journalLoadingOlder||!Number.isSafeInteger(beforeRevision)||beforeRevision<1)return;
 journalLoadingOlder=true;journalError=null;render();
 try{
  const result=await api('/studio/api/runs/'+encodeURIComponent(id)+'/reviews?limit=50&before_revision='+beforeRevision);
  if(state.storyId!==id)return;
  const page=Array.isArray(result?.reviews)?result.reviews:[];
  const known=new Set(journalData.rows.filter(row=>row.kind==='decision'&&row.revision!==null).map(row=>row.revision));
  const olderRows=journalReviewRows(page).filter(row=>row.revision===null||!known.has(row.revision));
  journalData={rows:journalData.rows.concat(olderRows).sort((a,b)=>String(b.date).localeCompare(String(a.date)))};
  const nextRevision=journalReviewCursor(page);
  if(page.length>=50&&(nextRevision===null||nextRevision>=beforeRevision)){
   journalBeforeRevision=null;journalHasMoreReviews=false;
   journalError='Pagination des décisions antérieures indisponible.';
  }else{
   journalBeforeRevision=nextRevision;journalHasMoreReviews=nextRevision!==null;
  }
 }catch(error){
  if(state.storyId===id)journalError='Historique des décisions antérieures indisponible.';
 }finally{
  if(state.storyId===id){journalLoadingOlder=false;render()}
 }
}
async function loadAdmin(){
 try{
  const parts=await Promise.allSettled([
   api('/studio/api/conception'),
   api('/studio/api/conception/commits?limit=70'),
   api('/studio/api/conception/ci?limit=80')
  ]);
  adminError=null;
  if(parts[0].status==='fulfilled'){adminData=parts[0].value;commitsData=parts[1].status==='fulfilled'?parts[1].value:null;ciData=parts[2].status==='fulfilled'?parts[2].value:null}
  else{adminError=parts[0].reason.status===503?'Intégration GitHub non configurée.':'Suivi GitHub indisponible.';adminData=null;commitsData=null;ciData=null}
  render();
 }catch(err){adminError=err.message;adminData=null;commitsData=null;ciData=null}
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
 item.place=item.scenes[0]?.landscape||item.place;
 return item;
}
async function navigate(route,storyId=null,panel='overview'){
 if(storyId&&storyId!==state.storyId){prodData=null;mediaData=null;historyData=null;journalData=null;journalError=null;journalPage=1;prodError=null;}
 state.route=route;state.storyId=storyId;state.panel=panel;state.sceneIndex=0;historyData=null;
 closeMobile();render();window.scrollTo({top:0,behavior:'auto'});
 if(route==='stories'&&storyId){
  try{
   const run=await api('/studio/api/runs/'+encodeURIComponent(storyId));
   const i=stories.findIndex(s=>s.id===storyId);
   if(i>=0)stories[i]=mapRun(run);
   if(state.storyId===storyId)render();
  }catch(e){showToast(e.message);if(state.storyId===storyId){state.storyId=null;render()}}
 }
 if(route==='admin')await loadAdmin();
 if(route==='journal')await loadJournal();
 if(route==='production'&&state.storyId)await loadProduction();
}
const btn=(text,icon,cls='',extra='')=>`<button type="button" class="button ${cls}" ${extra}>${icon?ico(icon):''}${escapeHtml(text)}</button>`;
const statusClass=status=>({'En écriture':'writing','À relire':'review','Validée':'valid','À retravailler':'changes','Échec':'failed'}[status]||'writing');
const statusPill=status=>`<span class="pill ${statusClass(status)}">${escapeHtml(status)}</span>`;
const coverMarkup=(s)=>ASSETS[s.cover]?`<img src="${ASSETS[s.cover]}" alt="Paysage de référence de ${escapeAttr(s.place)}">`:'<div style="height:100%;background:linear-gradient(130deg,#1b4035,#aec4ad)"></div>';
function render(){
 $$('#sidebar .nav-btn').forEach(b=>b.classList.toggle('active',b.dataset.route===state.route));
 $('#nav-count').textContent=editorialStories().length;
 const title=state.route==='stories'?(state.storyId?story(state.storyId)?.title:'Mes histoires'):state.route==='journal'?'Journal de création':state.route==='overview'?'Tableau de bord':state.route==='conception'?'Conception':state.route==='production'?'Production audiovisuelle':'Administration';
 $('#breadcrumb').textContent=title||'Mes histoires';
 let body='';
 if(state.route==='overview')body=renderDashboard();
 else if(state.route==='stories')body=state.storyId?renderAtelier():renderLibrary();
 else if(state.route==='conception')body=renderConception();
 else if(state.route==='production')body=state.storyId?renderProduction():renderProductionEmpty();
 else if(state.route==='journal')body=renderJournal();
 else body=renderAdmin();
 $('#content').innerHTML=body+'<div class="footer-note"><span>ARVOR — Un atelier pour les histoires qui comptent.</span><span>Studio privé · Données réelles</span></div>';
 bindContent();
}
const STAGES=[['brief','Brief'],['analyse','Analyse IA'],['storyboard','Storyboard'],['validation','Validation'],['production','Images & voix'],['video','Vidéo']];
function stageIndexFor(s){
 const scenes=s.scenes||[];
 const status=s.rawStatus;
 if(scenes.length===0)return 0;
 if(status==='approved')return 4;
 if(status==='waiting_validation'||status==='changes_requested'||status==='failed')return 3;
 return 2;
}
function renderPipeline(){
 const counts={};STAGES.forEach(st=>counts[st[0]]=0);
 editorialStories().forEach(s=>{const k=STAGES[stageIndexFor(s)][0];counts[k]=(counts[k]||0)+1});
 let current=-1;for(let i=0;i<STAGES.length;i++)if(counts[STAGES[i][0]]>0)current=i;
 const rows=STAGES.map((st,i)=>{const value=counts[st[0]]||0;const state=value===0?'todo':i===current?'current':'done';
  return `<div class="stage ${state}"><div class="stage-line"></div><div class="stage-dot"></div><div class="stage-label">${st[1]}</div><div class="stage-value">${value} histoire${value>1?'s':''}</div></div>`;}).join('');
 return `<section class="panel"><h3>État du pipeline</h3><div class="stage-stepper">${rows}</div><p class="muted" style="margin:16px 0 0;font-size:11px">Agrégé sur les histoires chargées via /studio/api/runs — état réel, non exhaustif sans pagination.</p></section>`;
}
function renderDashboard(){
 const stories=editorialStories();
 const sceneCount=stories.reduce((a,s)=>a+(s.scenes?.length||s.sceneCount||0),0);
 const pending=stories.filter(s=>['waiting_validation','changes_requested'].includes(s.rawStatus));
 const stats=[['book',stories.length,'Histoires enregistrées'],['film',sceneCount,'Scènes imaginées'],['layers',pending.length,'Décisions humaines en attente'],['clock',events.length,'Traces de création']];
 const statCards=stats.map(([ic,n,t])=>`<div class="metric"><div class="metric-icon">${ico(ic)}</div><div><span class="metric-number">${String(n).padStart(2,'0')}</span><span class="metric-label">${t}</span></div></div>`).join('');
 const actionCards=pending.length?pending.map(s=>`<article class="action-card"><div style="min-width:0;flex:1"><div class="card-topline"><span class="place">${ico('map')}${escapeHtml(s.place||'Lieu à définir')}</span>${statusPill(s.status)}</div><h3 class="card-title">${escapeHtml(s.title)}</h3><p class="card-summary">${escapeHtml(s.summary||'Synopsis en cours.')}</p><small class="muted">Dernière trace · mise à jour ${formatDay(s.updated)}</small></div><button type="button" class="button primary small" data-open="${escapeAttr(s.id)}">Ouvrir la revue ${ico('arrow')}</button></article>`).join(''):`<article class="action-card"><div><div class="card-topline"><span class="place">${ico('check')}Atelier</span><span class="pill valid"><i></i>Clair</span></div><h3 class="card-title">Aucune décision humaine en attente</h3><p class="card-summary">Les histoires en attente de validation ou de correction apparaîtront ici avec leur contexte réel.</p></div></article>`;
 const activity=stories.slice(0,6).map(s=>`<article class="timeline-row"><time>${formatDay(s.created)}</time><h3>${escapeHtml(s.title)}</h3><p>${escapeHtml(s.summary||'Histoire enregistrée')} · ${s.scenes?.length||0} scènes</p>${statusPill(s.status)}</article>`).join('');
 return `<div class="page-heading"><div><div class="eyebrow">ARVOR · ATELIER PRIVÉ</div><h1>La forge des légendes.</h1><p>Images, voix et récits prennent forme ici. Rien n’est validé sans votre décision.</p></div>${btn('Nouvelle histoire','plus','primary','data-action="new"')}</div>
  <div class="metric-grid">${statCards}</div>
  <div class="dash-grid">
   <div>
    <section class="panel"><h3>Prochaines actions humaines</h3><div class="action-list">${actionCards}</div></section>
    <section class="panel"><h3>Activité récente</h3><div class="timeline">${activity}</div></section>
   </div>
   <div>${renderPipeline()}</div>
  </div>`;
}
function renderConception(){
 const stories=editorialStories();
 const cards=stories.map(s=>`<article class="story-card"><div class="story-cover">${coverMarkup(s)}<span class="visual-tag">HISTOIRE EN COURS</span></div><div class="card-body"><div class="card-topline"><span class="place">${ico('map')}${escapeHtml(s.place||'Lieu à définir')}</span>${statusPill(s.status)}</div><h3 class="card-title">${escapeHtml(s.title)}</h3><p class="card-summary">${escapeHtml(s.summary||'')}</p><div class="card-data"><span>${ico('film')}${s.scenes?.length||0} scènes</span><span>${ico('clock')}${storyDurationText(s)}</span></div></div><div class="card-bottom"><span>Atelier</span><button type="button" class="button small" data-open="${escapeAttr(s.id)}">Ouvrir l’atelier ${ico('arrow')}</button></div></article>`).join('');
 return `<div class="page-heading"><div><div class="eyebrow">ATELIER DE CRÉATION</div><h1>Les histoires prennent forme.</h1><p>Sélectionnez une histoire enregistrée pour entrer dans l’atelier : scénario, scènes, personnages, décors et prompts.</p></div>${btn('Nouvelle histoire','plus','primary','data-action="new"')}</div>
  <div class="story-grid">${cards||'<div class="empty-state"><h3>Aucune histoire enregistrée.</h3><p>Les histoires créées via le brief Arvor apparaîtront ici.</p></div>'}</div>
  <section class="panel"><h3>Lancer une nouvelle création</h3><p>Le brief Arvor impose 75 secondes, 1 à 6 scènes et une clé d’idempotence par création.</p>${btn('Créer une histoire','plus','primary','data-action="new"')}</section>`;
}
function renderProductionEmpty(){
 return `<div class="empty-state"><h3>Aucun contexte de production.</h3><p>Sélectionnez une histoire dans la bibliothèque pour suivre ses images, sa voix et son montage.</p>${btn('Voir mes histoires','book','secondary','data-action="library"')}</div>`;
}
async function exportVideo(){
 const plan=prodData;
 if(!state.storyId||!plan)return;
 const video=plan.media?.video;
 if(!plan.approved||video?.status!=='ready'||!video?.id)return;
 if(plan.run_id&&plan.run_id!==state.storyId)return;
 const url='/studio/api/runs/'+encodeURIComponent(state.storyId)+'/media/'+encodeURIComponent(video.id)+'/content';
 try{
  const response=await fetch(url,{method:'GET',credentials:'same-origin'});
  if(!response.ok)throw Error('HTTP '+response.status);
  const blob=await response.blob();
  const objectUrl=URL.createObjectURL(blob);
  const link=document.createElement('a');
  link.href=objectUrl;link.download='arvor-production-video.mp4';document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
  showToast('Export vidéo prêt.');
 }catch(e){showToast('Export vidéo indisponible : '+e.message)}
}
function renderProduction(){
 if(!state.storyId)return renderProductionEmpty();
 const plan=prodData;
 if(!plan){
  if(prodError)return `<div class="empty-state"><h3>Lecture de la production impossible.</h3><p>${escapeHtml(prodError)}</p><button type="button" class="button secondary" data-action="library">${ico('left')} Retour</button></div>`;
  return `<div class="loading-view" role="status">Consultation de la production…</div>`;
 }
 const approved=!!plan.approved;
 const scenes=plan.scenes||[];
 const media=plan.media||{};
 const video=media.video||{};
 const voice=media.voice||{};
 const subtitles=media.subtitles||{};
 const missing=plan.missing_images||[];
 const quality=[
  ['Présence des médias',['voice','video','subtitles'].every(k=>!!media[k])?'ok':'ko'],
  ['Validation technique',approved&&plan.duration_seconds===75&&scenes.length>0&&missing.length===0&&voice.status==='ready'?'ok':'warn'],
  ['Validation artistique (humaine)',approved?'pending_human':'not_started']
 ];
 const qualityHtml=quality.map(([label,state])=>{const display=state==='pending_human'?'warn':state==='not_started'?'ko':state;return `<div class="quality-item"><span class="q-title">${display==='ok'?ico('check'):display==='warn'?ico('shield'):ico('close')}${escapeHtml(label)}</span><span class="pill ${display==='ok'?'valid':display==='warn'?'writing':'failed'}">${display==='ok'?'Prête':display==='warn'?'À traiter':'Manquante'}</span></div>`}).join('');
 const videoSrc=approved&&video.status==='ready'?`/studio/api/runs/${encodeURIComponent(state.storyId)}/media/${encodeURIComponent(video.id)}/content`:'';
 const canExport=approved&&video.status==='ready';
 const sceneRowsHtml=scenes.map(sc=>`<div class="mini-row"><b>Scène ${sc.scene_number}</b><span>${escapeHtml(sc.title)} · ${sc.duration_seconds} s · image : ${escapeHtml(sc.image_status)}</span></div>`).join('');
 const mediaHtml=[
  ['Voix',voice],['Vidéo',video],['Sous-titres',subtitles]
 ].map(([label,m])=>`<div class="mini-row"><b>${escapeHtml(label)}</b><span>Statut : ${escapeHtml(m?.status||'absent')}${m?.duration_seconds? ' · '+m.duration_seconds+' s':''}${m?.sha256?' · SHA256 '+m.sha256.slice(0,16):''}</span></div>`).join('');
 return `<div class="backline"><button type="button" class="button secondary" data-action="library">${ico('left')} Retour</button></div>
  <section class="panel">
   <div class="section-head"><div><div class="eyebrow">PRODUCTION</div><h2>Vidéo verticale 1080 × 1920</h2><p>Voix, images et montage — états réels de la production.</p></div>${btn('Exporter','download','primary','data-action="export-video"')}</div>
   ${videoSrc?`<video class="production-video" controls preload="metadata" src="${videoSrc}"></video>`:`<div class="empty-state"><h3>Vidéo non générée ou indisponible.</h3><p>La production vidéo n’est pas disponible pour cette histoire.</p></div>`}
   <div class="quality-check">${qualityHtml}</div>
   <div class="decision-bar"><div><b>${canExport?'Prête à exporter.':'Condition de sortie non remplie.'}</b><p>L’export ne part vers aucune plateforme sans validation humaine explicite.</p></div><button type="button" class="button primary" data-action="export-video" ${canExport?'':'disabled'}>Exporter le MP4 1080 × 1920</button></div>
  </section>
  <div class="dash-grid">
   <div>
    <section class="panel"><h3>Scènes et images</h3><div class="action-list">${sceneRowsHtml||'<p class="muted">Aucune scène.</p>'}</div></section>
   </div>
   <div>
    <section class="panel"><h3>Médias de production</h3>${mediaHtml}</section>
   </div>
  </div>`;
}
function renderLibrary(){
 const sceneCount=editorialStories().reduce((a,s)=>a+(s.sceneCount||s.scenes.length),0),elementCount=editorialStories().filter(s=>s.status==='À relire').length;
 return `<div class="page-heading"><div><div class="eyebrow">L’IMAGINAIRE BRETON, EN MOUVEMENT</div><h1>Vos histoires commencent ici.</h1><p>Du premier murmure au dernier plan, imaginez et façonnez chaque détail.</p></div>${btn('Nouvelle histoire','plus','primary','data-action="new"')}</div>
 <section class="stats" aria-label="Statistiques de l’atelier">
 ${[["book",editorialStories().length,"Histoires chargées"],["film",sceneCount,"Scènes imaginées"],["layers",elementCount,"À valider"],["clock",events.length,"Traces de création"]].map(([ic,n,t])=>`<div class="stat"><div class="stat-icon">${ico(ic)}</div><div><span class="stat-number">${String(n).padStart(2,'0')}</span><span class="stat-label">${t}</span></div></div>`).join('')}</section>
 <div class="toolbar"><div class="filter-tabs" role="group" aria-label="Filtrer par état">${['Toutes','En écriture','À relire','Validée','À retravailler','Échec'].map(v=>`<button type="button" class="filter-btn ${v===state.filter?'active':''}" data-filter="${v}" aria-pressed="${v===state.filter}">${v}</button>`).join('')}</div><label class="searchbox">${ico('search')}<input id="story-search" aria-label="Rechercher une histoire" placeholder="Rechercher une histoire…" value="${escapeAttr(state.query)}" autocomplete="off"></label></div>
 <div id="library-grid" class="story-grid"></div>${nextCursor?btn('Charger d’autres histoires','plus','small','data-action="more"'):''}`;
}
function libraryCards(){
 const el=$('#library-grid');if(!el)return;
 const results=editorialStories().filter(s=>(state.filter==='Toutes'||s.status===state.filter)&&(s.title+' '+s.summary+' '+s.place).toLocaleLowerCase('fr').includes(state.query.toLocaleLowerCase('fr')));
 const cards=results.map(s=>`<article class="story-card"><div class="story-cover">${coverMarkup(s)}<span class="visual-tag">ILLUSTRATION D’AMBIANCE</span></div><div class="card-body"><div class="card-topline"><span class="place">${ico('map')}${escapeHtml(s.place||'Lieu à définir')}</span>${statusPill(s.status)}</div><h3 class="card-title">${escapeHtml(s.title)}</h3><p class="card-summary">${escapeHtml(s.summary||'Synopsis en cours de génération.')}</p><div class="card-data"><span>${ico('film')}${(s.sceneCount||s.scenes.length)} scène${(s.sceneCount||s.scenes.length)>1?'s':''}</span><span>${ico('clock')}${escapeHtml(s.status)}</span></div></div><div class="card-bottom"><span>Modifiée le ${formatDay(s.updated)}</span><button type="button" data-open="${escapeAttr(s.id)}">Ouvrir l’histoire ${ico('arrow')}</button></div></article>`).join('');
 el.innerHTML=cards+`<div class="create-tile"><div class="create-icon">${ico('plus')}</div><h3>La prochaine légende ?</h3><p>Une idée, un lieu, une voix. Commencez un nouveau récit.</p>${btn('Créer une histoire','arrow','textual','data-action="new"')}</div>`;
}
const atelierMenu=[['overview','Vue d’ensemble','book'],['scenario','Scénario','file'],['scenes','Scènes','film'],['characters','Personnages','users'],['landscapes','Paysages','map'],['colors','Couleurs','palette'],['shots','Plans & cadrages','grid'],['emotions','Émotions','shield'],['sounds','Sons & voix','mic'],['media','Médias','image'],['history','Historique IA','clock']];
function renderAtelier(){
 const s=story(state.storyId);if(!s)return '<div class="empty-state">Histoire introuvable.</div>';
 if(!s.run)return '<div class="loading-view" role="status">Ouverture de l’histoire…</div>';
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
  if(state.storyId===id){mediaData={visuals,media};if(state.panel==='media')render()}
 }catch(e){showToast('Catalogue indisponible : '+e.message)}
}
async function loadProduction(){
 const id=state.storyId;if(!id)return;
 try{
  const plan=await api('/studio/api/runs/'+encodeURIComponent(id)+'/production-media');
  if(state.storyId===id){prodData=plan;prodError=null;render()}
 }catch(e){prodError=e.message;showToast('État de production indisponible : '+e.message)}
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
 if(k==='overview')return panelHeader('LA TRAME DE VOTRE RÉCIT','Une histoire, tout un univers.','Un aperçu clair de votre narration, de vos scènes et de votre distribution.')+`<div class="panel-grid"><div><section class="panel"><div class="eyebrow">SYNOPSIS</div><h3 style="margin-top:9px">L’essentiel du récit</h3><p>${escapeHtml(s.summary)}</p>${btn('Modifier le synopsis','edit','small','data-action="edit-story"')}</section><section class="panel"><div class="section-head"><div><div class="eyebrow">DÉCOUPAGE</div><h3 style="margin:7px 0">Le fil des scènes</h3></div>${btn('Ajouter une scène','plus','small','data-action="add-scene"')}</div>${sceneRows(s)}</section></div><div><section class="panel"><div class="eyebrow">FICHE ÉDITORIALE</div><h3 style="margin:9px 0">Repères</h3>${[['Univers',s.place],['Statut',s.status],['Scènes',s.scenes.length],['Durée totale',storyDurationText(s)],['Dernière édition',formatDay(s.updated)]].map(([n,v])=>`<div class="mini-row"><b>${n}</b><span>${escapeHtml(v)}</span></div>`).join('')}</section><section class="panel"><div class="eyebrow">DISTRIBUTION</div><h3 style="margin:9px 0">Personnages</h3>${s.characters.map(p=>`<div class="mini-row"><b>${escapeHtml(p.name)}</b><span>${escapeHtml(p.role)}</span></div>`).join('')||'<p>Personnages à créer.</p>'}</section></div></div>`;
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
function journalVisible(){
 const rows=journalData?.rows||[];
 const q=(state.journalQuery||'').toLowerCase();
 const filtered=rows.filter(r=>(state.journalFilter==='Tout'||r.kind===state.journalFilter)&&(q===''||r.title.toLowerCase().includes(q)||r.detail.toLowerCase().includes(q)));
 const pageSize=15;
 const totalPages=Math.max(1,Math.ceil(filtered.length/pageSize));
 const page=Math.min(Math.max(1,state.journalPage||1),totalPages);
 const pagerRows=filtered.slice((page-1)*pageSize,page*pageSize);
 return{pagerRows:pagerRows,page:page,totalPages:totalPages};
}
function renderJournal(){
 let body='';
 if(!state.storyId){
  body=`<div class="page-heading"><div><div class="eyebrow">RIEN NE SE PERD</div><h1>La mémoire de vos créations.</h1><p>Retrouvez les décisions, les versions et les étapes de chaque récit.</p></div></div><section class="panel"><div class="empty-state"><h3>Aucune histoire sélectionnée.</h3><p>Sélectionnez une histoire dans la bibliothèque pour retrouver ses traces réelles.</p><button type="button" class="button secondary" data-action="library">${ico('book')} Voir mes histoires</button></div></section>`;
 }else if(journalError&&!journalData){
  body=`<div class="backline"><button type="button" class="button secondary" data-action="library">${ico('left')} Retour</button></div>
   <section class="panel"><div class="empty-state"><h3>Journal indisponible.</h3><p>${escapeHtml(journalError)}</p><button type="button" class="button secondary" data-action="library">Retour</button></div></section>`;
 }else if(!journalData){
  body=`<div class="backline"><button type="button" class="button secondary" data-action="library">${ico('left')} Retour</button></div>
   <section class="panel"><div class="loading-view" role="status">Consultation du journal…</div></section>`;
 }else{
  const {pagerRows,page,totalPages}=journalVisible();
  body=`<div class="page-heading"><div><div class="eyebrow">RIEN NE SE PERD</div><h1>La mémoire de vos créations.</h1><p>Retrouvez les décisions, les versions et les étapes de chaque récit.</p></div></div>
   <div class="toolbar"><div class="filter-tabs">${[['Tout','Tout'],['Décisions humaines','decision'],['Traitements IA','ia']].map(([name,k])=>`<button type="button" class="filter-btn ${state.journalFilter===k?'active':''}" data-journal-filter="${k}" aria-pressed="${state.journalFilter===k}">${name}</button>`).join('')}</div><label class="searchbox">${ico('search')}<input id="journal-search" aria-label="Rechercher dans le journal" placeholder="Rechercher une trace…" value="${escapeAttr(state.journalQuery)}"></label></div>
   <section class="panel"><div class="eyebrow">TRACES RÉELLES</div>${journalError?`<div class="warning" role="status">${escapeHtml(journalError)} Les traces disponibles restent affichées.</div>`:'' }<div id="timeline" class="timeline">${pagerRows.map(r=>`<article class="timeline-row"><time>${escapeHtml(r.date?formatDay(r.date):'—')}</time><h3>${escapeHtml(r.title)}</h3><p>${escapeHtml(r.detail)}</p><div class="mini-meta"><span>${escapeHtml(r.status)}</span>${r.human?`<span>Décision ${escapeHtml(r.actionLabel||r.action||'—')}</span>`:''}<span>Version ${escapeHtml(r.version||'—')}</span><span>Agent ${escapeHtml(r.agent||'—')}</span><span>${escapeHtml(r.provenance||'—')}</span></div></article>`).join('')||'<div class="empty-state">Aucune trace correspondante.</div>'}</div>
   ${totalPages>1?`<div class="decision-bar"><div><b>${page} sur ${totalPages}</b></div><button type="button" class="button secondary" data-journal-page="${page-1}" ${page<=1?'disabled':''}>Page précédente</button><button type="button" class="button secondary" data-journal-page="${page+1}" ${page>=totalPages?'disabled':''}>Page suivante</button></div>`:''}
   ${journalHasMoreReviews?`<div class="decision-bar"><div><b>Décisions anciennes</b><p>Les décisions suivantes peuvent être chargées.</p></div><button type="button" class="button secondary" data-journal-older ${journalLoadingOlder?'disabled':''}>${journalLoadingOlder?'Chargement…':'Charger les décisions plus anciennes'}</button></div>`:''}
   </section>`;
 }
 return body;
}
function renderAdmin(){
 const tab=state.adminTab;
 const sourceStatus=adminError?(adminError.toLowerCase().includes('configur')?'not_configured':'unavailable'):'operational';
 const sourceLabel=adminError?(sourceStatus==='not_configured'?'Source : GitHub non configuré':'Source : GitHub indisponible'):'Source : GitHub en lecture réelle';
 let stage=adminError?'<div class="empty-state"><h3>Suivi GitHub indisponible.</h3><p>'+escapeHtml(adminError)+'</p>':adminData?renderAdminTab(tab):'<div class="loading-view">Chargement du suivi GitHub privé…</div>';
 return `<div class="page-heading"><div><div class="eyebrow">CONCEPTION · CODE · TRAÇABILITÉ</div><h1>Le projet, en toute clarté.</h1><p>Épics, pull requests, commits et livraisons issus de GitHub.</p></div><span class="pill ${sourceStatus==='operational'?'valid':sourceStatus==='not_configured'?'writing':'failed'}">${sourceLabel}</span></div>
 <div class="admin-tabs" role="tablist" aria-label="Sections administration">
 ${['Vue d’ensemble','Epics & stories','Pull requests','Commits','Agenda'].map(t=>`<button type="button" role="tab" aria-selected="${tab===t}" class="admin-tab ${tab===t?'active':''}" data-admin-tab="${escapeAttr(t)}">${t}</button>`).join('')}</div>
 <div id="admin-stage">${stage}</div>`;
}
function renderAdminTab(tab){
 const epics=adminData?.epics||[],issues=adminData?.issues||[],prs=adminData?.pull_requests||[],deliveries=adminData?.deliveries||[];
 const commits=commitsData?.commits||[];
 if(tab==='Vue d’ensemble'){
  const stats=[['grid',epics.length,'Epics'],['book',issues.length,'Issues chargées'],['file',prs.filter(x=>x.state==='open').length,'PR ouvertes'],['check',deliveries.filter(x=>x.conclusion==='failure').length,'Livraisons en échec']];
  const statCards=stats.map(([ic,n,label])=>`<div class="stat"><span class="stat-icon">${ico(ic)}</span><div><span class="stat-number">${n}</span><span class="stat-label">${label}</span></div></div>`).join('');
  const epicRows=epics.slice(0,12).map(e=>`<div class="mini-row"><b>#${e.number} · ${escapeHtml(e.title)}</b><small>${Number.isInteger(e.progress_pct)?e.checklist_done+'/'+e.checklist_total+' critères · '+e.progress_pct+' %':'Aucune checklist mesurable'}</small>${Number.isInteger(e.progress_pct)?`<progress class="progress" value="${e.progress_pct}" max="100"></progress>`:''}</div>`).join('');
  const prRows=prs.slice(0,9).map(p=>`<div class="mini-row"><b>PR #${p.number} · ${p.merged_at?'Fusionnée':p.state==='open'?'Ouverte':'Fermée'}</b><span>${escapeHtml(p.title)}</span></div>`).join('');
  const sourcePartial=Object.keys(adminData?.source_truncated||{}).some(k=>adminData.source_truncated[k]);
  const sourceNote=sourcePartial?`<section class="panel"><div class="eyebrow">SOURCES</div><h3>Disponibilité des sources</h3><p>Les résultats GitHub peuvent être partiels selon les limites de pagination.</p></section>`:'';
  return `<section class="stats">${statCards}</section>
  <div class="admin-grid"><section class="panel"><div class="eyebrow">AVANCEMENT VÉRIFIABLE</div><h3>Les epics</h3>${epicRows}</section>
  <section class="panel"><div class="eyebrow">LES DERNIÈRES TRACES</div><h3>Pull requests</h3>${prRows}</section>
  ${sourceNote}</div>`;
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
 document.querySelectorAll('[data-action="more"]').forEach(x=>x.addEventListener('click',()=>fetchStories(true).catch(e=>showToast(e.message))));
 document.querySelectorAll('[data-action="new"]').forEach(x=>x.addEventListener('click',()=>openEditor('new')));
 $$('[data-action="library"]').forEach(x=>x.addEventListener('click',()=>navigate('stories')));
 $$('[data-action="edit-story"]').forEach(x=>x.addEventListener('click',()=>openEditor('story')));
 $$('[data-action="edit-scene"]').forEach(x=>x.addEventListener('click',()=>openEditor('scene')));
 $$('[data-action="add-scene"]').forEach(x=>x.addEventListener('click',()=>openEditor('add-scene')));
 $$('[data-action="export"]').forEach(x=>x.addEventListener('click',exportStory));
 $$('[data-action="export-video"]').forEach(x=>x.addEventListener('click',exportVideo));
 $$('[data-open]').forEach(x=>x.addEventListener('click',()=>navigate('stories',x.dataset.open)));
 $$('[data-panel]').forEach(x=>x.addEventListener('click',()=>{state.panel=x.dataset.panel;mediaData=null;render();if(state.panel==='media')loadMedia();if(state.panel==='history')loadHistory()}));
 $$('[data-scene]').forEach(x=>x.addEventListener('click',()=>{state.sceneIndex=Number(x.dataset.scene);state.panel='scenes';render()}));
 $$('[data-filter]').forEach(x=>x.addEventListener('click',()=>{state.filter=x.dataset.filter;render()}));
 if($('#story-search')){libraryCards();bindLibraryOpen();$('#story-search').addEventListener('input',e=>{state.query=e.target.value;libraryCards();bindLibraryOpen()})}
 if($('#journal-search'))$('#journal-search').addEventListener('input',e=>{state.journalQuery=e.target.value;state.journalPage=1;const active=document.activeElement;const caret=e.target.selectionStart;render();const inp=$('#journal-search');inp.focus();inp.setSelectionRange(caret,caret)});
 $$('[data-journal-filter]').forEach(x=>x.addEventListener('click',()=>{state.journalFilter=x.dataset.journalFilter;state.journalPage=1;render()}));
 $('[data-journal-page]').forEach(x=>x.addEventListener('click',()=>{state.journalPage=Number(x.dataset.journalPage)||1;render()}));
 $('[data-journal-older]').forEach(x=>x.addEventListener('click',()=>loadOlderJournalReviews()));
 $$('[data-journal-retry]').forEach(x=>x.addEventListener('click',()=>loadJournal()));
 $$('[data-admin-tab]').forEach(x=>x.addEventListener('click',()=>{state.adminTab=x.dataset.adminTab;render()}));
 $$('[data-calendar-mode]').forEach(x=>x.addEventListener('click',()=>{state.calendarMode=x.dataset.calendarMode;render()}));
 $$('[data-cal]').forEach(x=>x.addEventListener('click',()=>{const d=state.month;const delta=x.dataset.cal==='prev'?-1:1;if(state.calendarMode==='Mois')d.setMonth(d.getMonth()+delta);else d.setDate(d.getDate()+delta*(state.calendarMode==='Semaine'?7:1));state.month=new Date(d);render()}));
}
function bindLibraryOpen(){ $$('[data-open]').forEach(x=>{const b=x.cloneNode(true);x.replaceWith(b);b.addEventListener('click',()=>navigate('stories',b.dataset.open))});$$('#library-grid [data-action="new"]').forEach(x=>{const b=x.cloneNode(true);x.replaceWith(b);b.addEventListener('click',()=>openEditor('new'))}) }
function fields(rows){$('#editor-fields').innerHTML=rows.map(([k,label,value,kind,choices,opts])=>{const o=opts||{};const numeric=kind==='number';const attrs=numeric?`type="number" min="${o.min??1}" max="${o.max??180}"`:'type="text"';const locked=o.readonly?' readonly aria-readonly="true"':'';return `<div class="field"><label for="edit-${k}">${escapeHtml(label)}</label>${kind==='select'?`<select id="edit-${k}" name="${k}">${choices.map(c=>`<option value="${escapeAttr(c)}" ${value===c?'selected':''}>${escapeHtml(c)}</option>`).join('')}</select>`:kind==='textarea'?`<textarea id="edit-${k}" name="${k}" rows="4" required>${escapeHtml(value||'')}</textarea>`:`<input id="edit-${k}" name="${k}" value="${escapeAttr(value||'')}" ${attrs}${locked} required maxlength="300">`}</div>`}).join('');}
function openEditor(mode){
 if(mode==='add-scene'){showToast('Le nombre de scènes est fixé par le brief initial. Révisez les scènes existantes.');return}
 const current=story(state.storyId);
 if(mode!=='new'&&(!current?.run?.storyboard||!['approved','waiting_validation','changes_requested'].includes(current.rawStatus))){
  showToast('Révision indisponible avant la génération du storyboard.');return
 }
 const s=story(state.storyId),sc=s?.scenes[state.sceneIndex];editorAction=mode;
 let rows=[];let title='';let kick='RÉVISION HISTORISÉE';
 if(mode==='new'){title='Créer une histoire';rows=[['topic','Sujet de la légende','','textarea'],['duration_seconds','Durée Arvor (s)',75,'number',null,{min:75,max:75,readonly:true}],['scene_count','Nombre de scènes',5,'number',null,{min:1,max:6}]];}
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
$$('[data-route]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.route,state.storyId)));
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
