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
function createSandbox(failure){
 const state={storyId:'story-123',journalFilter:'Tout',journalQuery:'',journalPage:1};
 const step={order:0,finished_at:'2026-11-09T10:00:00Z',parsed:true,prompt:'Analyse générée',prompt_version:'v1',response_metadata:{model:'model',provider:'provider'}};
 const review={created_at:'2026-11-09T09:00:00Z',step:'analysis',comment:'Décision validée',action:'accept',valid:true,revision:2,source_result_id:'review-1',actor_id:'editor'};
 return {state,journalData:null,journalError:null,
  escapeHtml:x=>String(x),escapeAttr:x=>String(x),formatDay:x=>String(x),ico:()=>'',btn:()=>'',render(){},
  api:async(url)=>{
   if((failure==='history'||failure==='both')&&url.endsWith('/history'))throw Error('private history detail');
   if((failure==='reviews'||failure==='both')&&url.includes('/reviews?'))throw Error('private review detail');
   return url.endsWith('/history')?{steps:[step]}:{reviews:[review]};
  }};
}
async function runCase(failure,expectedKind,expectedWarning){
 const sandbox=createSandbox(failure);vm.createContext(sandbox);vm.runInContext(code,sandbox);
 await sandbox.loadJournal();const html=sandbox.renderJournal();
 if(expectedKind){
  assert.ok(sandbox.journalData,'available journal source must remain visible');
  assert.deepEqual(Array.from(sandbox.journalData.rows,row=>row.kind).sort(),expectedKind);
  assert.equal(sandbox.journalError,expectedWarning);
  if(expectedWarning){
   assert.ok(html.includes(expectedWarning),'partial source warning must be rendered');
   assert.ok(!html.includes('Journal indisponible.'),'partial data must not be replaced by the full failure screen');
  }
 }else{
  assert.equal(sandbox.journalData,null);
  assert.ok(sandbox.journalError);
  assert.ok(html.includes('Journal indisponible.'));
 }
 if(failure==='reviews'||failure==='history'){
  assert.ok(!html.includes('private history detail'));
  assert.ok(!html.includes('private review detail'));
 }
}
(async()=>{
 await runCase(null,['decision','ia'],null);
 await runCase('reviews',['ia'],'Historique des décisions indisponible.');
 await runCase('history',['decision'],'Historique des traitements indisponible.');
 await runCase('both',null,null);
 console.log('4 journal source scenarios passed');
})().catch(e=>{console.error(e.message);process.exitCode=1});
