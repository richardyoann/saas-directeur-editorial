const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(process.argv[2]||path.resolve(__dirname,'../../apps/web/arvor_next.js'),'utf8');
const loadStart=source.indexOf('async function loadJournal()');
const loadEnd=source.indexOf('async function loadAdmin()',loadStart);
const viewStart=source.indexOf('function journalVisible()');
const viewEnd=source.indexOf('function renderAdmin()',viewStart);
assert.ok(loadStart>=0&&loadEnd>loadStart&&viewStart>=0&&viewEnd>viewStart);
const code=source.slice(loadStart,loadEnd)+'\n'+source.slice(viewStart,viewEnd);
const makeReview=revision=>({revision,created_at:new Date(Date.UTC(2026,0,revision)).toISOString(),step:'analysis',comment:'Décision ancienne '+revision,action:'accept',valid:true,source_result_id:'source-'+revision,actor_id:'editor'});
const firstPage=Array.from({length:50},(_,i)=>makeReview(60-i));
const olderPage=Array.from({length:10},(_,i)=>makeReview(10-i));
let failOlder=false;const calls=[];
const sandbox={
 state:{storyId:'story-123',journalFilter:'Tout',journalQuery:'',journalPage:1},
 journalData:null,journalError:null,journalPage:1,journalBeforeRevision:null,journalHasMoreReviews:false,journalLoadingOlder:false,
 escapeHtml:x=>String(x),escapeAttr:x=>String(x),formatDay:x=>String(x),ico:()=>'',btn:()=>'',render(){},
 api:async url=>{
  calls.push(url);
  if(url.endsWith('/history'))return {steps:[]};
  if(url.includes('before_revision=')&&failOlder)throw Object.assign(Error('private upstream detail'),{status:502});
  return {reviews:url.includes('before_revision=')?olderPage:firstPage};
 }
};
vm.createContext(sandbox);vm.runInContext(code,sandbox);
(async()=>{
 await sandbox.loadJournal();
 let html=sandbox.renderJournal();
 assert.ok(html.includes('data-journal-older'),'users must be able to load decisions older than the initial 50');
 assert.equal(sandbox.journalData.rows.filter(row=>row.kind==='decision').length,50);
 assert.equal(sandbox.journalBeforeRevision,11);
 failOlder=true;await sandbox.loadOlderJournalReviews();html=sandbox.renderJournal();
 assert.equal(sandbox.journalData.rows.filter(row=>row.kind==='decision').length,50,'failed page must keep loaded decisions');
 assert.equal(sandbox.journalBeforeRevision,11,'failed page must keep cursor for retry');
 assert.ok(html.includes('Historique des décisions antérieures indisponible.'));
 assert.ok(!html.includes('private upstream detail'));
 failOlder=false;await sandbox.loadOlderJournalReviews();html=sandbox.renderJournal();
 const decisions=sandbox.journalData.rows.filter(row=>row.kind==='decision');
 assert.equal(decisions.length,60);
 assert.equal(new Set(decisions.map(row=>row.revision)).size,60);
 assert.ok(decisions.some(row=>row.revision===1));
 assert.ok(calls.includes('/studio/api/runs/story-123/reviews?limit=50&before_revision=11'));
 assert.equal(sandbox.journalHasMoreReviews,false);
 assert.ok(!html.includes('data-journal-older'));
 sandbox.state.journalPage=4;html=sandbox.renderJournal();
 assert.ok(html.includes('Décision ancienne 1'),'oldest decision must be reachable through local pagination');
 console.log('journal review pagination: 50 + 10, failed-page retry, oldest decision visible');
})().catch(e=>{console.error(e.message);process.exitCode=1});
