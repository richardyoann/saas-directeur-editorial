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
const reviews=Array.from({length:40},(_,i)=>({revision:40-i,created_at:new Date(Date.UTC(2026,0,40-i)).toISOString(),step:'analysis',comment:'Decision '+i,action:'accept',valid:true}));
const sandbox={state:{storyId:'story-b',journalFilter:'Tout',journalQuery:'',journalPage:3},
 journalData:null,journalError:null,journalPage:1,journalBeforeRevision:null,journalHasMoreReviews:false,journalLoadingOlder:false,
 escapeHtml:x=>String(x),escapeAttr:x=>String(x),formatDay:x=>String(x),ico:()=>'',btn:()=>'',render(){},
 api:async url=>url.endsWith('/history')?{steps:[]}:{reviews}};
vm.createContext(sandbox);vm.runInContext(code,sandbox);
(async()=>{await sandbox.loadJournal();
 assert.equal(sandbox.state.journalPage,1,'loading a different story must reset the state page to 1');
 assert.match(sandbox.renderJournal(),/1 sur 3/,'the journal must render page 1 of the new story');
 console.log('journal page reset: new story starts on page 1');
})().catch(e=>{console.error(e.message);process.exitCode=1});
