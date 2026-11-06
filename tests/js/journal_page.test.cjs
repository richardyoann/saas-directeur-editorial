const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(process.argv[2] || path.resolve(__dirname, '../../apps/web/arvor_next.js'), 'utf8');
const start = source.indexOf('async function loadJournal()');
const end = source.indexOf('async function loadAdmin()', start);
assert.ok(start >= 0 && end > start, 'journal loader must exist');
async function scenario(storyId) {
  const sandbox = {state:{storyId, journalPage:3}, journalData:null, journalError:null,
    journalPage:3, render(){}, api:async()=>({steps:[], reviews:[]})};
  vm.createContext(sandbox);
  vm.runInContext(source.slice(start,end), sandbox);
  await sandbox.loadJournal();
  assert.equal(sandbox.state.journalPage, 1, 'loading another story must reset the page used by rendering');
}
(async()=>{await scenario(null); await scenario('synthetic-story-B'); console.log('2 journal page scenarios passed');})().catch(e=>{console.error(e.message);process.exitCode=1});
