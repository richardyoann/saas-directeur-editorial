const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(process.argv[2]||path.resolve(__dirname,'../../apps/web/arvor_next.js'),'utf8');
const begin=source.indexOf('async function loadAdmin()');
const end=source.indexOf('function closeMobile()',begin);
assert.ok(begin>=0&&end>begin);
async function scenario(failure){
 const sandbox={adminData:null,commitsData:null,ciData:null,adminError:null,render(){},api:async(url)=>{
   if(failure&&url.includes(failure))throw Object.assign(Error('private detail must not be shown'),{status:502});
   return url.includes('/commits')?{commits:[]}:url.includes('/ci?')?{runs:[]}:{configured:true};
 }};
 vm.createContext(sandbox);vm.runInContext(source.slice(begin,end),sandbox);await sandbox.loadAdmin();
 if(failure){assert.ok(sandbox.adminError,'partial source failure must be visible');assert.ok(!sandbox.adminError.includes('private detail'));}
 else{assert.equal(sandbox.adminError,null);assert.ok(sandbox.adminData);assert.deepEqual(Array.from(sandbox.commitsData.commits),[]);}
}
(async()=>{await scenario(null);await scenario('/commits');await scenario('/ci?');console.log('3 administration source scenarios passed');})().catch(e=>{console.error(e.message);process.exitCode=1});
