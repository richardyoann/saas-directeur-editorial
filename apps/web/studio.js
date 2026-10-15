/* Arvor Studio: secrets are server-side; DOM uses textContent for user data. */
(() => {
"use strict";
const $ = id => document.getElementById(id);
const s = {csrf:null,runs:[],next:null,run:null,tab:"storyboard",pending:null,step:"storyboard",reviews:[],nextReview:null,openRequest:0,pollBusy:false};
const uuid=/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const states={queued:"En attente",waiting_validation:"À valider",changes_requested:"À retravailler",approved:"Approuvé",running:"En cours",failed:"Échec"};
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
function lock(){s.csrf=null;s.run=null;s.runs=[];s.openRequest++;document.querySelectorAll("dialog[open]").forEach(d=>d.close());$("login").hidden=false;$("app").hidden=true;$("password").value="";}
function unlock(){ $("login").hidden=true;$("app").hidden=false;$("loginError").hidden=true; }
async function boot(){try{const x=await api("/studio/session");if(!x.authenticated)return lock();s.csrf=x.csrf;unlock();await list(true);const id=location.hash.replace("#run/","");if(uuid.test(id)&&location.hash.startsWith("#run/"))await openRun(id);}catch(e){lock();$("loginError").hidden=false;$("loginError").textContent=message(e);}}
async function login(e){e.preventDefault();$("loginButton").disabled=true;try{const x=await api("/studio/session","POST",{password:$("password").value});s.csrf=x.csrf;unlock();$("password").value="";await list(true);const id=location.hash.slice(5);if(location.hash.startsWith("#run/")&&uuid.test(id))await openRun(id);}catch(err){$("loginError").hidden=false;$("loginError").textContent=err.status===401?"Mot de passe incorrect.":message(err);}finally{$("loginButton").disabled=false;}}
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
 $("count").textContent=s.runs.length+(s.next?"+":"");$("total").textContent=$("count").textContent;
 $("pending").textContent=s.runs.filter(r=>["waiting_validation","changes_requested"].includes(r.status)).length;
 $("approved").textContent=s.runs.filter(r=>r.status==="approved").length;$("more").hidden=!s.next;
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
 }catch(e){if(e.status!==401)alertUser(message(e),true);}
 finally{s.pollBusy=false;}
}
function closeNav(){$("sidebar").classList.remove("open");$("menu").setAttribute("aria-expanded","false");}
async function openRun(id){
 if(!uuid.test(id))return alertUser("Identifiant UUID invalide.",true);
 const request=++s.openRequest;
 try{const result=await api("/studio/api/runs/"+id);if(request!==s.openRequest||!s.csrf)return;
 s.run=result;s.tab="storyboard";s.reviews=[];s.nextReview=null;
 const target="#run/"+id;if(location.hash!==target)history.pushState(null,"",target);
 $("empty").hidden=true;$("detail").hidden=false;render();renderList();closeNav();$("detail").scrollIntoView({behavior:"smooth",block:"start"});}
 catch(e){if(request===s.openRequest)alertUser(message(e),true);}
}
function render(){
 if(!s.run)return;const r=s.run,title=r.storyboard?.title||r.brief?.topic||"Sans titre";
 $("storyTitle").textContent=title;$("crumb").textContent=title;
 $("storyMeta").textContent=(r.brief?.topic||"Brief indisponible")+" · "+date(r.created_at);
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
async function refresh(){if(!s.run)return;try{s.run=await api("/studio/api/runs/"+s.run.id);if(s.run.status==="failed"&&s.pending?.runId===s.run.id)s.pending=null;render();await list(true);alertUser("Histoire actualisée.");}catch(e){alertUser(message(e),true);}}
async function reconcile(){
 if(!s.run||s.run.status!=="running")return;
 const b=$("reconcile");b.disabled=true;
 try{const run=await api("/studio/api/runs/"+s.run.id+"/reconcile","POST");
  s.run=run;if(run.status==="failed"&&s.pending?.runId===run.id)s.pending=null;
  render();await list(true);
  alertUser(run.status==="failed"?"Génération interrompue confirmée et historisée. Vous pouvez relancer le brief.":"Cette génération n'a pas dépassé le seuil de dix minutes. Réessayez après actualisation.",run.status==="failed");
 }catch(e){alertUser(message(e),true);}
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
 return {title:$("edit-title").value.trim(),synopsis:$("edit-synopsis").value.trim(),cast:s.run.storyboard?.cast||[],scenes};
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
 ev.preventDefault();const r=s.run;if(!r)return;const b=$("submitReview");b.disabled=true;
 $("reviewError").hidden=true;
 const payload={action:$("reviewAction").value,expected_revision:r.review_revision||0,comment:$("reviewComment").value.trim()};
 if(payload.action==="revise"){
  try{payload.revised_output=revisedOutput();}
  catch(error){$("reviewError").hidden=false;$("reviewError").textContent=error.message;b.disabled=false;return;}
 }
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
function home(push=true){s.openRequest++;s.run=null;$("detail").hidden=true;$("empty").hidden=false;$("crumb").textContent="Bibliothèque";if(push&&location.hash)history.pushState(null,"",location.pathname+location.search);renderList();closeNav();}
function bind(){
 $("loginForm").addEventListener("submit",login);$("logout").addEventListener("click",logout);
 for(const id of ["sideCreate","heroCreate","emptyCreate"])$(id).addEventListener("click",()=>{closeNav();$("newDialog").showModal();});
 $("home").addEventListener("click",()=>home());window.addEventListener("popstate",()=>{const id=location.hash.slice(5);if(location.hash.startsWith("#run/")&&uuid.test(id))openRun(id);else home(false);});$("openId").addEventListener("click",()=>$("idDialog").showModal());
 $("idForm").addEventListener("submit",e=>{e.preventDefault();const id=$("runId").value.trim();if(!uuid.test(id))return alertUser("Identifiant UUID invalide.",true);$("idDialog").close();openRun(id);});
 document.querySelectorAll(".close").forEach(b=>b.addEventListener("click",()=>b.closest("dialog").close()));
 document.querySelectorAll("dialog").forEach(d=>d.addEventListener("click",e=>{if(e.target===d)d.close();}));
 $("newForm").addEventListener("submit",create);$("reviewForm").addEventListener("submit",sendReview);$("reviewAction").addEventListener("change",toggleReview);
 $("menu").addEventListener("click",()=>{const x=$("sidebar").classList.toggle("open");$("menu").setAttribute("aria-expanded",String(x));});
 $("filter").addEventListener("input",renderList);$("more").addEventListener("click",()=>list(false));$("refresh").addEventListener("click",refresh);$("reconcile").addEventListener("click",reconcile);
 $("quickReview").addEventListener("click",()=>openReview("storyboard"));
 const tabs=[...document.querySelectorAll("[data-tab]")];
 tabs.forEach((b,i)=>{b.addEventListener("click",()=>tab(b.dataset.tab));b.addEventListener("keydown",e=>{if(!["ArrowRight","ArrowLeft","Home","End"].includes(e.key))return;e.preventDefault();const position=e.key==="Home"?0:e.key==="End"?tabs.length-1:(i+(e.key==="ArrowRight"?1:tabs.length-1))%tabs.length;const next=tabs[position];next.focus();tab(next.dataset.tab);});});
}
bind();boot();
window.setInterval(pollRun,4000);
})();