/* Deterministic async-state tests of the real Studio functions; no DOM journey. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../apps/web/studio.js'), 'utf8');

function fixture(name, endMarker) {
  const start = source.indexOf('async function ' + name + '(');
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, 'Actual Studio function must exist');
  let resolve, reject;
  const reply = new Promise((yes, no) => { resolve = yes; reject = no; });
  const trace = [];
  const state = {csrf:'session',run:{id:'A',status:'running'},openRequest:1,
    tab:name === 'historyView' ? 'history' : 'reviews',pollBusy:false,
    reviews:[],nextReview:null,runs:[]};
  const root = {replaceChildren(){trace.push('panel');}};
  const context = vm.createContext({s:state,api:()=>reply,
    document:{visibilityState:'visible'},$:()=>root,
    empty:()=>trace.push('empty'),message:()=> 'error',
    alertUser:()=>trace.push('alert'),render:()=>trace.push('render'),
    renderList:()=>trace.push('list'),put:()=>root,fold:()=>{},
    date:()=>'',names:{},verbs:{}});
  vm.runInContext(source.slice(start,end) + '\nglobalThis.invoke=' + name + ';',context);
  return {state,trace,resolve,reject,invoke:context.invoke};
}

const operations = [
  ['pollRun','function closeNav(',{id:'A',status:'failed',steps:[]}],
  ['historyView','async function reviews(', {steps:[]}],
  ['reviews','async function refresh(', {reviews:[]}],
];
for (const [name,end,data] of operations) {
  for (const failed of [false,true]) {
    test(name + ' ignores old ' + (failed ? 'error' : 'success') + ' after A -> B -> A', async()=>{
      const f=fixture(name,end);
      const pending=f.invoke();
      f.trace.length=0;
      f.state.openRequest+=2;
      const current={id:'A',status:'running',marker:'new visit'};
      f.state.run=current;
      failed ? f.reject({status:503}) : f.resolve(data);
      await pending;
      assert.equal(f.state.run,current);
      assert.deepEqual(f.trace,[]);
    });
  }
  test(name + ' ignores a delayed response after logout', async()=>{
    const f=fixture(name,end);
    const pending=f.invoke();
    f.trace.length=0;
    f.state.csrf=null;f.state.run=null;f.state.openRequest++;
    f.resolve(data);
    await pending;
    assert.equal(f.state.run,null);
    assert.deepEqual(f.trace,[]);
  });
  test(name + ' still handles the current response', async()=>{
    const f=fixture(name,end);
    const pending=f.invoke();
    f.trace.length=0;f.resolve(data);await pending;
    assert.ok(f.trace.length > 0, 'Current response must not be discarded');
  });
}
