/* Arvor private UI extension: no secrets, no writes, real data only. */
(()=>{"use strict";
const $=id=>document.getElementById(id);
const base="https://github.com/richardyoann/saas-directeur-editorial/";
const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=String(text);if(cls)el.className=cls;return el;};
const add=(to,tag,text,cls)=>{const el=make(tag,text,cls);to.append(el);return el;};
function nav(target){$("home").click();if(target==="journal"){document.querySelector(".hero").hidden=true;document.querySelector(".metrics").hidden=true;$("library").hidden=true;$("journal").hidden=false;$("home").classList.remove("selected");$("journalNav").classList.add("selected");$("crumb").textContent="Journal de création";renderJournal();history.replaceState(null,"","#journal");}else if(target==="admin"){$("conceptionNav").click();$("journal").hidden=true;$("journalNav").classList.remove("selected");history.replaceState(null,"","#conception");}}
function renderJournal(){
 const root=$("journalContent");root.replaceChildren();add(root,"p","Chargement de l’historique des histoires…");
 fetch("/studio/api/runs?limit=50",{credentials:"same-origin",cache:"no-store"}).then(r=>{if(!r.ok)throw Error("Accès indisponible");return r.json()}).then(data=>{
 root.replaceChildren();const runs=data.runs||[];
 if(!runs.length){add(root,"p","Aucune histoire réelle enregistrée.");return;}
 add(root,"p","Historique des créations (les événements détaillés restent consultables dans chaque histoire).","arvor-hint");
 runs.forEach(run=>{const row=add(root,"button",null,"arvor-journal-row");row.type="button";add(row,"span","◷","arvor-journal-icon");const part=add(row,"span",null);add(part,"strong",run.title||run.topic||"Sans titre");add(part,"small",[(run.status||"Statut inconnu"),run.created_at?new Date(run.created_at).toLocaleString("fr-FR"):""].filter(Boolean).join(" · "));add(row,"span","›");row.addEventListener("click",()=>{nav("stories");const item=[...document.querySelectorAll("#runList button")].find(b=>b.textContent.includes(run.title||run.topic||"@@@"));if(item)item.click();else location.hash="#run/"+run.id;});});
 if(data.next_before)add(root,"p","Résultats paginés : consulter la bibliothèque pour charger davantage d'histoires.","arvor-hint");
 }).catch(()=>{root.replaceChildren();add(root,"p","Impossible de charger l’historique. Vérifiez votre session.");});
}
function navStories(){ $("journal").hidden=true;$("journalNav").classList.remove("selected");$("home").click();}
function adminTabs(){
 const root=$("conception");if($("arvorAdminTabs"))return;
 const bar=make("div",null,"arvor-admin-tabs");bar.id="arvorAdminTabs";
 ["Vue d’ensemble","Epics & stories","Pull requests","Commits","Agenda"].forEach((label,i)=>{const b=add(bar,"button",label);b.type="button";b.addEventListener("click",()=>{[...bar.children].forEach(x=>x.classList.remove("active"));b.classList.add("active");renderAdmin(i);});});
 root.insertBefore(bar,$("conceptionContent"));bar.firstChild.classList.add("active");
}
async function renderAdmin(view){
 const root=$("conceptionContent");root.replaceChildren();add(root,"p","Lecture des données GitHub…");
 try{
 const r=await fetch("/studio/api/conception",{credentials:"same-origin",cache:"no-store"});if(!r.ok)throw Error("GitHub non configuré / inaccessible");const d=await r.json();root.replaceChildren();
 const epics=d.epics||[],prs=d.pull_requests||[],deliveries=d.deliveries||[];
 const link=(host,label,path)=>{const a=add(host,"a",label+" ↗");a.href=base+path;a.target="_blank";a.rel="noopener noreferrer";};
 const row=(title,state,desc,path)=>{const el=add(root,"article",null,"arvor-admin-row");const l=add(el,"div");add(l,"strong",title);add(l,"small",desc);add(el,"span",state,"arvor-state "+(state==="OK"?"ok":state==="KO"?"ko":"neutral"));if(path)link(el,"Consulter",path);};
 if(view===0){add(root,"h3","État du dépôt");row("Epics",String(epics.length)+" éléments","Issues GitHub","issues");row("Pull requests",String(prs.length)+" éléments","Statuts Git distincts des validations CI","pulls");row("Livraisons",String(deliveries.length)+" exécutions","Une CI verte ne prouve pas la livraison PC","actions");}
 if(view===1){add(root,"h3","Epics et stories (issues accessibles)");if(!epics.length)add(root,"p","Aucun epic fourni par l’API.");epics.forEach(e=>row("#"+e.number+" · "+e.title,e.state==="closed"?"OK":"Ouvert",e.created_at||"","issues/"+e.number));}
 if(view===2){add(root,"h3","Pull requests");prs.forEach(p=>row("#"+p.number+" · "+p.title,p.merged_at?"Fusionnée":p.draft?"Brouillon":p.state==="open"?"Ouverte":"Fermée","SHA "+(p.merge_commit_sha||p.sha||"inconnu").slice(0,12),"pull/"+p.number));}
 if(view===3){add(root,"h3","Commits et traces");add(root,"p","Les SHA de merge des PR sont affichés ici. Historique complet : consulter GitHub.");prs.filter(p=>p.merge_commit_sha).forEach(p=>row((p.merge_commit_sha||"").slice(0,12),"Non vérifié","Lié à PR #"+p.number,"commit/"+p.merge_commit_sha));}
 if(view===4){add(root,"h3","Agenda des PR et livraisons");const toolbar=add(root,"div",null,"arvor-calendar-tools");["Mois","Semaine","Jour"].forEach(t=>{const b=add(toolbar,"button",t);b.type="button";b.addEventListener("click",()=>calendar(t,prs,deliveries,root));});calendar("Mois",prs,deliveries,root);}
 }catch(e){root.replaceChildren();add(root,"p","Suivi GitHub indisponible. Configurez le jeton de lecture privé côté serveur. Aucun statut n’est inventé.");}
}
function calendar(mode,prs,deliveries,root){
 const old=$("arvorCalendar");if(old)old.remove();const target=add(root,"div",null,"arvor-calendar");target.id="arvorCalendar";
 const now=new Date();const events=[...prs.map(p=>({date:p.merged_at||p.updated_at,title:"PR #"+p.number+" "+(p.merged_at?"fusionnée":"mise à jour"),status:p.merged_at?"ok":"neutral"})),...deliveries.map(x=>({date:x.created_at,title:"Livraison "+(x.sha||"").slice(0,8),status:x.conclusion==="success"?"ok":x.conclusion==="failure"?"ko":"neutral"}))].filter(x=>x.date).sort((a,b)=>new Date(b.date)-new Date(a.date));
 add(target,"h4",mode+" — "+now.toLocaleDateString("fr-FR",{month:"long",year:"numeric"}));
 const filtered=events.filter(e=>{const d=new Date(e.date);return mode==="Jour"?d.toDateString()===now.toDateString():mode==="Semaine"?Math.abs(now-d)<604800000:d.getMonth()===now.getMonth()&&d.getFullYear()===now.getFullYear();});
 if(!filtered.length)add(target,"p","Aucun événement pour cette période.");
 filtered.forEach(e=>{const p=add(target,"div",null,"arvor-calendar-event "+e.status);add(p,"time",new Date(e.date).toLocaleString("fr-FR"));add(p,"span",e.title);});
}
function boot(){const navItem=$("conceptionNav");navItem.textContent="♧  Administration";
 const journal=make("button","◷  Journal de création","nav-item");journal.id="journalNav";journal.type="button";navItem.before(journal);
 const section=make("section",null,"arvor-journal");section.id="journal";section.hidden=true;
 add(section,"div","RIEN NE SE PERD","overline");add(section,"h2","La mémoire de vos créations.");add(section,"p","Retrouvez vos histoires enregistrées et ouvrez leurs traitements et versions.");add(section,"div",null,"arvor-journal-list").id="journalContent";
 $("conception").before(section);$("conception").querySelector("h2").textContent="Le projet, en toute clarté.";
 journal.addEventListener("click",()=>nav("journal"));
 $("home").addEventListener("click",()=>{section.hidden=true;journal.classList.remove("selected");});
 navItem.addEventListener("click",()=>{section.hidden=true;journal.classList.remove("selected");adminTabs();renderAdmin(0);});
 $("home").textContent="▤  Mes histoires";
 $("library").querySelector("h2").textContent="Vos histoires commencent ici.";
 document.querySelector(".hero h1").textContent="Vos histoires commencent ici.";
 document.querySelector(".hero p").textContent="Du premier murmure au dernier plan, composez chaque détail.";
 adminTabs();
 if(location.hash==="#journal"){const check=setInterval(()=>{if(!$("app").hidden){clearInterval(check);nav("journal");}},200);setTimeout(()=>clearInterval(check),10000);}
}
boot();
})();