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
async function switchStory() {
  const begin = source.indexOf('async function navigate(');
  const finish = source.indexOf('const btn=', begin);
  assert.ok(begin >= 0 && finish > begin, 'navigation must exist');
  const pages = [];
  const sandbox = {state:{storyId:'synthetic-A',journalPage:3},
    prodData:{},mediaData:{},historyData:{},journalData:{},journalError:null,prodError:null,
    journalPage:3,stories:[],closeMobile(){},window:{scrollTo(){}},
    render(){pages.push(this.state?.journalPage)},api:async()=>({steps:[],reviews:[]})};
  // Capture the rendered page through the same state object as navigation.
  sandbox.render=()=>pages.push(sandbox.state.journalPage);
  vm.createContext(sandbox);
  vm.runInContext(source.slice(start,end)+source.slice(begin,finish),sandbox);
  await sandbox.navigate('journal','synthetic-B');
  assert.equal(sandbox.state.storyId,'synthetic-B');
  assert.ok(pages.length >= 2, 'navigation and loaded journal must render');
  assert.deepEqual(pages,[1,1], 'A page 3 to B must render page 1 immediately and after loading');
  assert.equal(sandbox.prodData,null);
  assert.equal(sandbox.mediaData,null);
}
(async()=>{await switchStory();await scenario(null);await scenario('synthetic-story-B');console.log('3 journal page scenarios passed');})().catch(e=>{console.error(e.message);process.exitCode=1});
