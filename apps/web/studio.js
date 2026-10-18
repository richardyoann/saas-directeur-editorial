/* Arvor Studio: secrets are server-side; DOM uses textContent for user data. */
(() => {
"use strict";
const $ = id => document.getElementById(id);
const s = {csrf:null,runs:[],next:null,run:null,tab:"storyboard",pending:null,step:"storyboard",reviews:[],nextReview:null,openRequest:0,pollBusy:false,conception:null,calendarMonth:new Date(new Date().getFullYear(),new Date().getMonth(),1),composerCategory:"overview",coverToken:0};
let storyFilter="all";
const uuid=/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const states={queued:"En attente",waiting_validation:"À valider",changes_requested:"À retravailler",approved:"Approuvé",running:"En cours",failed:"Échec"};
const names={analysis:"Analyse",storyboard:"Storyboard"};
const verbs={accept:"Accepté",reject:"Changements demandés",revise:"Révision"};
function elem(tag,cls,value){const x=document.createElement(tag);if(cls)x.className=cls;if(value!==undefined&&value!==null)x.textContent=String(value);return x;}
function put(root,tag,cls,value){const x=elem(tag,cls,value);root.append(x);return x;}
function date(d){const x=new Date(d);return isNaN(x.getTime())?"Date inconnue":x.toLocaleString("fr-FR",{dateStyle:"medium",timeStyle:"short"});}
function message(e){return ({401:"Session expirée. Reconnectez-vous.",403:"Accès refusé.",404:"Histoire introuvable.",409:"Conflit de version : actualisez avant toute nouvelle décision.",422:"Données non conformes : vérifiez le schéma et les durées.",429:"Trop de requêtes. Patientez avant de réessayer cette opération.",502:"API indisponible : ne réessayez pas automatiquement.",503:"Service non configuré ou indisponible.",504:"Délai dépassé : l'état de la génération est incertain."})[e.status]||"Une erreur est survenue.";}
function alertUser(text,bad=false){$("notice").hidden=false;$("notice").textContent=text;$("notice").classList.toggle("error",bad);}
async function api(path,method="GET",body,more={}){
 let res,data;const headers={...more};
 if(method!=="GET")headers["X-CSRF-Token"]=s.csrf||"";
 if(body!==undefined)headers["Content-Type"]="application/json";
 try{res=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),credentials:"same-origin",cache:"no-store"});}
 catch{throw {status:0};}
 try{data=await res.json();}catch{throw {status:502};}
 if(!res.ok){if(res.status===401&&path!=="/studio/session")lock();throw {status:res.status,data};}
 return data;
}
function lock(){s.csrf=null;s.run=null;s.runs=[];s.openRequest++;document.querySelectorAll("dialog[open]").forEach(d=>d.close());$("login").hidden=false;$("app").hidden=true;$("password").value="";}
function unlock(){ $("login").hidden=true;$("app").hidden=false;$("loginError").hidden=true; }
async function boot(){try{const x=await api("/studio/session");if(!x.authenticated)return lock();s.csrf=x.csrf;unlock();await list(true);const id=location.hash.replace("#run/","");if(location.hash==="#conception")showConception(false);else if(uuid.test(id)&&location.hash.startsWith("#run/"))await openRun(id);else home(false);}catch(e){lock();$("loginError").hidden=false;$("loginError").textContent=message(e);}}
async function login(e){e.preventDefault();$("loginButton").disabled=true;try{const x=await api("/studio/session","POST",{password:$("password").value});s.csrf=x.csrf;unlock();$("password").value="";await list(true);const id=location.hash.slice(5);if(location.hash==="#conception")showConception(false);else if(location.hash.startsWith("#run/")&&uuid.test(id))await openRun(id);else home(false);}catch(err){$("loginError").hidden=false;$("loginError").textContent=err.status===401?"Mot de passe incorrect.":message(err);}finally{$("loginButton").disabled=false;}}
async function logout(){try{await api("/studio/logout","POST");s.runs=[];lock();}catch(e){if(e.status===401){s.runs=[];lock();return;}alertUser("Déconnexion non confirmée : la session peut rester active. Réessayez.",true);}}
async function list(reset=false){
 if(reset){s.runs=[];s.next=null;}
 let path="/studio/api/runs?limit=20";if(!reset&&s.next)path+="&before="+encodeURIComponent(s.next);
 try{const data=await api(path),ids=new Set(s.runs.map(x=>x.id));for(const r of data.runs||[])if(!ids.has(r.id))s.runs.push(r);s.next=data.next_before||null;renderList();}
 catch(e){renderList();alertUser(message(e),true);}
}
function renderList(){
 const root=$("runList"),q=$("filter").value.trim().toLocaleLowerCase("fr");root.replaceChildren();
 const runs=s.runs.filter(r=>[r.title,r.topic].filter(Boolean).join(" ").toLocaleLowerCase("fr").includes(q));
 if(!runs.length)put(root,"p","","Aucune histoire correspondante dans les éléments chargés.");
 for(const r of runs){const b=put(root,"button","run-item"+(r.id===s.run?.id?" active":""));b.type="button";put(b,"strong","",r.title||r.topic||"Histoire sans titre");put(b,"small","",(states[r.status]||"Inconnu")+" · "+date(r.created_at));b.addEventListener("click",()=>openRun(r.id));}
 const groups={all:()=>true,draft:r=>r.status==="changes_requested",writing:r=>["running","queued"].includes(r.status),review:r=>r.status==="waiting_validation",approved:r=>r.status==="approved"};
 renderCards(runs.filter(groups[storyFilter]||groups.all));
 $("count").textContent=s.runs.length+(s.next?"+":"");$("total").textContent=$("count").textContent;
 $("pending").textContent=s.runs.filter(r=>["waiting_validation","changes_requested"].includes(r.status)).length;
 $("approved").textContent=s.runs.filter(r=>r.status==="approved").length;$("more").hidden=!s.next;
}
document.querySelectorAll("[data-story-filter]").forEach(button=>button.addEventListener("click",()=>{
 storyFilter=button.dataset.storyFilter;
 document.querySelectorAll("[data-story-filter]").forEach(item=>{const active=item===button;item.classList.toggle("active",active);item.setAttribute("aria-pressed",String(active));});
 renderList();
}));
function renderCards(runs){
 const root=$("storyCards");root.replaceChildren();
 if(!runs.length){put(root,"p","empty-panel","Aucune histoire dans les éléments chargés. Créez votre premier récit.");return;}
 for(const r of runs){
  const b=put(root,"button","story-tile");b.type="button";
  b.dataset.runId=r.id;
  const artwork=put(b,"span","story-tile-art","✧");
  // The private image is displayed only if it actually exists. Never show
  // demo artwork as a generated output or leak a MinIO object URL.
  const image=new Image();
  image.loading="lazy";image.alt="Illustration de la première scène";
  image.addEventListener("load",()=>{artwork.replaceChildren(image);});
  image.src="/studio/api/runs/"+encodeURIComponent(r.id)+"/scenes/1/image";
  const meta=put(b,"span","story-tile-content");
  const badge=put(meta,"span","arvor-story-badge",states[r.status]||"Statut inconnu");
  badge.dataset.status=r.status||"unknown";
  if(r.landscape)put(meta,"small","arvor-place","⌖ "+r.landscape);
  put(meta,"strong","",r.title||r.topic||"Histoire sans titre");
  if(r.synopsis)put(meta,"span","arvor-synopsis",r.synopsis);
  if(Number.isInteger(r.scene_count))put(meta,"small","arvor-scene-count",r.scene_count+" scène"+(r.scene_count>1?"s":""));
  put(meta,"small","arvor-updated","Modifiée le "+date(r.updated_at||r.created_at));
  put(meta,"span","story-tile-more","Explorer l’histoire →");
  b.addEventListener("click",()=>openRun(r.id));
 }
}
function showWorkspace(view){
 $("library").hidden=view!=="library";
 $("conception").hidden=view!=="conception";
 $("detail").hidden=view!=="detail";
 $("empty").hidden=true;
 document.querySelector(".hero").hidden=view!=="library";
 document.querySelector(".metrics").hidden=view!=="library";
 $("home").classList.toggle("selected",view!=="conception");
 $("conceptionNav").classList.toggle("selected",view==="conception");
 const inStory=view==="detail";
 $("storyComposer").hidden=!inStory;
 for(const item of [document.querySelector(".stories-title"),document.querySelector(".search"),$("runList"),$("more")]){
   if(item)item.classList.toggle("composer-hide",inStory);
 }
}
function safeGithubLink(root,label,path){
 const b=put(root,"a","btn secondary small-btn",label+" ↗");
 const base=s.conception?.repository_url||"";
 if(!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(base)){
  b.removeAttribute("href");b.setAttribute("aria-disabled","true");return b;
 }
 b.href=base+"/"+path;
 b.target="_blank";b.rel="noopener noreferrer";
 return b;
}
function dateKey(value){
 if(!value)return null;
 const d=new Date(value);if(!Number.isFinite(d.getTime()))return null;
 return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
}
function calendarEvents(data){
 const result=[];
 for(const epic of data.epics||[]){
  if(epic.created_at)result.push({when:epic.created_at,kind:"dev",title:"Epic #"+epic.number+" · ticket créé",id:epic.number});
  if(epic.closed_at)result.push({when:epic.closed_at,kind:"validation",title:"Epic #"+epic.number+" · clôture",id:epic.number});
 }
 for(const pr of data.pull_requests||[]){
  if(pr.created_at)result.push({when:pr.created_at,kind:"validation",title:"PR #"+pr.number+" · ouverture",id:pr.number});
  if(pr.merged_at)result.push({when:pr.merged_at,kind:"validation",title:"PR #"+pr.number+" · fusion",id:pr.number});
 }
 for(const d of data.deliveries||[]){
  if(d.conclusion==="success"&&d.updated_at)result.push({when:d.updated_at,kind:"prod",title:"PC · contrôle technique réussi "+(d.sha||"").slice(0,8),id:d.id});
 }
 return result;
}
function calendarView(root,data){
 const wrap=put(root,"article","card conception-calendar");
 const header=put(wrap,"div","calendar-toolbar");
 const previous=put(header,"button","btn secondary small-btn","←");previous.type="button";
 const label=put(header,"h3","",s.calendarMonth.toLocaleDateString("fr-FR",{month:"long",year:"numeric"}));
 const next=put(header,"button","btn secondary small-btn","→");next.type="button";
 previous.addEventListener("click",()=>{s.calendarMonth=new Date(s.calendarMonth.getFullYear(),s.calendarMonth.getMonth()-1,1);renderConception();});
 next.addEventListener("click",()=>{s.calendarMonth=new Date(s.calendarMonth.getFullYear(),s.calendarMonth.getMonth()+1,1);renderConception();});
 const legend=put(wrap,"p","calendar-legend","● Ticket produit   ● Revue de code   ● Contrôle PC réussi");
 const dayNames=put(wrap,"div","calendar-days");
 ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"].forEach(day=>put(dayNames,"strong","",day));
 const cells=put(wrap,"div","calendar-days calendar-cells");
 const start=new Date(s.calendarMonth.getFullYear(),s.calendarMonth.getMonth(),1);
 const offset=(start.getDay()+6)%7;
 const days=new Date(start.getFullYear(),start.getMonth()+1,0).getDate();
 const buckets=new Map();
 for(const event of calendarEvents(data)){
  const key=dateKey(event.when);if(!key)continue;
  if(!buckets.has(key))buckets.set(key,[]);
  buckets.get(key).push(event);
 }
 for(let i=0;i<offset;i++)put(cells,"div","calendar-cell calendar-empty");
 for(let day=1;day<=days;day++){
  const cell=put(cells,"div","calendar-cell");put(cell,"strong","",day);
  const key=dateKey(new Date(start.getFullYear(),start.getMonth(),day,12));
  for(const event of (buckets.get(key)||[])){
   const item=put(cell,"div","calendar-event "+event.kind,event.title);
   item.title=event.title;
  }
 }
}
function renderConception(){
 const data=s.conception;
 const root=$("conceptionContent");root.replaceChildren();
 if(data && Object.values(data.source_truncated||{}).some(Boolean)){
  put(root,"p","warning","Résultats GitHub partiels : consultez le dépôt pour les éléments non chargés.");
 }
 if(!data){put(root,"p","empty-panel","Connectez l’intégration GitHub pour afficher les données réelles.");return;}
 const epics=put(root,"section","conception-section");put(epics,"h3","","Epics · "+(data.epics||[]).length);
 for(const epic of data.epics||[]){
  const card=put(epics,"article","conception-item");
  put(card,"strong","",epic.title);
  put(card,"span","pill "+(epic.state==="closed"?"approved":"running"),epic.state==="closed"?"Terminée":"Ouverte");
  const info=put(card,"small","", "Créée le "+date(epic.created_at)+(epic.closed_at?" · clôturée le "+date(epic.closed_at):""));
  safeGithubLink(card,"Détails","issues/"+epic.number);
 }
 const prs=put(root,"section","conception-section");put(prs,"h3","","Pull requests · "+(data.pull_requests||[]).length);
 for(const pr of data.pull_requests||[]){
  const card=put(prs,"article","conception-item");
  put(card,"strong","", "#"+pr.number+" · "+pr.title);
  put(card,"span","pill",pr.merged_at?"Fusionnée":pr.draft?"Brouillon":pr.state==="open"?"En validation":"Fermée");
  put(card,"small","","SHA : "+(pr.merge_commit_sha||pr.sha||"non disponible").slice(0,12));
  safeGithubLink(card,pr.draft?"Ouvrir brouillon":"Examiner la PR","pull/"+pr.number);
 }
 put(root,"h3","","Calendrier de réalisation (événements enregistrés)");
 calendarView(root,data);
 put(root,"p","tip","Dates réelles uniquement : création d'epic, événements de PR et contrôle PC réussi. Un workflow vert est une preuve technique, pas une preuve de mise en production.");
 const reload=put(root,"button","btn secondary","↻ Actualiser GitHub");
 reload.type="button";reload.addEventListener("click",loadConception);
}
async function loadConception(){
 const root=$("conceptionContent");put(root,"p","tip","Synchronisation des événements GitHub…");
 try{s.conception=await api("/studio/api/conception");if(!$("conception").hidden)renderConception();}
 catch(e){s.conception=null;if(!$("conception").hidden){root.replaceChildren();put(root,"p","warning",message(e)+" Lisez la documentation de configuration GitHub de ce projet.");}}
}
function showConception(push=true){
 s.openRequest++;s.run=null;
 showWorkspace("conception");$("crumb").textContent="Conception";
 if(push&&location.hash!=="#conception")history.pushState(null,"","#conception");
 closeNav();
 if(s.conception)renderConception();else loadConception();
}
async function pollRun(){
 if(s.pollBusy||!s.csrf||!s.run||!["queued","running"].includes(s.run.status)||
    document.visibilityState!=="visible")return;
 s.pollBusy=true;
 const id=s.run.id;
 try{
  const latest=await api("/studio/api/runs/"+id);
  if(!s.run||s.run.id!==id||!s.csrf)return;
  const changed=latest.status!==s.run.status||
    (latest.current_step?.name||"")!==(s.run.current_step?.name||"")||
    (latest.steps||[]).length!==(s.run.steps||[]).length;
  s.run=latest;
  if(changed){
   render();
   const listed=s.runs.find(x=>x.id===id);
   if(listed){listed.status=latest.status;listed.title=latest.storyboard?.title||listed.title;}
   renderList();
   if(!["queued","running"].includes(latest.status)){
    if(s.pending?.runId===id)s.pending=null;
    alertUser(latest.status==="failed"?"La génération a échoué. Consultez l'historique avant de relancer.":"Génération terminée : la validation humaine est maintenant disponible.",latest.status==="failed");
   }
  }
 }catch(e){if(e.status!==401&&s.run?.id===id&&s.csrf)alertUser(message(e),true);}
 finally{s.pollBusy=false;}
}
function closeNav(){$("sidebar").classList.remove("open");$("menu").setAttribute("aria-expanded","false");}
async function openRun(id){
 if(!uuid.test(id))return alertUser("Identifiant UUID invalide.",true);
 const request=++s.openRequest;
 try{const result=await api("/studio/api/runs/"+id);if(request!==s.openRequest||!s.csrf)return;
 s.run=result;s.tab="storyboard";s.composerCategory="overview";s.reviews=[];s.nextReview=null;
 const target="#run/"+id;if(location.hash!==target)history.pushState(null,"",target);
 showWorkspace("detail");render();renderList();closeNav();$("detail").scrollIntoView({behavior:"smooth",block:"start"});}
 catch(e){if(request===s.openRequest)alertUser(message(e),true);}
}
function render(){
 if(!s.run)return;const r=s.run,title=r.storyboard?.title||r.brief?.topic||"Sans titre";
 $("editStory").disabled=!r.storyboard || !["waiting_validation","changes_requested","approved"].includes(r.status);
 $("editStory").title=$("editStory").disabled?"Révision autorisée uniquement pendant la validation du storyboard.":"";
 $("storyTitle").textContent=title;$("crumb").textContent=title;
 $("storyMeta").textContent=(r.storyboard?.synopsis||r.brief?.topic||"Brief indisponible")+" · "+(r.storyboard?.scenes?.length||0)+" scène(s) · "+date(r.created_at);
 $("detailLocation").textContent=r.storyboard?.scenes?.[0]?.landscape||"";
 $("exportStory").disabled=!r.storyboard;
 renderComposer();renderCover();
 $("status").textContent=states[r.status]||"Inconnu";$("status").className="pill "+r.status;
 $("decisionFoot").hidden=!["waiting_validation","changes_requested"].includes(r.status);$("reconcile").hidden=r.status!=="running";tab(s.tab);
}
function tab(name){
 s.tab=name;document.querySelectorAll("[data-tab]").forEach(b=>{b.classList.toggle("active",b.dataset.tab===name);b.setAttribute("aria-selected",String(b.dataset.tab===name));b.tabIndex=b.dataset.tab===name?0:-1;});$("panel").setAttribute("aria-labelledby","tab-"+name);
 if(name==="storyboard")storyboard();
 if(name==="visuals")visuals();
 if(name==="analysis")analysis();
 if(name==="history")historyView();
 if(name==="reviews")reviews(true);
}

