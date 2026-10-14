/* Arvor Studio: secrets are server-side; DOM uses textContent for user data. */
(() => {
"use strict";
const $ = id => document.getElementById(id);
const s = {csrf:null,runs:[],next:null,run:null,tab:"storyboard",pending:null,step:"storyboard",reviews:[],nextReview:null};
const uuid=/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const states={waiting_validation:"À valider",changes_requested:"À retravailler",approved:"Approuvé",running:"En cours",failed:"Échec"};
const names={analysis:"Analyse",storyboard:"Storyboard"};
const verbs={accept:"Accepté",reject:"Changements demandés",revise:"Révision"};
function elem(tag,cls,value){const x=document.createElement(tag);if(cls)x.className=cls;if(value!==undefined&&value!==null)x.textContent=String(value);return x;}
function put(root,tag,cls,value){const x=elem(tag,cls,value);root.append(x);return x;}
function date(d){const x=new Date(d);return isNaN(x.getTime())?"Date inconnue":x.toLocaleString("fr-FR",{dateStyle:"medium",timeStyle:"short"});}
function message(e){return ({401:"Session expirée. Reconnectez-vous.",403:"Accès refusé.",404:"Histoire introuvable.",409:"Conflit de version : actualisez avant toute nouvelle décision.",422:"Données non conformes : vérifiez le schéma et les durées.",429:"Trop de tentatives de connexion.",502:"API indisponible : ne réessayez pas automatiquement.",503:"Service non configuré ou indisponible.",504:"Délai dépassé : l'état de la génération est incertain."})[e.status]||"Une erreur est survenue.";}
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
function lock(){s.csrf=null;s.run=null;$("login").hidden=false;$("app").hidden=true;$("password").value="";}
function unlock(){ $("login").hidden=true;$("app").hidden=false;$("loginError").hidden=true; }
async function boot(){try{const x=await api("/studio/session");if(!x.authenticated)return lock();s.csrf=x.csrf;unlock();await list(true);const id=location.hash.replace("#run/","");if(uuid.test(id)&&location.hash.startsWith("#run/"))await openRun(id);}catch(e){lock();$("loginError").hidden=false;$("loginError").textContent=message(e);}}
async function login(e){e.preventDefault();$("loginButton").disabled=true;try{const x=await api("/studio/session","POST",{password:$("password").value});s.csrf=x.csrf;unlock();$("password").value="";await list(true);}catch(err){$("loginError").hidden=false;$("loginError").textContent=err.status===401?"Mot de passe incorrect.":message(err);}finally{$("loginButton").disabled=false;}}
async function logout(){try{await api("/studio/logout","POST");s.runs=[];lock();}catch(e){if(e.status===401){s.runs=[];lock();return;}alertUser("Déconnexion non confirmée : la session peut rester active. Réessayez.",true);}}
async function list(reset=false){
 if(reset){s.runs=[];s.next=null;}
 let path="/studio/api/runs?limit=20";if(!reset&&s.next)path+="&before="+encodeURIComponent(s.next);
 try{const data=await api(path),ids=new Set(s.runs.map(x=>x.id));for(const r of data.runs||[])if(!ids.has(r.id))s.runs.push(r);s.next=data.next_before||null;renderList();}
 catch(e){renderList();alertUser(message(e),true);}
}
function renderList(){
 const root=$("runList"),q=$("filter").value.trim().toLocaleLowerCase("fr");root.replaceChildren();
 const runs=s.runs.filter(r=>(r.title||r.topic||"").toLocaleLowerCase("fr").includes(q));
 if(!runs.length)put(root,"p","","Aucune histoire correspondante dans les éléments chargés.");
 for(const r of runs){const b=put(root,"button","run-item"+(r.id===s.run?.id?" active":""));b.type="button";put(b,"strong","",r.title||r.topic||"Histoire sans titre");put(b,"small","",(states[r.status]||"Inconnu")+" · "+date(r.created_at));b.addEventListener("click",()=>openRun(r.id));}
 $("count").textContent=s.runs.length+(s.next?"+":"");$("total").textContent=$("count").textContent;
 $("pending").textContent=s.runs.filter(r=>["waiting_validation","changes_requested"].includes(r.status)).length;
 $("approved").textContent=s.runs.filter(r=>r.status==="approved").length;$("more").hidden=!s.next;
}
function closeNav(){$("sidebar").classList.remove("open");$("menu").setAttribute("aria-expanded","false");}
async function openRun(id){
 if(!uuid.test(id))return alertUser("Identifiant UUID invalide.",true);
 try{s.run=await api("/studio/api/runs/"+id);s.tab="storyboard";s.reviews=[];s.nextReview=null;
 history.replaceState(null,"","#run/"+id);$("empty").hidden=true;$("detail").hidden=false;render();renderList();closeNav();$("detail").scrollIntoView({behavior:"smooth",block:"start"});}
 catch(e){alertUser(message(e),true);}
}
function render(){
 if(!s.run)return;const r=s.run,title=r.storyboard?.title||r.brief?.topic||"Sans titre";
 $("storyTitle").textContent=title;$("crumb").textContent=title;
 $("storyMeta").textContent=(r.brief?.topic||"Brief indisponible")+" · "+date(r.created_at);
 $("status").textContent=states[r.status]||"Inconnu";$("status").className="pill "+r.status;
 $("decisionFoot").hidden=!["waiting_validation","changes_requested"].includes(r.status);tab(s.tab);
}
function tab(name){
 s.tab=name;document.querySelectorAll("[data-tab]").forEach(b=>{b.classList.toggle("active",b.dataset.tab===name);b.setAttribute("aria-selected",String(b.dataset.tab===name));});
 if(name==="storyboard")storyboard();
 if(name==="analysis")analysis();
 if(name==="history")historyView();
 if(name==="reviews")reviews(true);
}
function empty(text){$("panel").replaceChildren();put($("panel"),"div","empty-panel",text);}
function decisions(root,step){
 if(!["waiting_validation","changes_requested"].includes(s.run.status))return;
 const bar=put(root,"div","review-buttons");
 for(const [action,label] of [["accept","Accepter"],["reject","Demander des changements"],["revise","Réviser"]]){
  const b=put(bar,"button","btn "+(action==="accept"?"primary":"secondary"),label);b.type="button";b.addEventListener("click",()=>openReview(step,action));
 }
}
function storyboard(){
 const root=$("panel"),board=s.run.storyboard;root.replaceChildren();if(!board)return empty("Storyboard indisponible.");
 const box=put(root,"article","card");put(box,"div","overline","SYNOPSIS");put(box,"h3","",board.title);put(box,"p","",board.synopsis);
 const grid=put(root,"div","scene-grid");
 (board.scenes||[]).forEach((scene,i)=>{
  const item=put(grid,"article","scene");put(item,"div","scene-art","✧");const body=put(item,"div","scene-content");
  put(body,"small","","SCÈNE "+String(i+1).padStart(2,"0")+" · "+scene.duration_seconds+" S");
  put(body,"h3","",scene.title);put(body,"p","",scene.visual_description);
  const tags=put(body,"div","tags");[scene.shot,scene.emotion,scene.landscape].filter(Boolean).forEach(v=>put(tags,"span","",v));
  const dl=put(body,"dl");for(const [k,v] of [["Narration",scene.narration],["Personnages",(scene.characters||[]).join(", ")],["Couleurs",(scene.colors||[]).join(", ")],["Son",scene.sound],["Prompt image",scene.image_prompt]]){put(dl,"dt","",k);put(dl,"dd","",v||"—");}
 });
 if(s.run.storyboard_stale)put(root,"p","warning","Storyboard obsolète : une nouvelle révision est obligatoire.");
 decisions(root,"storyboard");
}
function analysis(){
 const root=$("panel"),a=s.run.analysis;root.replaceChildren();if(!a)return empty("Analyse indisponible.");
 const box=put(root,"article","card");put(box,"div","overline","ANALYSE NARRATIVE");put(box,"h3","",a.angle);put(box,"p","",a.message);put(box,"h4","","Points à vérifier avant publication");
 const ul=put(box,"ul");(a.historical_checks||[]).forEach(v=>put(ul,"li","",v));decisions(root,"analysis");
}
function fold(root,label,value){const d=put(root,"details");put(d,"summary","",label);put(d,"pre","",typeof value==="string"?value:JSON.stringify(value||{},null,2));}
async function historyView(){
 empty("Chargement de l’historique…");const id=s.run.id;
 try{const x=await api("/studio/api/runs/"+id+"/history");if(s.tab!=="history"||s.run.id!==id)return;
  const root=$("panel");root.replaceChildren();if(!x.steps?.length)return empty("Aucun traitement historisé.");
  x.steps.forEach((h,i)=>{const c=put(root,"article","card");put(c,"div","overline","ÉTAPE "+(i+1));put(c,"h3","",h.order===0?"Analyse IA":"Storyboard IA");fold(c,"Voir le prompt",h.prompt);fold(c,"Voir le résultat structuré",h.parsed);if(h.error_code)put(c,"p","warning",h.error_code);});
 }catch(e){empty(message(e));}
}
async function reviews(reset=true){
 if(reset){s.reviews=[];s.nextReview=null;}empty("Chargement des décisions…");const id=s.run.id;
 try{let url="/studio/api/runs/"+id+"/reviews?limit=20";if(!reset&&s.nextReview)url+="&before_revision="+s.nextReview;
  const x=await api(url);if(s.tab!=="reviews"||s.run.id!==id)return;
  s.reviews.push(...(x.reviews||[]));s.nextReview=x.next_before_revision;const root=$("panel");root.replaceChildren();
  if(!s.reviews.length)return empty("Aucune décision humaine enregistrée.");
  const card=put(root,"article","card");put(card,"h3","","Journal des décisions");
  for(const r of s.reviews){const e=put(card,"div","history-entry");put(e,"strong","","Révision "+r.revision+" · "+(names[r.step]||r.step)+" · "+(verbs[r.action]||r.action));put(e,"p","",date(r.created_at)+(r.comment?" · "+r.comment:""));fold(e,"Consulter cette version",r.effective_output);}
  if(s.nextReview){const b=put(root,"button","btn secondary","Décisions précédentes ↓");b.type="button";b.addEventListener("click",()=>reviews(false));}
 }catch(e){empty(message(e));}
}
async function refresh(){if(!s.run)return;try{s.run=await api("/studio/api/runs/"+s.run.id);render();await list(true);alertUser("Histoire actualisée.");}catch(e){alertUser(message(e),true);}}
function openReview(step,action="accept"){
 s.step=step;$("reviewError").hidden=true;$("reviewError").textContent="";$("reviewTitle").textContent=names[step];$("reviewAction").value=action;$("reviewComment").value="";
 $("reviewHelp").textContent=step==="analysis"?"Une révision de l’analyse invalide le storyboard.":"Une révision crée un nouveau scénario sans effacer le précédent.";
 $("revisionJson").value=JSON.stringify(s.run[step]||{},null,2);$("confirmReview").checked=false;toggleReview();$("reviewDialog").showModal();
}
function toggleReview(){const a=$("reviewAction").value;$("jsonBox").hidden=a!=="revise";$("reviewComment").required=a!=="accept";$("revisionJson").required=a==="revise";$("commentRequired").textContent=a==="accept"?"(facultatif)":"(obligatoire)";}
async function sendReview(ev){
 ev.preventDefault();const r=s.run;if(!r)return;const b=$("submitReview");b.disabled=true;
 const payload={action:$("reviewAction").value,expected_revision:r.review_revision||0,comment:$("reviewComment").value.trim()};
 if(payload.action==="revise"){try{payload.revised_output=JSON.parse($("revisionJson").value);}catch{$("reviewError").hidden=false;$("reviewError").textContent="Le JSON de révision est invalide.";b.disabled=false;return;}}
 try{s.run=await api("/studio/api/runs/"+r.id+"/steps/"+s.step+"/review","POST",payload);$("reviewDialog").close();render();await list(true);alertUser("Décision enregistrée et historisée.");}
 catch(e){if(e.status===409){$("reviewDialog").close();await refresh();alertUser(message(e),true);}else{$("reviewError").hidden=false;$("reviewError").textContent=message(e);}}
 finally{b.disabled=false;}
}
async function create(ev){
 ev.preventDefault();const b=$("submitNew");b.disabled=true;b.textContent="Génération en cours…";
 const brief={topic:$("topic").value.trim(),genre:$("genre").value,duration_seconds:Number($("duration").value),
 scene_count:Number($("scenes").value),audience:$("audience").value.trim(),tone:$("tone").value.trim(),sources:[]};
 const fp=JSON.stringify(brief);if(!s.pending||s.pending.fp!==fp)s.pending={fp,key:crypto.randomUUID()};
 try{const r=await api("/studio/api/runs","POST",brief,{"Idempotency-Key":s.pending.key});
  s.pending=null;$("newDialog").close();$("newForm").reset();await list(true);await openRun(r.id);
  alertUser("Histoire générée. Vérifiez toutes les scènes avant validation.");
 }catch(e){$("newDialog").close();if(e.data?.id&&uuid.test(e.data.id))await openRun(e.data.id);
  alertUser(message(e)+" La même clé sera utilisée lors d’une relance explicite du même brief.",true);
 }finally{b.disabled=false;b.textContent="Générer le storyboard →";}
}
function home(){s.run=null;$("detail").hidden=true;$("empty").hidden=false;$("crumb").textContent="Bibliothèque";history.replaceState(null,"",location.pathname);renderList();closeNav();}
function bind(){
 $("loginForm").addEventListener("submit",login);$("logout").addEventListener("click",logout);
 for(const id of ["sideCreate","heroCreate","emptyCreate"])$(id).addEventListener("click",()=>{closeNav();$("newDialog").showModal();});
 $("home").addEventListener("click",home);$("openId").addEventListener("click",()=>$("idDialog").showModal());
 $("idForm").addEventListener("submit",e=>{e.preventDefault();const id=$("runId").value.trim();if(!uuid.test(id))return alertUser("Identifiant UUID invalide.",true);$("idDialog").close();openRun(id);});
 document.querySelectorAll(".close").forEach(b=>b.addEventListener("click",()=>b.closest("dialog").close()));
 document.querySelectorAll("dialog").forEach(d=>d.addEventListener("click",e=>{if(e.target===d)d.close();}));
 $("newForm").addEventListener("submit",create);$("reviewForm").addEventListener("submit",sendReview);$("reviewAction").addEventListener("change",toggleReview);
 $("menu").addEventListener("click",()=>{const x=$("sidebar").classList.toggle("open");$("menu").setAttribute("aria-expanded",String(x));});
 $("filter").addEventListener("input",renderList);$("more").addEventListener("click",()=>list(false));$("refresh").addEventListener("click",refresh);
 $("quickReview").addEventListener("click",()=>openReview("storyboard"));
 const tabs=[...document.querySelectorAll("[data-tab]")];
 tabs.forEach((b,i)=>{b.addEventListener("click",()=>tab(b.dataset.tab));b.addEventListener("keydown",e=>{if(!["ArrowRight","ArrowLeft"].includes(e.key))return;e.preventDefault();const next=tabs[(i+(e.key==="ArrowRight"?1:tabs.length-1))%tabs.length];next.focus();tab(next.dataset.tab);});});
}
bind();boot();
})();