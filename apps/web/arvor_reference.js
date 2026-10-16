/* Arvor reference UI. Private API only; never HTML-inject remote text. */
(() => {
"use strict";
const $ = id => document.getElementById(id);
const create = (tag, cls, value) => {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (value !== undefined && value !== null) el.textContent = String(value);
  return el;
};
const put = (root, tag, cls, value) => {
  const el = create(tag, cls, value);
  root.append(el);
  return el;
};
const view = {
  journalRuns: [], journalNext: null, journalFilter: "all", journalText: "",
  admin: null, commits: null, ci: null, adminTab: 0, search: "",
  calendarMode: "month", calendarDate: new Date(), journalRequest: 0,
};
const formatDate = raw => {
  const date = new Date(raw);
  return Number.isFinite(date.getTime()) ?
    date.toLocaleString("fr-FR", {dateStyle:"medium",timeStyle:"short"}) : "Date inconnue";
};
const shortSHA = sha => typeof sha === "string" ? sha.slice(0, 10) : "SHA inconnu";
const stateLabel = status => ({
  queued:"En attente",running:"En cours",waiting_validation:"À relire",
  approved:"Validée",changes_requested:"À réviser",failed:"Échec",
})[status] || "Statut inconnu";
async function request(path) {
  const response = await fetch(path, {credentials:"same-origin", cache:"no-store"});
  if (!response.ok) throw new Error(response.status === 401 ?
    "Session expirée. Reconnectez-vous." : "Service indisponible (HTTP " + response.status + ").");
  return response.json();
}
function hideJournal() {
  $("journal").hidden = true;
  $("journalNav").classList.remove("selected");
}
function showJournal(push=true) {
  if ($("app").hidden) return;
  $("home").click(); // use existing controller to clean detail, tabs and in-flight requests
  document.querySelector(".hero").hidden = true;
  document.querySelector(".metrics").hidden = true;
  $("library").hidden = true;
  $("journal").hidden = false;
  $("home").classList.remove("selected");
  $("journalNav").classList.add("selected");
  $("crumb").textContent = "Journal de création";
  if (push) history.pushState(null, "", "#journal");
  else history.replaceState(null, "", "#journal");
  refreshJournal();
}
function journalHeader(root) {
  put(root,"div","overline","RIEN NE SE PERD");
  put(root,"h2","","La mémoire de vos créations.");
  put(root,"p","", "Retrouvez les versions, prompts et traitements enregistrés de vos histoires.");
  const tools = put(root,"div","arvor-controls");
  const tabs = put(tools,"div","arvor-tabs");
  for (const [id,label] of [["all","Tout"],["versions","Versions"],["prompts","Prompts"],["treatments","Traitements"]]) {
    const button = put(tabs,"button",id === view.journalFilter?"active":"",label);
    button.type = "button";
    button.setAttribute("aria-pressed",String(id===view.journalFilter));
    button.addEventListener("click",()=>{view.journalFilter=id;renderJournal();});
  }
  const search = put(tools,"input","arvor-search");
  search.type="search";search.placeholder="Rechercher une histoire…";
  search.setAttribute("aria-label","Rechercher dans le journal de création");
  search.value=view.journalText;
  search.addEventListener("input",()=>{view.journalText=search.value;renderJournal();});
}
async function refreshJournal() {
  const ticket = ++view.journalRequest;
  const container=$("journalBody");
  container.replaceChildren();
  put(container,"p","arvor-placeholder","Chargement du journal privé…");
  try {
    const data=await request("/studio/api/runs?limit=50");
    if(ticket!==view.journalRequest)return;
    view.journalRuns=Array.isArray(data.runs)?data.runs:[];
    view.journalNext=data.next_before || null;
    renderJournal();
  }catch(error){
    container.replaceChildren();
    put(container,"p","arvor-error",error.message);
  }
}
function renderJournal() {
  if ($("journal").hidden) return;
  // The heading and search input are mounted once; typing keeps focus.
  const tabs=$("journalHeading").querySelectorAll(".arvor-tabs button");
  tabs.forEach((button,i)=>{
    const current=["all","versions","prompts","treatments"][i]===view.journalFilter;
    button.classList.toggle("active",current);
    button.setAttribute("aria-pressed",String(current));
  });
  const rows=$("journalBody");rows.replaceChildren();
  const q=view.journalText.trim().toLocaleLowerCase("fr");
  const filtered=view.journalRuns.filter(run=>
    [run.title,run.topic].filter(Boolean).join(" ").toLocaleLowerCase("fr").includes(q)
  );
  if (!filtered.length){
    put(rows,"p","arvor-placeholder",q?"Aucune histoire correspondante.":"Aucune création enregistrée.");
    return;
  }
  for (const run of filtered) {
    const item=put(rows,"article","arvor-entry");
    const button=put(item,"button","arvor-entry-main");
    button.type="button";button.setAttribute("aria-expanded","false");
    put(button,"span","arvor-entry-icon","◷");
    const content=put(button,"span","arvor-entry-text");
    put(content,"strong","",run.title||run.topic||"Histoire sans titre");
    put(content,"small","",stateLabel(run.status)+" · "+formatDate(run.created_at));
    put(button,"span","arvor-entry-arrow","›");
    const details=put(item,"div","arvor-entry-details");details.hidden=true;
    button.addEventListener("click",async()=>{
      const expand=details.hidden;
      details.hidden=!expand;button.setAttribute("aria-expanded",String(expand));
      if (expand) await fillHistory(details,run);
    });
  }
  if (view.journalNext){
    put(rows,"p","arvor-hint","Journal limité aux 50 dernières histoires. Charger davantage depuis la bibliothèque.");
  }
}
async function fillHistory(root,run){
  root.replaceChildren();
  put(root,"p","arvor-hint","Lecture des versions et traitements…");
  try {
    const encoded=encodeURIComponent(run.id);
    const [h,reviews]=await Promise.all([
      request("/studio/api/runs/"+encoded+"/history"),
      request("/studio/api/runs/"+encoded+"/reviews?limit=50"),
    ]);
    if(!root.isConnected)return;
    root.replaceChildren();
    const open=put(root,"a","arvor-inline-link","Ouvrir la fiche complète de l’histoire ↗");
    open.href="#run/"+encoded;
    open.addEventListener("click",event=>{
      event.preventDefault();hideJournal();
      const row=[...document.querySelectorAll("#runList .run-item")].find(el=>
        el.textContent.includes(run.title||run.topic||"\u0000"));
      if(row)row.click();
      else {history.pushState(null,"","#run/"+encoded);window.dispatchEvent(new PopStateEvent("popstate"));}
    });
    const items=[];
    for(const [i,step] of (h.steps||[]).entries()){
      if(view.journalFilter==="all" || view.journalFilter==="prompts")
        items.push({type:"Prompt",title:step.step||"Étape "+(i+1),
          text:step.prompt || "Prompt indisponible."});
      if(view.journalFilter==="all" || view.journalFilter==="treatments")
        items.push({type:"Traitement",title:step.step||"Étape "+(i+1),
          text:"Statut : "+(step.error_code||"terminé")+
           " · modèle : "+(step.response_metadata?.model||"non renseigné")});
    }
    for(const review of reviews.reviews||[]){
      if(view.journalFilter==="all" || view.journalFilter==="versions")
        items.push({type:"Version",title:review.step||"Relecture",
          text:"Révision "+(review.revision??review.review_revision??"?")+
               " · décision "+(review.action||"non renseignée")});
    }
    if(!items.length)put(root,"p","arvor-hint","Aucun événement de ce type enregistré.");
    for(const item of items){
      const dl=put(root,"details","arvor-trace");
      put(dl,"summary","",item.type+" · "+item.title);
      put(dl,"pre","arvor-trace-text",item.text.slice(0,2500));
    }
  }catch(error){root.replaceChildren();put(root,"p","arvor-error",error.message);}
}
function ensureJournal() {
  if($("journal"))return;
  const nav=$("conceptionNav");
  const button=create("button","nav-item","◷  Journal de création");
  button.id="journalNav";button.type="button";nav.before(button);
  const section=create("section","arvor-journal");
  section.id="journal";section.hidden=true;
  put(section,"div","arvor-section-heading").id="journalHeading";
  put(section,"div","arvor-entry-list").id="journalBody";
  $("conception").before(section);
  journalHeader($("journalHeading"));
  button.addEventListener("click",()=>showJournal());
  $("home").addEventListener("click",hideJournal);
  nav.addEventListener("click",hideJournal);
}
function repoLink(root,text,path) {
  const base=view.admin?.repository_url;
  if(!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(base||""))return;
  const el=put(root,"a","arvor-inline-link",text+" ↗");
  el.href=base+"/"+path;
  el.target="_blank";el.rel="noopener noreferrer";
}
function pill(root,label,tone="neutral"){
  return put(root,"span","arvor-pill "+tone,label);
}
function row(root,title,detail,status,path,tone="neutral"){
  const item=put(root,"article","arvor-admin-row");
  const content=put(item,"div","arvor-admin-row-text");
  put(content,"strong","",title);
  put(content,"small","",detail);
  pill(item,status,tone);
  if(path)repoLink(item,"Voir",path);
}
function selectTab(index){
  view.adminTab=index;
  [...$("arvorAdminTabs").children].forEach((button,i)=>{
    button.classList.toggle("active",i===index);
    button.setAttribute("aria-selected",String(i===index));
  });
  renderAdmin();
}
function ensureAdmin() {
  const root=$("conception");root.classList.add("arvor-admin");
  root.querySelector("h2").textContent="Le projet, en toute clarté.";
  root.querySelector(".overline").textContent="CONCEPTION · CODE · TRAÇABILITÉ";
  root.querySelector("p").textContent="Suivez les besoins, les changements et les résultats de chaque action.";
  $("conceptionContent").hidden=true; // legacy content stays available to existing code/tests
  const tabs=put(root,"div","arvor-admin-tabs");
  tabs.id="arvorAdminTabs";tabs.setAttribute("role","tablist");
  ["Vue d’ensemble","Epics & stories","Pull requests","Commits","Agenda"].forEach((text,i)=>{
    const b=put(tabs,"button","",text);
    b.type="button";b.setAttribute("role","tab");
    b.addEventListener("click",()=>selectTab(i));
  });
  const tools=put(root,"div","arvor-admin-actions");
  const search=put(tools,"input","arvor-search");
  search.type="search";search.placeholder="Rechercher dans le suivi…";
  search.setAttribute("aria-label","Rechercher dans les éléments GitHub");
  search.addEventListener("input",()=>{view.search=search.value.trim().toLocaleLowerCase("fr");renderAdmin();});
  const refresh=put(tools,"button","arvor-btn","↻ Recharger le suivi");
  refresh.type="button";refresh.addEventListener("click",()=>loadAdmin(true));
  const surface=put(root,"div","arvor-admin-surface");
  surface.id="arvorAdminSurface";surface.setAttribute("role","tabpanel");
  selectTab(0);
}
async function loadAdmin(force=false){
  if(view.admin && !force){renderAdmin();return;}
  const root=$("arvorAdminSurface");root.replaceChildren();
  put(root,"p","arvor-placeholder","Synchronisation GitHub…");
  try {
    const results=await Promise.allSettled([
      request("/studio/api/conception"),
      request("/studio/api/conception/commits?limit=70"),
      request("/studio/api/conception/ci?limit=80"),
    ]);
    if(results[0].status!=="fulfilled")throw results[0].reason;
    view.admin=results[0].value;
    view.commits=results[1].status==="fulfilled"?results[1].value:null;
    view.ci=results[2].status==="fulfilled"?results[2].value:null;
    renderAdmin();
  }catch(error){root.replaceChildren();put(root,"p","arvor-error",
    error.message+" Configurez EDITORIAL_GITHUB_READ_TOKEN et EDITORIAL_GITHUB_REPOSITORY côté serveur.");}
}
function match(text){return !view.search || String(text||"").toLocaleLowerCase("fr").includes(view.search);}
function CIMap(){
  const map=new Map();
  for(const run of view.ci?.runs||[]){
    if(!run.sha || map.has(run.sha) || run.event!=="push")continue;
    map.set(run.sha,run);
  }
  return map;
}
function renderAdmin() {
  const root=$("arvorAdminSurface");if(!root || $("conception").hidden)return;
  root.replaceChildren();
  const data=view.admin;
  if(!data){put(root,"p","arvor-placeholder","Ouvrez le suivi pour charger les données réelles.");return;}
  if(Object.values(data.source_truncated||{}).some(Boolean) ||
      view.commits?.partial || view.ci?.partial)
    put(root,"p","arvor-warning","Résultats partiels : utilisez les liens GitHub pour un historique exhaustif.");
  const prs=data.pull_requests||[],epics=data.epics||[],issues=data.issues||[],deliveries=data.deliveries||[];
  const commits=view.commits?.commits||[], ci=CIMap();
  const filtered=(arr,fn)=>arr.filter(item=>match(fn(item)));
  if(view.adminTab===0){
    const stats=put(root,"div","arvor-stats");
    for(const [n,label] of [[epics.length,"Epics"],[issues.length,"Issues"],[prs.filter(p=>p.state==="open").length,"PR ouvertes"],[deliveries.filter(d=>d.conclusion==="failure").length,"Livraisons en échec (historique chargé)"]]){
      const s=put(stats,"article","arvor-stat");put(s,"strong","",n);put(s,"span","",label);
    }
    put(root,"h3","","Avancement des epics");
    for(const e of filtered(epics,x=>x.title).slice(0,12))
      row(root,"#"+e.number+" · "+e.title,"Statut GitHub",e.state==="closed"?"Fermé":"Ouvert","issues/"+e.number,e.state==="closed"?"ok":"neutral");
    put(root,"h3","","Dernières activités");
    for(const p of prs.slice(0,10))
      row(root,"PR #"+p.number+" · "+p.title,formatDate(p.updated_at),
        p.merged_at?"Fusionnée":p.draft?"Brouillon":p.state==="open"?"Ouverte":"Fermée","pull/"+p.number);
  }else if(view.adminTab===1){
    put(root,"h3","","Epics, stories et tâches GitHub");
    if(!issues.length)put(root,"p","arvor-placeholder","Aucune issue retournée.");
    for(const x of filtered(issues,y=>y.title+" #"+y.number))
      row(root,"#"+x.number+" · "+x.title,formatDate(x.created_at),
        x.state==="closed"?"Fermée":"Ouverte","issues/"+x.number,x.state==="closed"?"ok":"neutral");
  }else if(view.adminTab===2){
    put(root,"h3","","Pull requests");
    for(const p of filtered(prs,x=>x.title+" #"+x.number)){
      const run=ci.get(p.merge_commit_sha)||ci.get(p.sha);
      const status=run?(run.conclusion==="success"?"CI OK":run.conclusion==="failure"?"CI KO":"CI "+(run.status||"en cours")):"CI non vérifiée";
      const tone=status==="CI OK"?"ok":status==="CI KO"?"ko":"neutral";
      row(root,"#"+p.number+" · "+p.title,(p.merged_at?"Fusionnée":"Statut : "+p.state)+" · "+shortSHA(p.merge_commit_sha||p.sha),status,"pull/"+p.number,tone);
    }
    if(!prs.length)put(root,"p","arvor-placeholder","Aucune PR chargée.");
  }else if(view.adminTab===3){
    put(root,"h3","","Historique réel des commits de main");
    if(!view.commits)put(root,"p","arvor-warning","Historique GitHub des commits indisponible.");
    for(const c of filtered(commits,x=>x.message+" "+x.sha))
      row(root,shortSHA(c.sha)+" · "+c.message,formatDate(c.when),"Commit Git","commit/"+c.sha);
  }else{
    buildCalendar(root,prs,commits,deliveries,view.ci?.runs||[]);
  }
}
function buildEvents(prs,commits,deliveries,ci){
  const result=[];
  for(const p of prs){
    if(p.created_at)result.push({when:p.created_at,title:"PR #"+p.number+" créée",kind:"pr",tone:"neutral",path:"pull/"+p.number});
    if(p.merged_at)result.push({when:p.merged_at,title:"PR #"+p.number+" fusionnée",kind:"pr",tone:"ok",path:"pull/"+p.number});
  }
  for(const c of commits)if(c.when)result.push({when:c.when,title:shortSHA(c.sha)+" · "+c.message,kind:"commit",tone:"neutral",path:"commit/"+c.sha});
  for(const d of deliveries)if(d.created_at)result.push({when:d.created_at,title:"Livraison "+shortSHA(d.sha),kind:"delivery",tone:d.conclusion==="success"?"ok":d.conclusion==="failure"?"ko":"neutral",path:"actions/runs/"+d.id});
  for(const r of ci)if(r.created_at)result.push({when:r.created_at,title:"CI "+shortSHA(r.sha),kind:"ci",tone:r.conclusion==="success"?"ok":r.conclusion==="failure"?"ko":"neutral",path:"actions/runs/"+r.id});
  return result.filter(e=>Number.isFinite(new Date(e.when).getTime()));
}
function localDay(d){return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");}
function buildCalendar(root,prs,commits,deliveries,ci){
  put(root,"h3","","Agenda des actions Git et GitHub");
  const controls=put(root,"div","arvor-calendar-toolbar");
  const prev=put(controls,"button","arvor-btn","‹");prev.type="button";prev.setAttribute("aria-label","Période précédente");
  const today=put(controls,"button","arvor-btn","Aujourd’hui");today.type="button";
  const next=put(controls,"button","arvor-btn","›");next.type="button";next.setAttribute("aria-label","Période suivante");
  put(controls,"strong","",view.calendarDate.toLocaleDateString("fr-FR",{month:"long",year:"numeric"}));
  const modes=put(controls,"div","arvor-calendar-modes");
  for(const [id,label] of [["month","Mois"],["week","Semaine"],["day","Jour"]]){
    const btn=put(modes,"button","arvor-btn"+(id===view.calendarMode?" active":""),label);
    btn.type="button";btn.setAttribute("aria-pressed",String(id===view.calendarMode));
    btn.addEventListener("click",()=>{view.calendarMode=id;renderAdmin();});
  }
  const change=n=>{
    const d=new Date(view.calendarDate);
    if(view.calendarMode==="month")d.setMonth(d.getMonth()+n);
    else d.setDate(d.getDate()+n*(view.calendarMode==="week"?7:1));
    view.calendarDate=d;renderAdmin();
  };
  prev.addEventListener("click",()=>change(-1));
  next.addEventListener("click",()=>change(1));
  today.addEventListener("click",()=>{view.calendarDate=new Date();renderAdmin();});
  const events=buildEvents(prs,commits,deliveries,ci);
  const calendar=put(root,"div","arvor-calendar");
  const start=new Date(view.calendarDate);start.setHours(0,0,0,0);
  let days=1;
  if(view.calendarMode==="month"){
    start.setDate(1);
    start.setDate(start.getDate()-((start.getDay()+6)%7));
    const last=new Date(view.calendarDate.getFullYear(),view.calendarDate.getMonth()+1,0);
    days=Math.ceil(((last-start)/86400000+1)/7)*7;
  }else if(view.calendarMode==="week"){
    start.setDate(start.getDate()-((start.getDay()+6)%7));
    days=7;
  }
  if(view.calendarMode!=="day")for(const name of ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"])put(calendar,"div","arvor-weekday",name);
  const grid=put(calendar,"div","arvor-calendar-grid"+(view.calendarMode==="day"?" single":""));
  for(let i=0;i<days;i++){
    const d=new Date(start);d.setDate(d.getDate()+i);
    const day=put(grid,"div","arvor-calendar-cell"+(d.getMonth()!==view.calendarDate.getMonth()&&view.calendarMode==="month"?" outside":""));
    put(day,"strong","",d.getDate());
    for(const event of events.filter(x=>localDay(new Date(x.when))===localDay(d)).slice(0,7)){
      const link=put(day,"div","arvor-event "+event.tone);
      repoLink(link,event.title,event.path);
    }
    const total=events.filter(x=>localDay(new Date(x.when))===localDay(d)).length;
    if(total>7)put(day,"small","","+"+(total-7)+" actions");
  }
}
function init(){
  ensureJournal();
  const nav=$("conceptionNav");
  nav.firstChild.textContent="♧  Administration";
  $("home").firstChild.textContent="▤  Mes histoires ";
  // Keep the #count element: the original Studio updates it after every load.
  $("library").querySelector("h2").textContent="Vos histoires commencent ici.";
  const h1=document.querySelector(".hero h1");h1.textContent="Vos histoires commencent ici.";
  document.querySelector(".hero .overline").textContent="L’IMAGINAIRE BRETON, EN MOUVEMENT";
  document.querySelector(".hero p").textContent="Du premier murmure au dernier plan, composez chaque détail.";
  ensureAdmin();
  nav.addEventListener("click",()=>{hideJournal();loadAdmin();selectTab(0);});
  window.addEventListener("popstate",()=>{
    if(location.hash==="#journal")showJournal(false);
    else hideJournal();
  });
  const app=$("app");
  new MutationObserver(()=>{
    if(!app.hidden && location.hash==="#journal" && $("journal").hidden)showJournal(false);
  }).observe(app,{attributes:true,attributeFilter:["hidden"]});
  if(!app.hidden&&location.hash==="#journal")showJournal(false);
}
init();
})();