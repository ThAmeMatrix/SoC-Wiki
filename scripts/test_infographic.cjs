'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const R=require('../infographic-core.js'),root=path.resolve(__dirname,'..');
function load(file,key){const context={window:{WIKI_PAGES:{}}};vm.runInNewContext(fs.readFileSync(path.join(root,file),'utf8'),context);return JSON.parse(JSON.stringify(key?context.window[key]:Object.values(context.window.WIKI_PAGES)[0]));}
const data=load('data/index.js','WIKI_DATA'),extra=load('data/infographic.js','WIKI_INFOGRAPHIC_DATA');
const byId=new Map(data.pages.map(p=>[p.id,p]));
function resolve(title){let id=data.titles[title],seen=new Set();while(data.redirects[id]&&!seen.has(id)){seen.add(id);id=data.redirects[id];}return byId.get(id);}
function modelFor(character){
 const raw=load(`data/pages/${character.id}.js`).rawFields||{},basic=resolve('技能图鉴库/'+raw['初始普攻']);
 const names=R.treeNames(raw),ids=[...new Set(names.flatMap(t=>t.names).map(n=>resolve('技能图鉴库/'+n)?.id).filter(Boolean))];
 const skills=ids.map(id=>{const d=load(`data/pages/${id}.js`);return {...byId.get(id),kind:R.kind(d.rawFields||{},id===basic?.id)};});
 return {character,skills,initialBasic:basic?.id,initialSkillIds:R.treeNames(raw).find(t=>t.rank===0).names.map(n=>resolve('技能图鉴库/'+n)?.id).filter(Boolean)};
}
const catalog={equipment:data.pages.filter(p=>p.type==='equipment'),...extra};
assert.equal(extra.tarot.length,22);assert.equal(extra.engravings.length,10);
const types=['宝剑','权杖','星币','圣杯'],combinations=new Set(extra.engravings.map(e=>e.parts.slice().sort().join('+')));
for(let i=0;i<4;i++)for(let j=i;j<4;j++)assert(combinations.has([types[i],types[j]].sort().join('+')));
for(const [source,payload] of Object.entries(extra.assets)){assert(fs.existsSync(path.join(root,source)));assert(fs.existsSync(path.join(root,payload)));}
let checked=0;
for(const c of data.pages.filter(p=>p.type==='character'&&!p.redirect)){
 for(const [kind,names] of [['rarities',[c.rarity]],['professions',[c.class]],['factions',(c.faction||'').split(/[，,、]/)]])for(const name of names.filter(n=>n&&n!=='召唤物')){const badge=extra.badges[kind][name.trim()];assert(badge&&extra.assets[badge],c.name+' missing '+name+' image');}
 const model=modelFor(c),state=R.defaults(model),restored=R.restore(state,model,catalog);assert.deepEqual(restored,state);
 if(model.initialBasic)assert(R.pool(model,0).some(s=>s.id===model.initialBasic));
 assert(R.pool(model,1).every(s=>s.kind==='reaction'));assert(R.pool(model,2).every(s=>s.kind==='skill'));
 for(const tier of R.treeNames({}))assert([11,9,7,5,3,1,0].includes(tier.rank));checked++;
}
for(const name of ['猩红之触','白剑','以冰铸剑']){const id=data.titles['技能图鉴库/'+name];assert.equal(R.kind(load(`data/pages/${id}.js`).rawFields),'basic',name);}
assert.equal(R.kind({'技能类别':'反应','技能描述':'受到攻击后回复生命。'}),'reaction');
const model=modelFor(byId.get(9296)),state=R.defaults(model),skills=R.pool(model,2),reaction=R.pool(model,1)[0];
assert(R.setSlot(state,model,0,2,skills[0].id));assert(R.setSlot(state,model,0,3,skills[1].id));
assert(R.setSlot(state,model,0,2,skills[1].id));assert.equal(state.loadouts[0].slots[3],skills[0].id);
assert(!R.setSlot(state,model,0,0,reaction.id));assert(!R.setSlot(state,model,0,1,skills[0].id));
assert(!R.setSlot(state,model,3,2,skills[0].id));assert(!R.moveSlot(state,0,1,1));
assert(R.moveSlot(state,0,3,-1));assert.equal(state.loadouts[0].slots[2],skills[0].id);
const foreign=R.defaults(model);foreign.characterId=879;assert.deepEqual(R.restore(foreign,model,catalog),R.defaults(model));
const invalid={...state,star:99,weaponStar:-3,scores:[99,-10,'bad',2.7,null,4],marks:{'bogus':'required',[skills[0].id]:'optional'},weapons:[9337,9337,8991,'bad'],accessories:[9337,8991,8991,null],tarot:['none','tarot-1','tarot-1',null]};
const fixed=R.restore(invalid,model,catalog);assert(!('star' in fixed));assert(!('weaponStar' in fixed));assert.deepEqual(fixed.scores,[5,0,0,2.5,0,4]);assert.deepEqual(fixed.weapons,[9337,null,null,null]);assert.deepEqual(fixed.accessories,[null,8991,null,null]);assert(!fixed.marks.bogus);
console.log(`PASS infographic: ${checked} character models, initial basics, slot types and swaps, state validation, 22 tarot, all 10 engravings, ${Object.keys(extra.assets).length} image payloads`);

