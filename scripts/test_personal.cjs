const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const P=require('../personal-data.js'),R=require('../tools-core.js');
const context={window:{}};
for(const file of ['index','tools'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../data/'+file+'.js'),'utf8'),context);
const data=JSON.parse(JSON.stringify(context.window.WIKI_TOOLS_DATA)),pages=JSON.parse(JSON.stringify(context.window.WIKI_DATA.pages));
const id=pages.find(p=>p.type==='character').id,other=pages.find(p=>p.type==='equipment').id;
let checks=0;
function test(name,fn){fn();checks++;console.log('PASS '+name);}
function backup(){const state=R.draw(R.newSimulation(data),'chuyu',100,data,()=>.99).state;return {
  format:'socwiki-personal',version:2,favorites:[id],notes:{[id]:'用于回归测试的笔记'},history:[id],comparison:[id],
  preferences:{theme:'dark',readerFont:19},tools:{damage:{current:{...R.defaults},presets:[{name:'方案',values:{...R.defaults,atkPanel:'3500'}}]},
  gacha:{sourceRevision:data.revision,poolId:'chuyu',state}}};}
test('full backup round-trip keeps damage plans, simulation, comparison and preferences',()=>{
  const original=backup(),decoded=P.parse(JSON.parse(JSON.stringify(original)),pages,data);
  assert.deepEqual(decoded.damage,original.tools.damage);assert.deepEqual(decoded.gacha,original.tools.gacha);
  assert.deepEqual(decoded.comparison,[id]);assert.equal(decoded.readerFont,19);assert.equal(decoded.theme,'dark');
});
test('v1 personal backup preserves tool state by leaving missing sections untouched',()=>{
  const decoded=P.parse({format:'socwiki-personal',version:1,favorites:[id,id,-1],history:[id],notes:{[id]:'旧版'},comparison:[id,other]},pages,data);
  assert.equal(decoded.damage,undefined);assert.equal(decoded.gacha,undefined);assert.deepEqual(decoded.favorites,[id]);assert.deepEqual(decoded.comparison,[id]);
});
test('individual tool exports can be restored without altering personal pages',()=>{
  const b=backup();const g=P.parse({format:'socwiki-gacha',sourceRevision:data.revision,poolId:'chuyu',...b.tools.gacha.state},pages,data);
  assert.equal(g.gacha.state.total,100);assert.equal(g.notes,undefined);
  const d=P.parse({format:'socwiki-damage',version:1,...b.tools.damage},pages,data);assert.equal(d.damage.presets[0].values.atkPanel,'3500');
});
test('wrong snapshot, invalid counters and malformed history are rejected',()=>{
  let b=backup();b.tools.gacha.sourceRevision=-1;assert.throws(()=>P.parse(b,pages,data),/卡池版本/);
  b=backup();b.tools.gacha.state.pity=1000;assert.throws(()=>P.parse(b,pages,data),/计数/);
  b=backup();b.tools.gacha.state.counts.legend=10;assert.throws(()=>P.parse(b,pages,data));
  b=backup();b.tools.gacha.state.history[0].name='不存在的角色';assert.throws(()=>P.parse(b,pages,data),/历史/);
  b=backup();b.tools.gacha.state.legendStats={};assert.throws(()=>P.parse(b,pages,data),/传说/);
});
test('damaged plans cannot partially import otherwise valid personal data',()=>{
  const b=backup();b.tools.damage.current.atkPanel='12oops';assert.throws(()=>P.parse(b,pages,data));
  b.tools.damage.current.atkPanel='3000';b.tools.damage.current.defClass='<invalid>';assert.throws(()=>P.parse(b,pages,data));
});
test('untrusted keys and oversized notes never enter the normalized backup',()=>{
  const b=backup();b.notes=JSON.parse('{"__proto__":{"polluted":true},"-1":"bad","'+id+'":"valid"}');
  const decoded=P.parse(b,pages,data);assert.deepEqual(decoded.notes,{[id]:'valid'});assert.equal({}.polluted,undefined);
  b.notes[id]='x'.repeat(30001);assert.throws(()=>P.parse(b,pages,data),/笔记/);
});
test('incoming named plans take precedence; unrelated existing plans survive',()=>{
  const existing=[{name:'同名',values:{atkPanel:'1'}},{name:'旧方案',values:{atkPanel:'2'}}];
  const incoming=[{name:'同名',values:{atkPanel:'3'}},{name:'新方案',values:{atkPanel:'4'}}];
  const merged=P.mergePresets(existing,incoming);assert.equal(merged.length,3);assert.equal(merged[0].values.atkPanel,'3');assert.equal(merged[2].name,'旧方案');
});
test('storage failure rolls back all previously changed keys',()=>{
  const saved=new Map([['socwiki.favorites','[123]'],['socwiki.notes','{"123":"existing"}']]);let writes=0;
  const storage={getItem:k=>saved.get(k)??null,setItem:(k,v)=>{writes++;if(writes===3)throw new Error('quota');saved.set(k,v);},removeItem:k=>saved.delete(k)};
  assert.throws(()=>P.commit(storage,{favorites:[id],history:[id],notes:{[id]:'new'}}),/无法保存/);
  assert.equal(saved.get('socwiki.favorites'),'[123]');assert.equal(saved.get('socwiki.notes'),'{"123":"existing"}');assert.ok(!saved.has('socwiki.history'));
});
test('successful commit saves exactly the supported local keys',()=>{
  const saved=new Map();const storage={getItem:k=>saved.get(k)??null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)};
  P.commit(storage,{comparison:[id],'damage.current':R.defaults});assert.equal(saved.size,2);assert.deepEqual(JSON.parse(saved.get('socwiki.comparison')),[id]);
});
console.log(`PASS ${checks} backup regression groups`);
