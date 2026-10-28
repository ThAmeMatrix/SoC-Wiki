/* Boundary and arithmetic regressions for the two offline tools. Run with Node. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const R=require('../tools-core.js');
const scope={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../data/tools.js'),'utf8'),scope);
const D=JSON.parse(JSON.stringify(scope.window.WIKI_TOOLS_DATA));
let checks=0;
function test(name,fn){fn();checks++;console.log('PASS '+name);}
test('example damage and unrounded critical multiplication',()=>{
  const r=R.calculateDamage({});assert.equal(r.damage,2700);assert.equal(r.criticalDamage,3510);
  assert.equal(R.calculateDamage({atkPanel:'1',defBase:'0',skillMult:'150',critDmgPct:'130'}).criticalDamage,2);
});
test('additive and multiplicative regions, class advantage, defense floor and vulnerability cap',()=>{
  const r=R.calculateDamage({atkClass:'crusher',defClass:'defender',atkPanel:'3000',atkBonusPct:'20，30',atkBonusFlat:'100',
    skillMult:'150',critDmgPct:'130,30',defBase:'2000',defDebuff:'20',hornBuff:true,defReduceFlat:'100',
    ignoreDefPct:'50,50',dmgZone:'20,-10',finalDmgZone:'20,30',vulnZone:'20,50',finalVulnZone:'10'});
  assert.equal(r.attack,4600);assert.equal(r.defense,275);assert.equal(r.vulnerability,3);
  assert.equal(r.damage,48459);assert.equal(r.criticalDamage,77535);
  assert.equal(R.calculateDamage({defReduceFlat:'9000'}).defense,0);
  assert.equal(R.calculateDamage({defBase:'9000'}).damage,0);
  assert.equal(R.calculateDamage({dmgZone:'-90'}).damage,1350);
  assert.equal(R.calculateDamage({finalDmgZone:'-100'}).damage,0);
});
test('all five class relationships and neutral pairs',()=>{
  for(const [a,b,n] of [['crusher','defender',1.3],['defender','raider',1.3],['raider','crusher',1.3],['watcher','destroyer',1.4],
    ['defender','crusher',.7],['raider','defender',.7],['crusher','raider',.7],['destroyer','watcher',.6],['watcher','crusher',1]])
    assert.equal(R.calculateDamage({atkClass:a,defClass:b}).restraint,n);
});
test('invalid values never yield a believable partial result',()=>{
  for(const value of ['NaN','Infinity','12abc','1,,2','20;30','<script>','1e999'])assert.throws(()=>R.calculateDamage({atkBonusPct:value}));
  assert.throws(()=>R.calculateDamage({ignoreDefPct:'101'}));assert.throws(()=>R.calculateDamage({ignoreDefPct:'-1'}));
  assert.throws(()=>R.calculateDamage({atkPanel:'1,2'}));assert.throws(()=>R.calculateDamage({finalDmgZone:'-101'}));
  assert.throws(()=>R.calculateDamage({defBase:'-1'}));assert.equal(R.calculateDamage({atkBonusPct:'20%'}).damage,3600);
});
test('snapshot pool data resolves all UP characters to offline assets',()=>{
  assert.equal(D.pools.length,2);
  for(const p of D.pools){assert.ok(fs.existsSync(path.join(__dirname,'..',p.image)));for(const name of p.up)assert.ok(D.characters.legend.some(c=>c.name===name));}
  for(const c of Object.values(D.characters).flat())if(c.image)assert.ok(fs.existsSync(path.join(__dirname,'..',c.image)),c.name);
});
test('rarity thresholds on both sides of every boundary',()=>{
  for(const [roll,rarity] of [[0,'legend'],[.019999,'legend'],[.02,'epic'],[.219999,'epic'],[.22,'elite'],[.619999,'elite'],[.62,'common'],[.99999,'common']]) {
    const r=R.draw(R.newSimulation(D),'chuyu',1,D,()=>roll);assert.equal(r.results[0].rarity,rarity);
  }
});
test('100th legendary guarantee and 180th UP guarantee reset shared pity',()=>{
  const fresh=R.newSimulation(D);let s=R.draw(fresh,'chuyu',100,D,()=>.99).state;
  assert.equal(fresh.total,0);assert.equal(s.total,100);assert.equal(s.counts.legend,1);assert.equal(s.pity,0);assert.equal(s.special.chuyu,100);
  for(let i=0;i<8;i++)s=R.draw(s,'chuyu',10,D,()=>.99).state;
  assert.equal(s.total,180);assert.equal(s.counts.legend,2);assert.equal(s.pity,0);assert.equal(s.special.chuyu,0);
  assert.equal(s.history[0].guarantee,'up');assert.equal(s.history[0].name,D.pools[0].up[0]);
});
test('switching pools shares legendary pity and keeps separate UP counters',()=>{
  let s=R.newSimulation(D);for(let i=0;i<9;i++)s=R.draw(s,'chuyu',10,D,()=>.99).state;
  for(let i=0;i<9;i++)s=R.draw(s,'chuyu',1,D,()=>.99).state;
  s=R.draw(s,'chongfeng',1,D,()=>.99).state;
  assert.equal(s.counts.legend,1);assert.equal(s.pity,0);assert.equal(s.special.chuyu,99);assert.equal(s.special.chongfeng,1);
});
test('UP guarantee prefers unowned partner and wins simultaneous guarantees',()=>{
  const s=R.newSimulation(D);s.total=179;s.counts.common=179;s.pity=99;s.special.chongfeng=179;s.owned=[D.pools[1].up[0]];
  const r=R.draw(s,'chongfeng',1,D,()=>0);
  assert.equal(r.results[0].name,D.pools[1].up[1]);assert.equal(r.results[0].guarantee,'up');assert.equal(r.state.pity,0);
});
test('random UP resets only the active pool, non-UP excludes banner UPs',()=>{
  const s=R.newSimulation(D);s.total=20;s.counts.common=20;s.pity=20;s.special.chuyu=8;s.special.chongfeng=12;
  const r=R.draw(s,'chongfeng',1,D,()=>0);assert.equal(r.state.special.chuyu,8);assert.equal(r.state.special.chongfeng,0);
  const sequence=[0,.99,.99];const non=R.draw(R.newSimulation(D),'chuyu',1,D,()=>sequence.shift());
  assert.ok(!D.pools.flatMap(p=>p.up).includes(non.results[0].name));
});
test('history is bounded, full statistics survive refresh and malformed storage is rejected',()=>{
  let s=R.newSimulation(D);for(let i=0;i<10;i++)s=R.draw(s,'chuyu',100,D,()=>.99).state;
  assert.equal(s.total,1000);assert.equal(s.history.length,200);assert.deepEqual(R.restoreSimulation(JSON.parse(JSON.stringify(s)),D),s);
  assert.equal(R.restoreSimulation({...s,pity:10000},D).total,0);
  assert.equal(R.restoreSimulation({...s,counts:{legend:-1}},D).total,0);
  assert.throws(()=>R.draw(s,'missing',1,D));assert.throws(()=>R.draw(s,'chuyu',999,D));
});
console.log(`PASS ${checks} groups of offline tool regressions`);