const legacy={...R.defaults(model),version:1,engraving:'engraving-5',marks:{[model.initialBasic]:'required',[skills[0].id]:'optional'}};
delete legacy.engravings;delete legacy.gearNotes;delete legacy.groupNotes;
const migrated=R.restore(legacy,model,catalog);assert.equal(migrated.version,6);assert.deepEqual(migrated.engravings,[{id:'engraving-5',note:''}]);assert(!migrated.marks[model.initialBasic]);assert.equal(migrated.marks[skills[0].id],'optional');
const cycle=R.defaults(model),pick=model.skills.find(s=>R.canMark(model,s.id)).id;
assert(!R.cycleMark(cycle,model,model.initialBasic));assert.deepEqual(cycle.marks,{});
for(const expected of ['required','optional',undefined]){assert(R.cycleMark(cycle,model,pick));assert.equal(cycle.marks[pick],expected);}
const multiple=R.restore({...cycle,engravings:[{id:'engraving-1',note:'爆发'},{id:'engraving-2',note:'续航'},{id:'engraving-1',note:'重复'},{id:'bad',note:'无效'}],gearNotes:{weapons:['输出'],accessories:['辅助'],tarot:['适配']},groupNotes:{weapons:'自由搭配'}},model,catalog);
assert.equal(multiple.engravings.length,2);assert.equal(multiple.engravings[1].note,'续航');assert.equal(multiple.gearNotes.weapons[0],'输出');assert.equal(multiple.groupNotes.weapons,'自由搭配');
console.log('PASS v6 state migration, initial display-only skills, three-state marking cycle, multiple engraving notes, red captions');

const older=R.restore({...R.defaults(model),version:2,subtitle:'角色养成 · 一图流'},model,catalog);
assert.equal(older.version,6);assert.equal(older.subtitle,'角色养成一图流');assert.equal(older.titleColor,'#ef9b73');assert.equal(older.treeNotes,'');
const themed=R.restore({...older,titleColor:'#79D1F2',treeNotes:'技能树下方的说明'},model,catalog);assert.equal(themed.titleColor,'#79d1f2');assert.equal(themed.treeNotes,'技能树下方的说明');
assert.equal(R.restore({...older,titleColor:'not-a-color'},model,catalog).titleColor,'#ef9b73');
for(const c of data.pages.filter(p=>p.type==='character')){assert(Array.from(c.name).every(ch=>extra.nameFont.ranges.some(([a,b])=>ch.codePointAt(0)>=a&&ch.codePointAt(0)<=b)));const raw=load(`data/pages/${c.id}.js`).rawFields||{};for(const name of (raw['极限解放']||'').split(/[，,、]/).filter(Boolean)){const skill=resolve('极限解放/'+name.trim());assert(skill&&extra.assets[skill.image],c.name+' liberation '+name);}}
console.log('PASS old draft migration, custom title color, tree footer notes, all character font coverage and liberation icons');