function renderCover(){
 const r=s.run,cover=$("storyCover"),token=++s.coverToken;
 if(!r||!cover)return;
 cover.replaceChildren();
 const fallback=put(cover,"div","story-cover-placeholder");
 put(fallback,"span","","✧");
 put(fallback,"strong","","La trame de votre récit");
 put(fallback,"small","","Illustration issue de vos créations, si elle existe");
 if(!r.storyboard?.scenes?.length)return;
 const img=new Image();img.alt="Illustration privée de la première scène";img.loading="lazy";
 img.addEventListener("load",()=>{
   if(s.coverToken===token && s.run?.id===r.id && cover.isConnected)cover.replaceChildren(img);
 });
 img.src="/studio/api/runs/"+encodeURIComponent(r.id)+"/scenes/1/image";
}
function renderComposer(){
 const root=$("storyComposer");if(!root||!s.run)return;
 root.replaceChildren();
 put(root,"div","nav-title","COMPOSER");
 const board=s.run.storyboard,scenes=board?.scenes||[];
 const cast=new Set([...(board?.cast||[]).map(x=>x.name),...scenes.flatMap(x=>x.characters||[])]);
 const nav=[
  ["overview","Vue d’ensemble","⌂",""],
  ["scenario","Scénario","▤",board?"1":"0"],
  ["scenes","Scènes","▣",scenes.length],
  ["characters","Personnages","♙",cast.size],
  ["landscapes","Paysages","⌁",scenes.filter(x=>x.landscape).length],
  ["colors","Couleurs","◒",scenes.filter(x=>x.colors?.length).length],
  ["shots","Plans & cadrages","◫",scenes.filter(x=>x.shot).length],
  ["emotions","Émotions","♡",scenes.filter(x=>x.emotion).length],
  ["sound","Sons & voix","♫",scenes.filter(x=>x.sound).length],
 ];
 for(const [key,label,icon,count] of nav){
  const b=put(root,"button","composer-link"+(s.composerCategory===key?" active":""));
  b.type="button";b.dataset.composer=key;
  put(b,"span","composer-icon",icon);put(b,"span","composer-label",label);
  if(count!=="")put(b,"span","composer-count",count);
  if(s.composerCategory===key)b.setAttribute("aria-current","page");
  b.addEventListener("click",()=>showComposer(key));
 }
 put(root,"div","nav-title composer-memory","MÉMOIRE");
 const historyButton=put(root,"button","composer-link"+(s.composerCategory==="history"?" active":""));
 historyButton.type="button";historyButton.dataset.composer="history";
 put(historyButton,"span","composer-icon","◷");put(historyButton,"span","composer-label","Historique");
 if(s.composerCategory==="history")historyButton.setAttribute("aria-current","page");
 historyButton.addEventListener("click",()=>showComposer("history"));
 put(root,"p","composer-hint","Vos modifications sont versionnées et sauvegardées après validation.");
}
function showComposer(key){
 if(!s.run)return;
 s.composerCategory=key;
 if(key==="history"){tab("history");renderComposer();return;}
 tab("storyboard");
 if(key==="characters"||["landscapes","colors","shots","emotions","sound"].includes(key))showCollection(key);
 if(key==="scenes")$("#panel").querySelector(".storyboard-section")?.scrollIntoView({block:"start",behavior:"smooth"});
 if(key==="scenario")$("#panel").querySelector(".card")?.scrollIntoView({block:"start",behavior:"smooth"});
 renderComposer();
 closeNav();
}
function showCollection(key){
 const board=s.run?.storyboard,root=$("panel");if(!board)return;
 root.replaceChildren();
 const title={characters:"Personnages",landscapes:"Paysages",colors:"Couleurs",shots:"Plans & cadrages",emotions:"Émotions",sound:"Sons & voix"}[key];
 detailHeader(root,"LA TRAME DE VOTRE RÉCIT",title,"Retour à l’histoire");
 const grid=put(root,"div","composer-collection");
 if(key==="characters"){
  const names=new Set([...(board.cast||[]).map(x=>x.name),...board.scenes.flatMap(x=>x.characters||[])]);
  for(const name of names){
   const b=put(grid,"button","composer-collection-card");b.type="button";
   put(b,"span","overline","FICHE PERSONNAGE");put(b,"strong","",name);
   const profile=(board.cast||[]).find(x=>x.name===name);
   put(b,"p","",profile?.role||profile?.appearance||"Consulter la fiche");
   b.addEventListener("click",()=>personDetail(name));
  }
  if(!names.size)put(root,"p","empty-panel","Aucun personnage enregistré.");
  return;
 }
 const field={landscapes:"landscape",colors:"colors",shots:"shot",emotions:"emotion",sound:"sound"}[key];
 for(const [i,scene] of board.scenes.entries()){
  const raw=scene[field];if(!raw||(Array.isArray(raw)&&!raw.length))continue;
  const b=put(grid,"button","composer-collection-card");b.type="button";
  put(b,"span","overline","SCÈNE "+(i+1));
  put(b,"strong","",scene.title);put(b,"p","",Array.isArray(raw)?raw.join(", "):raw);
  b.addEventListener("click",()=>elementValue(i,field,title));
 }
 if(!grid.children.length)put(root,"p","empty-panel","Aucun élément renseigné dans cette catégorie.");
}
function exportStory(){
 const r=s.run;if(!r?.storyboard)return;
 const file={format:"arvor-storyboard-v1",exported_at:new Date().toISOString(),run_id:r.id,status:r.status,
  brief:r.brief,storyboard:r.storyboard,review_revision:r.review_revision};
 const blob=new Blob([JSON.stringify(file,null,2)],{type:"application/json;charset=utf-8"});
 const url=URL.createObjectURL(blob),link=document.createElement("a");
 link.href=url;link.download="arvor-"+r.id+".json";document.body.append(link);link.click();link.remove();
 URL.revokeObjectURL(url);
}
function empty(text){$("panel").replaceChildren();put($("panel"),"div","empty-panel",text);}
function decisions(root,step){
 if(!["waiting_validation","changes_requested","approved"].includes(s.run.status))return;
 const bar=put(root,"div","review-buttons");
 for(const [action,label] of [["accept","Accepter"],["reject","Demander des changements"],["revise","Réviser"]]){
  const b=put(bar,"button","btn "+(action==="accept"?"primary":"secondary"),label);b.type="button";b.addEventListener("click",()=>openReview(step,action));
 }
}
function detailRow(root,label,value,onClick){
 const wrap=put(root,"div","element-row");
 const b=put(wrap,"button","element-link");b.type="button";
 put(b,"strong","",label);
 put(b,"span","",String(value??"—"));
 b.addEventListener("click",onClick);
}
function detailHeader(root,category,title,back,onBack=storyboard){
 const crumb=put(root,"div","element-crumb");
 const returnButton=put(crumb,"button","btn secondary small-btn","← "+back);
 returnButton.type="button";returnButton.addEventListener("click",onBack);
 put(root,"div","overline",category);put(root,"h3","",title);
}
function editElement(sceneIndex){
 if(!s.run||!["waiting_validation","changes_requested"].includes(s.run.status)){
  alertUser("L'édition requiert un storyboard en validation. Les versions déjà approuvées ne sont pas écrasées.",true);return;
 }
 openReview("storyboard","revise");
 if(Number.isInteger(sceneIndex)){
  const field=$("edit-scene-"+sceneIndex+"-title");
  field?.focus();
 }
}
function elementValue(sceneIndex,key,label){
 const scene=s.run?.storyboard?.scenes?.[sceneIndex];if(!scene)return storyboard();
 const root=$("panel");root.replaceChildren();
 detailHeader(root,"SCÈNE "+(sceneIndex+1)+" / "+label,label,"Retour à la scène",()=>sceneDetail(sceneIndex));
 const a=put(root,"article","card");
 const value=scene[key];
 if(Array.isArray(value)){
  const list=put(a,"ul");
  for(const v of value)put(list,"li","",v);
 }else put(a,"p","",value||"Non renseigné");
 put(a,"p","tip","Cette information appartient au storyboard historisé. La révision conserve la version précédente.");
 const button=put(a,"button","btn primary","✎ Modifier dans le storyboard");
 button.type="button";button.addEventListener("click",()=>editElement(sceneIndex));
}
function personDetail(name){
 const board=s.run?.storyboard;if(!board)return storyboard();
 const profile=(board.cast||[]).find(p=>p.name.toLocaleLowerCase("fr")===name.toLocaleLowerCase("fr"));
 const root=$("panel");root.replaceChildren();
 detailHeader(root,"FICHE PERSONNAGE",name,"Retour à l'histoire");
 const card=put(root,"article","card");
 for(const [title,value] of [["Apparence",profile?.appearance],["Rôle",profile?.role],["Personnalité",profile?.personality]]){
  put(card,"h4","",title);put(card,"p","",value||"Non renseigné");
 }
 const indices=board.scenes.map((v,i)=>v.characters.some(c=>c.toLocaleLowerCase("fr")===name.toLocaleLowerCase("fr"))?i:-1).filter(i=>i>=0);
 put(card,"h4","","Présence dans les scènes");
 for(const index of indices){
  const button=put(card,"button","btn secondary small-btn","Scène "+(index+1)+" — "+board.scenes[index].title);
  button.type="button";button.addEventListener("click",()=>sceneDetail(index));
 }
 const revise=put(card,"button","btn primary","✎ Modifier la fiche personnage");
 revise.type="button";revise.addEventListener("click",()=>editElement(null));
}
function sceneDetail(sceneIndex){
 const board=s.run?.storyboard,scene=board?.scenes?.[sceneIndex];if(!scene)return storyboard();
 const root=$("panel");root.replaceChildren();
 detailHeader(root,"SCÉNARIO / SCÈNE "+String(sceneIndex+1).padStart(2,"0"),scene.title,"Retour à l'histoire");
 const summary=put(root,"article","card");
 put(summary,"p","",scene.visual_description);
 put(summary,"p","","Durée : "+scene.duration_seconds+" secondes");
 const edit=put(summary,"button","btn primary","✎ Modifier la scène");
 edit.type="button";edit.addEventListener("click",()=>editElement(sceneIndex));
 const gallery=put(root,"div","scene-element-grid");
 const fields=[["Narration","narration"],["Description visuelle","visual_description"],["Décor / paysage","landscape"],["Palette de couleurs","colors"],["Plan / caméra","shot"],["Émotion","emotion"],["Son et voix","sound"],["Prompt image","image_prompt"]];
 for(const [label,key] of fields){
  const shown=Array.isArray(scene[key])?scene[key].join(", "):scene[key];
  detailRow(gallery,label,shown,()=>elementValue(sceneIndex,key,label));
 }
 const cast=put(root,"article","card");
 put(cast,"h4","","Personnages de la scène");
 if(!(scene.characters||[]).length)put(cast,"p","","Aucun personnage indiqué.");
 for(const name of scene.characters||[]){
  const button=put(cast,"button","btn secondary small-btn",name+" →");
  button.type="button";button.addEventListener("click",()=>personDetail(name));
 }
 const image=put(root,"article","card");
 put(image,"h4","","Illustration et médias associés");
 put(image,"p","","Les images sont accessibles dans l'onglet Personnages & images. Les autres médias sont répertoriés uniquement s'ils sont enregistrés pour cette histoire.");
 const listing=put(image,"div","media-catalog","Recherche des fichiers de production…");
 api("/studio/api/runs/"+s.run.id+"/media").then(data=>{
  if(!listing.isConnected)return;
  listing.replaceChildren();
  if(!(data.media||[]).length){
   put(listing,"p","tip","Aucun fichier de voix, vidéo ou sous-titres archivé dans le catalogue de cette histoire.");return;
  }
  for(const item of data.media){
   const card=put(listing,"div","media-catalog-entry");
   put(card,"strong","",({voice:"Voix",video:"Vidéo",image:"Image",manifest:"Manifeste",subtitles:"Sous-titres"})[item.kind]||"Média");
   put(card,"p","","Taille : "+(item.size_bytes??"—")+" octets · Empreinte SHA256 : "+(item.sha256||"—"));
   put(card,"small","",date(item.created_at));
  }
 }).catch(e=>{if(listing.isConnected)listing.textContent=message(e);});
 const media=put(image,"button","btn secondary","Afficher les images privées");
 media.type="button";media.addEventListener("click",()=>tab("visuals"));
}
function storyboard(){
 const root=$("panel"),board=s.run.storyboard;root.replaceChildren();
 if(!board)return empty("Storyboard indisponible. Le traitement est peut-être en cours.");
 const intro=put(root,"article","card");put(intro,"div","overline","HISTOIRE / SCÉNARIO");put(intro,"h3","",board.title);put(intro,"p","",board.synopsis);
 put(intro,"p","tip","Sélectionnez une scène ou un personnage pour accéder à ses données, puis à chacun de ses éléments.");
 const actions=put(intro,"div","actions");
 const edit=put(actions,"button","btn primary","✎ Éditer l'histoire");
 edit.type="button";edit.addEventListener("click",()=>editElement(null));
 const brief=put(root,"article","card");
 put(brief,"h4","","Brief de création");
 for(const [label,value] of [["Sujet",s.run.brief?.topic],["Genre",s.run.brief?.genre],["Public",s.run.brief?.audience],["Ton",s.run.brief?.tone],["Durée",s.run.brief?.duration_seconds+" s"]]){
  put(brief,"strong","",label+": ");put(brief,"span","",value||"—");put(brief,"div","");
 }
 const gallery=put(root,"div","storyboard-section");
 put(gallery,"h3","","Scènes et éléments");
 const grid=put(gallery,"div","story-cards");
 (board.scenes||[]).forEach((scene,i)=>{
  const button=put(grid,"button","story-tile");button.type="button";
  put(button,"span","story-tile-art","0"+(i+1));
  const c=put(button,"span","story-tile-content");
  put(c,"strong","",scene.title);put(c,"small","",scene.duration_seconds+" s · "+scene.landscape);
  put(c,"span","story-tile-more","Voir les éléments →");
  button.addEventListener("click",()=>sceneDetail(i));
 });
 const casting=put(root,"article","card");
 put(casting,"h3","","Personnages");
 const all=new Set([...(board.cast||[]).map(p=>p.name),...(board.scenes||[]).flatMap(sc=>sc.characters||[])]);
 if(!all.size)put(casting,"p","","Aucun personnage indiqué.");
 for(const name of all){
  const b=put(casting,"button","btn secondary small-btn",name+" →");
  b.type="button";b.addEventListener("click",()=>personDetail(name));
 }
 if(s.run.storyboard_stale)put(root,"p","warning","Storyboard obsolète : une nouvelle révision est obligatoire.");
 decisions(root,"storyboard");
}
async function visuals(){
 const root=$("panel"),id=s.run?.id;
 empty("Chargement du catalogue des personnages et images…");
 if(!id)return;
 try{
  const data=await api("/studio/api/runs/"+id+"/visuals");
  if(!s.run||s.run.id!==id||s.tab!=="visuals")return;
  root.replaceChildren();
  const intro=put(root,"article","card");
  put(intro,"div","overline","DIRECTION ARTISTIQUE");
  put(intro,"h3","","Personnages & images par scène");
  put(intro,"p","","Personnages extraits du storyboard généré par Qwen. Une image est produite uniquement sur demande, après validation humaine, par un modèle d'images distinct.");
  put(intro,"p","","La cohérence visuelle reste à vérifier après génération. Le modèle exact, la seed et la mémoire GPU ne sont pas communiqués par ce moteur.");
  const verify=put(intro,"button","btn","Vérifier les images et leur historique");
  verify.type="button";
  const verification=put(intro,"p","","Aucun contrôle d'intégrité lancé.");
  verify.addEventListener("click",async()=>{
   verify.disabled=true;
   try{
    const report=await api("/studio/api/runs/"+id+"/visuals/verification?expected_scenes="+data.scenes.length);
    verification.textContent=(report.technical_passed?"Intégrité et historique vérifiés.":"Contrôle incomplet : vérifiez les images et leur historique.")+
     " Validation visuelle humaine requise. GPU et VRAM non mesurés.";
    if(report.duplicate_image_digests)verification.textContent+=" Plusieurs scènes utilisent une image identique : à vérifier.";
   }catch(e){verification.textContent=message(e);}
   finally{verify.disabled=false;}
  });
  if(!data.characters?.length)put(intro,"p","","Aucun personnage nommé dans ce récit.");
  else{
   const list=put(intro,"div","tags");
   for(const person of data.characters){
    put(list,"span","",person.name+" · scènes "+(person.scenes||[]).join(", "));
    if(person.appearance){
     const detail=put(intro,"p","","Apparence de "+person.name+" : "+person.appearance);
     if(person.role)put(intro,"p","","Rôle : "+person.role+" · Personnalité : "+(person.personality||"non précisée"));
    }
   }
  }
  if(!data.scenes?.length)return put(root,"div","empty-panel","Créez et révisez d'abord votre storyboard.");
  const grid=put(root,"div","visual-grid");
  for(const item of data.scenes){
   const card=put(grid,"article","visual-card");
   put(card,"small","","SCÈNE "+String(item.scene_number).padStart(2,"0"));
   put(card,"h3","",item.title);
   if(item.image_status==="ready"){
    const image=put(card,"img","image-preview");
    image.alt="Illustration privée de la scène "+item.scene_number;
    image.loading="lazy";
    image.src="/studio/api/runs/"+id+"/scenes/"+item.scene_number+"/image";
   }else put(card,"div","visual-placeholder","Image : "+({
    not_generated:"non générée",generating:"génération en cours",
    failed:"échec à diagnostiquer"}[item.image_status]||item.image_status));
   const generation=item.generation;
   if(generation){
    if(Number.isFinite(generation.duration_seconds))put(card,"p","","Durée : "+generation.duration_seconds.toFixed(2)+" s");
    if(generation.provenance?.character_reference_sha256)put(card,"p","","Repères personnages conservés dans l'historique.");
    if(generation.outcome_uncertain||item.image_status==="generating")
     put(card,"p","warning","Résultat en attente ou incertain. Vérifiez le moteur avant toute reprise ; aucune nouvelle génération automatique.");
    else if(item.image_status==="failed")put(card,"p","warning","Génération échouée. Le diagnostic est conservé ; aucune relance automatique.");
   }
   const details=put(card,"details");
   put(details,"summary","","Consulter le prompt image");
   put(details,"p","",item.prompt);
   if(item.image_status==="not_generated"){
    const button=put(card,"button","btn primary","Générer cette image");
    button.type="button";button.disabled=!data.approved;
    if(!data.approved)button.title="Validez d'abord l'analyse et le storyboard";
    button.addEventListener("click",async()=>{
     button.disabled=true;button.textContent="Génération en cours…";
     try{
      await api("/studio/api/runs/"+id+"/scenes/"+item.scene_number+"/image","POST");
      alertUser("Image produite et historisée pour la scène "+item.scene_number+".");
     }catch(e){alertUser(message(e),true);}
     finally{if(s.run?.id===id&&s.tab==="visuals")await visuals();}
    });
   }
  }
  if(!data.approved)put(root,"p","warning","Approuvez l'analyse et le storyboard pour autoriser la génération d'images. Rien n'est publié automatiquement.");
 }catch(e){if(s.run?.id===id&&s.tab==="visuals"){empty(message(e));alertUser(message(e),true);}}
}
function analysis(){
 const root=$("panel"),a=s.run.analysis;root.replaceChildren();if(!a)return empty("Analyse indisponible.");
 const box=put(root,"article","card");put(box,"div","overline","ANALYSE NARRATIVE");put(box,"h3","",a.angle);put(box,"p","",a.message);put(box,"h4","","Points à vérifier avant publication");
 const ul=put(box,"ul");(a.historical_checks||[]).forEach(v=>put(ul,"li","",v));decisions(root,"analysis");
}
function fold(root,label,value){const d=put(root,"details");put(d,"summary","",label);put(d,"pre","",typeof value==="string"?value:JSON.stringify(value||{},null,2));}
async function historyView(){
 empty("Chargement de l’historique…");const id=s.run.id;
 try{const x=await api("/studio/api/runs/"+id+"/history");if(s.tab!=="history"||s.run?.id!==id||!s.csrf)return;
  const root=$("panel");root.replaceChildren();if(!x.steps?.length)return empty("Aucun traitement historisé.");
  x.steps.forEach((h,i)=>{const c=put(root,"article","card");put(c,"div","overline","ÉTAPE "+(i+1));put(c,"h3","",h.order===0?"Analyse IA":"Storyboard IA");fold(c,"Voir le prompt",h.prompt);fold(c,"Voir le résultat structuré",h.parsed);if(h.error_code)put(c,"p","warning",h.error_code);});
 }catch(e){if(s.tab==="history"&&s.run?.id===id&&s.csrf)empty(message(e));}
}
async function reviews(reset=true){
 if(reset){s.reviews=[];s.nextReview=null;}empty("Chargement des décisions…");const id=s.run.id;
 try{let url="/studio/api/runs/"+id+"/reviews?limit=20";if(!reset&&s.nextReview)url+="&before_revision="+s.nextReview;
  const x=await api(url);if(s.tab!=="reviews"||s.run?.id!==id||!s.csrf)return;
  s.reviews.push(...(x.reviews||[]));s.nextReview=x.next_before_revision;const root=$("panel");root.replaceChildren();
  if(!s.reviews.length)return empty("Aucune décision humaine enregistrée.");
  const card=put(root,"article","card");put(card,"h3","","Journal des décisions");
  for(const r of s.reviews){const e=put(card,"div","history-entry");put(e,"strong","","Révision "+r.revision+" · "+(names[r.step]||r.step)+" · "+(verbs[r.action]||r.action));put(e,"p","",date(r.created_at)+(r.comment?" · "+r.comment:""));fold(e,"Consulter cette version",r.effective_output);}
  if(s.nextReview){const b=put(root,"button","btn secondary","Décisions précédentes ↓");b.type="button";b.addEventListener("click",()=>reviews(false));}
 }catch(e){if(s.tab==="reviews"&&s.run?.id===id&&s.csrf)empty(message(e));}
}
async function refresh(){
 if(!s.run)return;
 const id=s.run.id,request=s.openRequest;
 try{
  const updated=await api("/studio/api/runs/"+id);
  if(request!==s.openRequest||s.run?.id!==id||!s.csrf)return;
  s.run=updated;
  if(s.run.status==="failed"&&s.pending?.runId===id)s.pending=null;
  render();
  await list(true);
  if(request===s.openRequest&&s.run?.id===id)alertUser("Histoire actualisée.");
 }catch(e){if(request===s.openRequest&&s.run?.id===id)alertUser(message(e),true);}
}
async function reconcile(){
 if(!s.run||s.run.status!=="running")return;
 const id=s.run.id,request=s.openRequest;
 const b=$("reconcile");b.disabled=true;
 try{
  const run=await api("/studio/api/runs/"+id+"/reconcile","POST");
  if(request!==s.openRequest||s.run?.id!==id||!s.csrf)return;
  s.run=run;
  if(run.status==="failed"&&s.pending?.runId===id)s.pending=null;
  render();await list(true);
  if(request===s.openRequest&&s.run?.id===id)
   alertUser(run.status==="failed"?"Génération interrompue confirmée et historisée. Vous pouvez relancer le brief.":"Cette génération n'a pas dépassé le seuil de dix minutes. Réessayez après actualisation.",run.status==="failed");
 }catch(e){if(request===s.openRequest&&s.run?.id===id)alertUser(message(e),true);}
 finally{b.disabled=false;}
}
// Form fields map exactly to the Pydantic Analysis/Storyboard contracts.
// No generated HTML or JSON editing is necessary: all values are plain text inputs.
function editField(root,id,label,value,options={}){
 const block=put(root,"div","edit-field"),caption=put(block,"label","",label);
 caption.htmlFor=id;
 const control=put(block,options.multiline?"textarea":"input","");
 control.id=id;control.name=id;
 if(!options.multiline)control.type=options.numeric?"number":"text";
 else control.rows=options.rows||2;
 if(options.numeric){control.min="1";control.max="180";control.step="1";}
 else control.maxLength=options.max||4000;
 control.required=options.required!==false;
 control.value=String(value??"");
 return control;
}
function editList(root,id,label,values,required=false){
 return editField(root,id,label,(values||[]).join("\n"),{multiline:true,required,max:48000});
}
function buildEditor(){
 const root=$("editFields");root.replaceChildren();
 const result=s.run[s.step]||{};
 if(s.step==="analysis"){
  editField(root,"edit-angle","Angle du récit",result.angle,{max:200});
  editField(root,"edit-message","Message éditorial",result.message,{multiline:true,rows:3});
  editList(root,"edit-checks","Affirmations historiques à vérifier (une par ligne)",result.historical_checks);
 }else{
  editField(root,"edit-title","Titre du storyboard",result.title,{max:200});
  editField(root,"edit-synopsis","Synopsis",result.synopsis,{multiline:true,rows:3});
  const profiles=put(root,"fieldset","edit-profiles");
  put(profiles,"legend","","Personnages et fiches");
  const allNames=[...new Set([...(result.cast||[]).map(p=>p.name),...(result.scenes||[]).flatMap(sc=>sc.characters||[])])];
  const editableCast=allNames.map(name=>(result.cast||[]).find(p=>p.name===name)||{name,appearance:"",personality:"",role:""});
  if(editableCast.length>12)put(profiles,"p","warning","Maximum 12 profils. Réduisez les personnages du scénario avant d'enregistrer.");
  editableCast.slice(0,12).forEach((person,i)=>{
   const p="edit-person-"+i+"-";
   editField(profiles,p+"name","Personnage "+(i+1),person.name,{max:200});
   editField(profiles,p+"appearance","Apparence",person.appearance,{multiline:true,max:4000});
   editField(profiles,p+"personality","Personnalité",person.personality,{max:200});
   editField(profiles,p+"role","Rôle",person.role,{max:200});
  });
  const plan=put(root,"p","tip","La durée totale doit être exactement de "+s.run.brief.duration_seconds+" secondes. Chaque scène est enregistrée dans l'ordre actuel.");
  plan.id="edit-duration-help";
  (result.scenes||[]).forEach((scene,i)=>{
   const section=put(root,"fieldset","edit-scene");
   put(section,"legend","","Scène "+(i+1));
   const base="edit-scene-"+i+"-";
   editField(section,base+"title","Titre",scene.title,{max:200});
   editField(section,base+"duration_seconds","Durée (secondes)",scene.duration_seconds,{numeric:true});
   editField(section,base+"narration","Narration",scene.narration,{multiline:true,rows:3});
   editField(section,base+"visual_description","Description visuelle",scene.visual_description,{multiline:true,rows:3});
   editList(section,base+"characters","Personnages (un par ligne)",scene.characters);
   editField(section,base+"landscape","Paysage",scene.landscape,{max:200});
   editList(section,base+"colors","Couleurs (une par ligne)",scene.colors,true);
   editField(section,base+"shot","Plan de caméra",scene.shot,{max:200});
   editField(section,base+"emotion","Émotion",scene.emotion,{max:200});
   editField(section,base+"sound","Son",scene.sound,{max:200});
   editField(section,base+"image_prompt","Prompt image",scene.image_prompt,{multiline:true,rows:3});
  });
 }
}
function editedList(id){return $(id).value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);}
function revisedOutput(){
 if(s.step==="analysis")return {
  angle:$("edit-angle").value.trim(),
  message:$("edit-message").value.trim(),
  historical_checks:editedList("edit-checks")
 };
 const scenes=(s.run.storyboard?.scenes||[]).map((scene,i)=>{
  const p="edit-scene-"+i+"-";
  return {
   title:$(p+"title").value.trim(),
   duration_seconds:Number($(p+"duration_seconds").value),
   narration:$(p+"narration").value.trim(),
   visual_description:$(p+"visual_description").value.trim(),
   characters:editedList(p+"characters"),
   landscape:$(p+"landscape").value.trim(),
   colors:editedList(p+"colors"),
   shot:$(p+"shot").value.trim(),
   emotion:$(p+"emotion").value.trim(),
   sound:$(p+"sound").value.trim(),
   image_prompt:$(p+"image_prompt").value.trim()
  };
 });
 if(scenes.length!==s.run.brief.scene_count)
  throw Error("Le nombre de scènes ne correspond pas au brief.");
 if(scenes.some(x=>!Number.isInteger(x.duration_seconds)||x.duration_seconds<1)||
    scenes.reduce((sum,x)=>sum+x.duration_seconds,0)!==s.run.brief.duration_seconds)
  throw Error("La durée totale des scènes doit être de "+s.run.brief.duration_seconds+" secondes.");
 if(scenes.some(x=>x.colors.length<1||x.colors.length>8||x.characters.length>12))
  throw Error("Chaque scène accepte de 1 à 8 couleurs et au maximum 12 personnages.");
 const cast=[...document.querySelectorAll('[id^="edit-person-"][id$="-name"]')].map((input,i)=>{const p="edit-person-"+i+"-";return {
  name:$(p+"name").value.trim(),appearance:$(p+"appearance").value.trim(),
  personality:$(p+"personality").value.trim(),role:$(p+"role").value.trim()
 };});
 if(cast.length>12)throw Error("Maximum 12 profils de personnages.");
 return {title:$("edit-title").value.trim(),synopsis:$("edit-synopsis").value.trim(),cast,scenes};
}
function openReview(step,action="accept"){
 s.step=step;$("reviewError").hidden=true;$("reviewError").textContent="";
 $("reviewTitle").textContent=names[step];$("reviewAction").value=action;
 $("reviewComment").value="";$("confirmReview").checked=false;
 $("reviewHelp").textContent=step==="analysis"?"Une révision de l’analyse invalide le storyboard.":"Une révision crée un nouveau scénario sans effacer le précédent.";
 buildEditor();toggleReview();$("reviewDialog").showModal();
}
function toggleReview(){
 const revised=$("reviewAction").value==="revise";
 $("editFields").hidden=!revised;
 $("editFields").querySelectorAll("input,textarea").forEach(input=>input.disabled=!revised);
 $("reviewComment").required=$("reviewAction").value!=="accept";
 $("commentRequired").textContent=$("reviewAction").value==="accept"?"(facultatif)":"(obligatoire)";
}
async function sendReview(ev){
 ev.preventDefault();
 const r=s.run;if(!r)return;
 const request=s.openRequest,step=s.step,b=$("submitReview");b.disabled=true;
 $("reviewError").hidden=true;
 const payload={action:$("reviewAction").value,expected_revision:r.review_revision||0,comment:$("reviewComment").value.trim()};
 if(payload.action==="revise"){
  try{payload.revised_output=revisedOutput();}
  catch(error){$("reviewError").hidden=false;$("reviewError").textContent=error.message;b.disabled=false;return;}
 }
 try{
  const updated=await api("/studio/api/runs/"+r.id+"/steps/"+step+"/review","POST",payload);
  if(request!==s.openRequest||s.run?.id!==r.id||!s.csrf)return;
  s.run=updated;
  $("reviewDialog").close();render();await list(true);
  if(request===s.openRequest&&s.run?.id===r.id)alertUser("Décision enregistrée et historisée.");
 }catch(e){
  if(request!==s.openRequest||s.run?.id!==r.id||!s.csrf)return;
  if(e.status===409){$("reviewDialog").close();await refresh();if(request===s.openRequest&&s.run?.id===r.id)alertUser(message(e),true);}
  else{$("reviewError").hidden=false;$("reviewError").textContent=message(e);}
 }finally{b.disabled=false;}
}
async function create(ev){
 ev.preventDefault();const b=$("submitNew");b.disabled=true;b.textContent="Génération en cours…";
 const brief={topic:$("topic").value.trim(),genre:$("genre").value,duration_seconds:Number($("duration").value),
 scene_count:Number($("scenes").value),audience:$("audience").value.trim(),tone:$("tone").value.trim(),sources:[]};
 const fp=JSON.stringify(brief);if(!s.pending||s.pending.fp!==fp)s.pending={fp,key:crypto.randomUUID()};
 try{const r=await api("/studio/api/runs","POST",brief,{"Idempotency-Key":s.pending.key});
  if(["queued","running"].includes(r.status))s.pending.runId=r.id;else s.pending=null;
  $("newDialog").close();if(!["queued","running"].includes(r.status))$("newForm").reset();await list(true);await openRun(r.id);
  if(r.status==="queued")alertUser("Histoire en attente de traitement. Son état s’actualise automatiquement.");
  else if(r.status==="running")alertUser("Génération en cours. Son état s’actualise automatiquement.");
  else alertUser("Histoire générée. Vérifiez toutes les scènes avant validation.");
 }catch(e){$("newDialog").close();
  const failed=e.data?.status==="failed"&&uuid.test(e.data?.id||"");
  if(failed)s.pending=null;
  else if(uuid.test(e.data?.id||"")&&s.pending)s.pending.runId=e.data.id;
  if(uuid.test(e.data?.id||""))await openRun(e.data.id);
  alertUser(failed?"Cette génération a échoué et reste historisée. Une nouvelle tentative utilisera une nouvelle clé.":message(e)+" La même clé sera conservée tant que l'issue de la requête reste incertaine.",true);
 }finally{b.disabled=false;b.textContent="Générer le storyboard →";}
}
function home(push=true){s.coverToken++;s.openRequest++;s.run=null;showWorkspace("library");$("crumb").textContent="Histoires";if(push&&location.hash)history.pushState(null,"",location.pathname+location.search);renderList();closeNav();}
function bind(){
 $("loginForm").addEventListener("submit",login);$("logout").addEventListener("click",logout);
 for(const id of ["sideCreate","heroCreate","emptyCreate","libraryCreate"])$(id).addEventListener("click",()=>{closeNav();$("newDialog").showModal();});
 $("home").addEventListener("click",()=>home());$("conceptionNav").addEventListener("click",()=>showConception());window.addEventListener("popstate",()=>{const id=location.hash.slice(5);if(location.hash==="#conception")showConception();else if(location.hash.startsWith("#run/")&&uuid.test(id))openRun(id);else home(false);});$("openId").addEventListener("click",()=>$("idDialog").showModal());
 $("idForm").addEventListener("submit",e=>{e.preventDefault();const id=$("runId").value.trim();if(!uuid.test(id))return alertUser("Identifiant UUID invalide.",true);$("idDialog").close();openRun(id);});
 document.querySelectorAll(".close").forEach(b=>b.addEventListener("click",()=>b.closest("dialog").close()));
 document.querySelectorAll("dialog").forEach(d=>d.addEventListener("click",e=>{if(e.target===d)d.close();}));
 $("newForm").addEventListener("submit",create);$("reviewForm").addEventListener("submit",sendReview);$("reviewAction").addEventListener("change",toggleReview);
 $("menu").addEventListener("click",()=>{const x=$("sidebar").classList.toggle("open");$("menu").setAttribute("aria-expanded",String(x));});
 $("filter").addEventListener("input",renderList);$("more").addEventListener("click",()=>list(false));$("refresh").addEventListener("click",refresh);$("reconcile").addEventListener("click",reconcile);
 $("detailBack").addEventListener("click",()=>home());$("exportStory").addEventListener("click",exportStory);
 $("quickReview").addEventListener("click",()=>openReview("storyboard"));$("editStory").addEventListener("click",()=>{if(!$("editStory").disabled)openReview("storyboard","revise");});
 const tabs=[...document.querySelectorAll("[data-tab]")];
 tabs.forEach((b,i)=>{b.addEventListener("click",()=>{s.composerCategory=b.dataset.tab==="history"?"history":"overview";tab(b.dataset.tab);renderComposer();});b.addEventListener("keydown",e=>{if(!["ArrowRight","ArrowLeft","Home","End"].includes(e.key))return;e.preventDefault();const position=e.key==="Home"?0:e.key==="End"?tabs.length-1:(i+(e.key==="ArrowRight"?1:tabs.length-1))%tabs.length;const next=tabs[position];next.focus();tab(next.dataset.tab);});});
}
bind();boot();
window.setInterval(pollRun,4000);
})();
