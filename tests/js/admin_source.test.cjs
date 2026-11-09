const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(process.argv[2]||path.resolve(__dirname,'../../apps/web/arvor_next.js'),'utf8');
const begin=source.indexOf('async function loadAdmin()');
const end=source.indexOf('function closeMobile()',begin);
assert.ok(begin>=0&&end>begin);
async function scenario(failure){
 let renders=0;
 const sandbox={
  adminData:{previous:'private'},commitsData:{commits:[{sha:'old'}]},ciData:{runs:[{id:'old'}]},
  adminError:'old error',render(){renders++},api:async(url)=>{
   if(failure&&url===failure.url)throw Object.assign(Error('private provider detail must not be shown'),{status:failure.status});
   return url.includes('/commits')?{commits:[]}:url.includes('/ci?')?{runs:[]}:{configured:true};
  }
 };
 vm.createContext(sandbox);vm.runInContext(source.slice(begin,end),sandbox);await sandbox.loadAdmin();
 if(failure){
  const expected=failure.url==='/studio/api/conception'&&failure.status===503?'Intégration GitHub non configurée.':'Suivi GitHub indisponible.';
  assert.equal(sandbox.adminError,expected,'failure must have the expected safe category');
  assert.equal(sandbox.adminData,null,'stale conception data must be cleared');
  assert.equal(sandbox.commitsData,null,'stale commit data must be cleared');
  assert.equal(sandbox.ciData,null,'stale CI data must be cleared');
  assert.ok(!sandbox.adminError.includes('private provider detail'),'provider detail must not leak');
 }else{
  assert.equal(sandbox.adminError,null);
  assert.deepEqual(Array.from(sandbox.commitsData.commits),[]);
  assert.deepEqual(Array.from(sandbox.ciData.runs),[]);
 }
 assert.equal(renders,1);
}
(async()=>{
 await scenario(null);
 await scenario({url:'/studio/api/conception/commits?limit=70',status:502});
 await scenario({url:'/studio/api/conception/ci?limit=80',status:502});
 await scenario({url:'/studio/api/conception',status:502});
 await scenario({url:'/studio/api/conception',status:503});
 console.log('5 administration source scenarios passed, including stale-state clearing and conception 503');
})().catch(e=>{console.error(e.message);process.exitCode=1});