assert(R.branchSpan(1)<R.branchSpan(3));assert.equal(R.branchSpan(1),R.branchSpan(5));assert.equal(R.branchSpan(5),R.branchSpan(9));assert.equal(R.branchSpan(3),R.branchSpan(7));assert.equal(R.branchSpan(7),R.branchSpan(11));
const bg={portrait:'awakened',x:37,y:-52,scale:1.2},rect=R.backgroundRect(800,1600,bg),anchor={x:1300,y:600};
const zoomed=R.zoomBackground(bg,rect,1.6,anchor),nextRect=R.backgroundRect(800,1600,zoomed);
assert(Math.abs((anchor.x-rect.x)/rect.w-(anchor.x-nextRect.x)/nextRect.w)<1e-8);assert(Math.abs((anchor.y-rect.y)/rect.h-(anchor.y-nextRect.y)/nextRect.h)<1e-8);
const badBg=R.restore({...older,background:{portrait:'skin-2',scale:100,x:Infinity,y:-99999},customTitle:'https://example.com/title.png'},model,catalog);
assert.equal(badBg.background.portrait,'awakened');assert.equal(badBg.background.scale,4);assert.equal(badBg.background.x,0);assert.equal(badBg.background.y,-2160);assert.equal(badBg.customTitle,null);
for(const c of data.pages.filter(p=>p.type==='character'))for(const art of c.portraits||[])if(['base','awakened'].includes(art.key))assert(extra.assets[art.src],c.name+' '+art.key+' export payload');
assert(fs.existsSync(path.join(root,extra.signatureFont)));assert(extra.assets[extra.referenceTitles['9296']]);
assert(fs.existsSync(path.join(root,extra.signatureLatinFont)));
assert.equal(extra.nameFont.family,'Source Han Serif SC');assert(!extra.nameFont.file&&!extra.nameFont.web);
const viperaPortrait=byId.get(9296).portraits.find(p=>p.key==='awakened').src;
assert.deepEqual(extra.portraitSizes[viperaPortrait],{width:3000,height:2539});
console.log('PASS alternating branch lengths, zoom anchoring, transform validation, both portrait sets and exact reference title/signature resources');

const renamed=R.restore({...R.defaults(model),titleName:'  霁月·瑟蕾妮娅  '},model,catalog);assert.equal(renamed.titleName,'霁月·瑟蕾妮娅');assert.equal(renamed.version,6);
assert.equal(R.restore({...renamed,version:4,titleName:undefined},model,catalog).titleName,'');
assert.equal(Array.from(R.restore({...renamed,titleName:'𠮷'.repeat(30)},model,catalog).titleName).length,24);
assert(!('nameArt' in extra));assert(extra.nameFont.glyphs>40000);assert(fs.existsSync(path.join(root,extra.nameFont.script)));
for(const ch of '霁月瑟蕾妮娅龘龍鳳凰𠮷')assert(extra.nameFont.ranges.some(([a,b])=>ch.codePointAt(0)>=a&&ch.codePointAt(0)<=b));
console.log('PASS arbitrary names, Unicode-safe state migration, full offline font coverage and no per-character title lookup');

assert.equal(R.defaults(model).titleMode,'reference');
const other=modelFor(data.pages.find(p=>p.type==='character'&&p.id!==9296&&!p.redirect));assert.equal(R.defaults(other).titleMode,'text');
const legacyText=R.restore({...state,version:5,titleMode:undefined,titleName:'全新名字'},model,catalog);assert.equal(legacyText.titleMode,'text');
const legacyImage=R.restore({...state,version:5,titleMode:undefined,customTitle:'data:image/png;base64,YQ=='},model,catalog);assert.equal(legacyImage.titleMode,'image');
const toggled=R.restore({...legacyImage,titleMode:'text',titleFont:'sans',titleImageTint:true},model,catalog);assert.equal(toggled.titleMode,'text');assert.equal(toggled.customTitle,legacyImage.customTitle);assert.equal(toggled.titleFont,'sans');assert(toggled.titleImageTint);
assert.equal(R.restore({...state,titleMode:'reference',titleName:'其他名字'},model,catalog).titleMode,'text');
assert.equal(R.restore({...state,titleMode:'evil',titleFont:'url(x)',titleImageTint:'yes'},model,catalog).titleFont,'serif');
console.log('PASS reference/text/image modes, legacy migration, retained image and validated font/tint settings');

const legacyAppearance=R.restore({...state,backgroundOpacity:undefined,brightness:.4},model,catalog);assert.equal(legacyAppearance.backgroundOpacity,.4);assert.equal(legacyAppearance.panelOpacity,.92);assert.equal(legacyAppearance.markWidth,3);
const appearance=R.restore({...state,panelOpacity:0,backgroundOpacity:1,markWidth:1.5},model,catalog);assert.equal(appearance.panelOpacity,0);assert.equal(appearance.backgroundOpacity,1);assert.equal(appearance.markWidth,1.5);
const invalidAppearance=R.restore({...state,panelOpacity:9,backgroundOpacity:-3,markWidth:100},model,catalog);assert.equal(invalidAppearance.panelOpacity,1);assert.equal(invalidAppearance.backgroundOpacity,0);assert.equal(invalidAppearance.markWidth,6);
console.log('PASS appearance defaults, old brightness migration, transparent endpoints and ring width limits');

const liberationId=data.titles['极限解放/单打独斗'],withLiberation={...model,liberations:[{id:liberationId}]},libState=R.defaults(withLiberation);
for(const expected of ['required','optional',undefined]){assert(R.cycleMark(libState,withLiberation,liberationId));assert.equal(libState.marks[liberationId],expected);}
libState.marks[liberationId]='optional';assert.equal(R.restore(libState,withLiberation,catalog).marks[liberationId],'optional');assert(!R.pool(withLiberation,2).some(s=>s.id===liberationId));
for(const span of [65,89,109])for(const sign of [-1,1])for(const width of [1,3,6])for(const length of [0,40,100]){const cx=189+span*sign,e=R.branchEnds(189,cx,width,length);assert(Math.abs(e.end-cx)>=30.5+width/2+3-1e-9);assert(Math.abs(e.end-189)>=22-1e-9);}
assert(!R.validDate('2026-02-31'));assert(R.validDate('2024-02-29'));assert.equal(R.posterDate({generatedDate:'2025-01-02'}),'2025-01-02');assert.equal(R.posterDate({},new Date(2026,9,27)),'2026-10-27');
const customStyle=R.restore({...state,titleItalic:true,titleBold:true,titleOutlineWidth:4,titleOutlineColor:'#123abc',titleScale:.8,generatedDate:'2026-01-02',topText:'群：123',topTextX:900,topTextY:140,branchWidth:1,branchLength:60},model,catalog);assert.equal(customStyle.titleScale,.8);assert(customStyle.titleItalic);assert.equal(customStyle.generatedDate,'2026-01-02');assert.equal(customStyle.topTextX,900);assert.equal(customStyle.branchLength,60);
console.log('PASS liberation marking/migration, branch endpoints outside circles, valid dates and typography/publication settings');
assert.equal(R.defaults(model).datePrefix,'');
assert.equal(R.restore({...state,datePrefix:'更新于'},model,catalog).datePrefix,'更新于');
assert.equal(R.restore({...state,datePrefix:'a\nb\rc'},model,catalog).datePrefix,'a b c');
assert.equal(R.restore({...state,datePrefix:'长'.repeat(30)},model,catalog).datePrefix.length,24);
console.log('PASS optional date prefix migration, newline sanitization and length limit');
for(const key of ['weapons','accessories','tarot'])assert.equal(R.defaults(model)[key].length,1);
const customLayout=R.restore({...state,layout:{trait:{x:500,y:200,w:900,h:300},invalid:{x:1,y:1,w:2,h:2}},roleText:'持续伤害 / 控场',weapons:[]},model,catalog);
assert.deepEqual(customLayout.layout.trait,{x:500,y:200,w:900,h:300});assert(!customLayout.layout.invalid);assert.equal(customLayout.roleText,'持续伤害 / 控场');assert.equal(customLayout.weapons.length,1);
assert.deepEqual(R.layoutRect({x:9999,y:-5,w:300,h:200}),{x:1620,y:0,w:300,h:200});
assert.equal(R.snapLayout({x:104,y:70,w:100,h:50},[{x:100,y:400,w:600,h:200}]).rect.x,100);
assert.equal(R.snapLayout({x:104,y:70,w:100,h:50},[],false,false).rect.x,104);
assert.equal(R.snapLayout({x:100,y:70,w:596,h:50},[{x:700,y:400,w:100,h:200}],true).rect.w,600);
assert.equal(R.restore({...state,weapons:Array(100).fill(null)},model,catalog).weapons.length,12);
console.log('PASS layout bounds, movement/resize snapping, optional snapping, custom roles and variable recommendation counts');

assert.equal(R.statRatio(50,100),50);assert.equal(R.statRatio(0,100),0);assert.equal(R.statRatio("",100),null);assert.equal(R.statRatio("未收录",100),null);assert.equal(R.statRatio(10,0),null);assert.equal(R.statRatio(200,100),100);
console.log("PASS stat percentages, missing data, zero and upper bound");

assert.equal(R.baseStatDefinitions.filter(([key])=>key.startsWith("jump")).length,1);assert(R.baseStatDefinitions.some(([key,label])=>key==="jump"&&label==="跳跃"));

// Real saved builds must survive growth past the former three-row limit and deletion.
const flexible=R.defaults(model);assert.equal(flexible.loadouts.length,1);assert(!R.removeLoadout(flexible,0));
for(let i=0;i<4;i++)R.addLoadout(flexible,model);
assert.equal(flexible.loadouts.length,5);assert(R.setSlot(flexible,model,4,2,skills[0].id));assert(R.setSlot(flexible,model,4,3,skills[1].id));assert(R.moveSlot(flexible,4,3,-1));
flexible.loadouts[4].name='持续输出';const tail=JSON.parse(JSON.stringify(flexible.loadouts[4]));assert(R.removeLoadout(flexible,2));assert.deepEqual(flexible.loadouts[3],tail);
assert(!R.setSlot(flexible,model,4,2,skills[0].id));assert(!R.removeLoadout(flexible,-1));
flexible.loadoutCommentary=R.commentary({enabled:true,text:'先控场，再爆发。',font:'serif',size:24,bold:true,italic:true,align:'center',lineHeight:1.8,outlineWidth:1,color:'#d5e8ff'});
flexible.layout.loadoutNotes={x:400,y:700,w:600,h:150};assert.deepEqual(R.restore(flexible,model,catalog),flexible);
const legacyThree={...flexible,loadouts:flexible.loadouts.slice(0,3)};delete legacyThree.loadoutCommentary;assert.deepEqual(R.restore(legacyThree,model,catalog).loadouts,legacyThree.loadouts);assert.equal(R.restore(legacyThree,model,catalog).loadoutCommentary.enabled,false);
assert.equal(R.restore({...flexible,loadouts:[]},model,catalog).loadouts.length,1);
const badNote=R.commentary({size:99,lineHeight:9,outlineWidth:99,color:'bad',align:'bogus',font:'bogus'});assert.equal(badNote.size,48);assert.equal(badNote.lineHeight,2.4);assert.equal(badNote.outlineWidth,3);assert.equal(badNote.color,'#e9efed');assert.equal(badNote.font,'sans');
console.log('PASS variable loadouts beyond three, deletion preserves other builds, minimum one, legacy drafts and independent commentary settings');

// Canvas migrations and coordinates must preserve real pixels outside the old 1080px height.
assert.deepEqual(R.canvasSize(),{width:1920,height:1080});
assert.deepEqual(R.canvasSize({width:1400.4,height:2100.1}),{width:1400,height:2100});
assert.deepEqual(R.canvasSize({width:99999,height:-9}),{width:4096,height:320});
const tall=R.restore({...state,canvas:{width:1280,height:2400},layout:{stats:{x:900,y:2000,w:300,h:240}},composition:'spotlight',decoration:{style:'plain',intensity:.4},topTextY:1900},model,catalog);
assert.deepEqual(tall.layout.stats,{x:900,y:2000,w:300,h:240});assert.equal(tall.topTextY,1900);assert.equal(tall.composition,'spotlight');assert.equal(tall.decoration.style,'plain');
assert.deepEqual(R.restore(tall,model,catalog),tall);
assert.equal(R.snapLayout({x:902,y:2005,w:300,h:240},[{x:900,y:2000,w:100,h:100}],false,true,null,tall.canvas).rect.y,2000);
assert.equal(R.layoutRect({x:1100,y:2399,w:300,h:240},tall.canvas).y,2160);
const hero={x:650,y:15,w:600,h:570,focusScale:3,focusY:228},position={portrait:'awakened',x:12,y:38,scale:1.1},artRect=R.backgroundRect(3000,2539,position,tall.canvas,hero),point={x:850,y:340};
const zoom=R.zoomBackground(position,artRect,1.3,point,tall.canvas),zoomRect=R.backgroundRect(3000,2539,zoom,tall.canvas,hero);
assert(Math.abs((point.x-artRect.x)/artRect.w-(point.x-zoomRect.x)/zoomRect.w)<1e-8);
assert(Math.abs((point.y-artRect.y)/artRect.h-(point.y-zoomRect.y)/zoomRect.h)<1e-8);
console.log('PASS custom canvas validation/migration, tall-frame coordinates and snapping, gold/plain styles, artwork focus and stable zoom anchors');

// Old drafts keep the established signature. New typography and artwork travel with a plan.
const oldAuthor={...state,author:'ThAme'};delete oldAuthor.authorFont;delete oldAuthor.authorMode;
assert.equal(R.restore(oldAuthor,model,catalog).authorFont,'signature');assert.equal(R.restore(oldAuthor,model,catalog).authorMode,'text');
const authorPlan=R.restore({...state,author:'ThAme',authorFont:'custom',authorCustomFont:{name:'sample.woff2',data:'data:font/woff2;base64,AA=='},authorMode:'image',authorImage:'data:image/png;base64,AA==',composition:'information'},model,catalog);
assert.equal(authorPlan.authorFont,'custom');assert.equal(authorPlan.composition,'information');assert.deepEqual(R.restore(authorPlan,model,catalog),authorPlan);
const badAuthor=R.restore({...authorPlan,authorImage:'https://example.com/name.png',authorCustomFont:{name:'external',data:'url(https://example.com/font.woff2)'}},model,catalog);
assert.equal(badAuthor.authorImage,null);assert.equal(badAuthor.authorCustomFont,null);assert.equal(badAuthor.authorFont,'signature');
assert.equal(R.restore({...state,authorFont:'unsupported',composition:'unknown'},model,catalog).authorFont,'signature');
console.log('PASS legacy author defaults, font/image plan roundtrip, information layout persistence and external asset rejection');
