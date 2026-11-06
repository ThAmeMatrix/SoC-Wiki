const fs = require('fs');
const path = require('path');
const vm = require('vm');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'data', 'panel-data.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'data', 'combat-data.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'data', 'world-data.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'panel-calc.js'), 'utf8'), sandbox);
const P = sandbox.window.WIKI_PANEL_DATA, C = sandbox.window.WikiPanelCalc;
const B = sandbox.window.WIKI_COMBAT_DATA;
let failed = 0;
function check(name, ok, detail) {
  if (!ok) failed++;
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ' :: ' + detail : ''));
}

check('data loaded', !!P && P.characters.length > 100, P && P.characters.length + ' characters');
check('calc loaded', !!C && typeof C.calculate === 'function');

const cfg = C.defaults(P);
const r = C.calculate(cfg, P);
check('five totals', r.total.length === 5 && r.total.every(Number.isFinite), JSON.stringify(r.total));
check('result has steps', r.extras.length >= 3, r.extras.map(e => e.key).join(','));
check('speed present', Number.isFinite(r.speed), String(r.speed));

// Cross-check the character base against the Python client formula (floor in two stages).
function pythonBase(character, config) {
  const level = Math.min(P.maxLevel, config.level);
  const growth = P.unitGrowth[character.modify][level - 1];
  const adj = P.rarities[character.rarity][1];
  const star = P.stars[config.star];
  const friend = C.friendshipPermillage(P, config.friendship);
  const line = C.skillLinePermillage(P, character, config);
  const adds = C.rankAdditions(P, character, config.rank);
  return growth.map((g, i) => {
    const p = star[i] + line[i] + friend;
    const adjusted = Math.floor(g * adj * (1000 + p) / 1000);
    return Math.floor((adjusted + 100 * adds[i]) / 100);
  });
}
const ch = C.findCharacter(P, cfg.character);
const py = pythonBase(ch, cfg);
check('character base == client two-stage floor', py.every((v, i) => v === r.base[i]),
  py.join('/') + ' vs ' + r.base.join('/'));

// Monotonicity: higher level / star / rank must not lower any stat.
const up = (patch) => C.calculate(Object.assign({}, cfg, patch), P).total;
const low = up({ level: 1, star: 1, rank: 0, friendship: 0 });
check('level/star/rank monotonic', r.total.every((v, i) => v >= low[i]),
  low.join('/') + ' -> ' + r.total.join('/'));

// Equipment: empty slots remove their contribution.
const bare = C.calculate(Object.assign({}, cfg, {
  weapon: { ...cfg.weapon, id: 0 }, offhand: { ...cfg.offhand, id: 0 },
  charm: { ...cfg.charm, id: 0, entryCount: 0, entries: [] },
}), P);
check('equipment contributes', r.total.some((v, i) => v > bare.total[i]),
  bare.total.join('/') + ' -> ' + r.total.join('/'));

// Permillage affix raises the panel by roughly the expected percentage.
const enchanted = JSON.parse(JSON.stringify(cfg));
enchanted.weapon.enchant.percents = [0, 100, 0, 0, 0];
const boosted = C.calculate(enchanted, P);
check('enchant permillage applied', boosted.total[1] > r.total[1],
  r.total[1] + ' -> ' + boosted.total[1]);
check('enchant permillage recorded', boosted.permillage[1] - r.permillage[1] === 100,
  String(boosted.permillage[1] - r.permillage[1]));

// Every character in the calculator must produce finite values.
let bad = 0;
for (const c of P.characters) {
  const out = C.calculate(Object.assign({}, cfg, { character: c.key }), P);
  if (!out.total.every(Number.isFinite)) bad++;
}
check('all characters finite', bad === 0, bad + ' bad');

// Enchant caps match the source table.
const caps = C.enchantCaps(P, P.elements[0].id);
check('enchant caps present', caps.flat[0] > 0 && caps.percent[0] > 0,
  JSON.stringify(caps.flat) + ' / ' + JSON.stringify(caps.percent));

// Per-rank skill-line branches: none / both must move the stats.
const ranks = P.lineRanks?.[ch.line] || [];
const withPick = value => {
  const linePicks = {};
  for (const rank of ranks) linePicks[rank] = value;
  return C.calculate(Object.assign({}, cfg, { linePicks }), P);
};
const none = withPick('none'), both = withPick('both');
check('skill-line ranks exported', ranks.length > 0, JSON.stringify(ranks));
check('per-rank skill-line picks change stats', none.total.some((v, i) => v < both.total[i]),
  none.total.join('/') + ' -> ' + both.total.join('/'));
check('per-rank left/right differ from both', withPick('left').total[0] <= both.total[0]);

// Both account-wide talent trees feed the final panel.
check('talent data exported', !!P.talents?.star && !!P.talents?.pioneer,
  P.talents && [P.talents.star.maxLevel, P.talents.pioneer.maxLevel].join('/'));
const talented = C.calculate(Object.assign({}, cfg, {
  talent: { star: P.talents.star.maxLevel, pioneer: P.talents.pioneer.maxLevel },
}), P);
// Both trees are fully lit by default now, so a higher legacy tier cannot add
// more; verify the node-based total is present and finite instead.
check('talent bonuses present in the panel',
  r.talent.nodeBased && r.talent.flat.some(Boolean) &&
  talented.total.every(Number.isFinite),
  r.talent.flat.join('/'));
check('talent step recorded', talented.extras.some(e => e.key === 'talent'));
const adjusted = C.calculate(Object.assign({}, cfg, { talentAdjust: [100, 0, 0, 0, 0] }), P);
check('talent manual adjust applied', adjusted.total[0] > r.total[0],
  r.total[0] + ' -> ' + adjusted.total[0]);

// Real talent trees (star/pioneer) are keyed by the character's profession
// category and expose the client's grade / unlock-group / prerequisite data.
check('talent trees exported', !!P.talents?.star?.trees && !!P.talents?.pioneer?.trees);
const anyChar = P.characters[0];
const starTree = C.talentTree(P, 'star', anyChar);
const pioneerTree = C.talentTree(P, 'pioneer', anyChar);
check('star tree has grades and nodes', !!starTree && starTree.grades.length === 7 && starTree.nodes.length > 40,
  starTree && `${starTree.grades.length} grades / ${starTree.nodes.length} nodes`);
check('pioneer tree has unlock groups', !!pioneerTree && pioneerTree.groups.length >= 20 && pioneerTree.nodes.length > 100,
  pioneerTree && `${pioneerTree.groups.length} groups / ${pioneerTree.nodes.length} nodes`);
check('star grades have real exp thresholds', starTree.grades.some(g => g.exp > 1000),
  starTree.grades.map(g => g.exp).join('/'));
check('talent nodes carry prerequisites, costs and levels',
  starTree.nodes.some(n => n.prev.length && n.levels.some(l => l.cost.length && l.reqLevel > 1)));
const attrNode = starTree.nodes.find(n => n.attr && n.levels.some(l => l.flat.some(Boolean)));
check('attribute nodes have five-stat vectors', !!attrNode && attrNode.levels[0].flat.length === 5);
const nodeCfg = { ...cfg, talentNodes: { star: { [attrNode.id]: attrNode.levels.length }, pioneer: {} } };
const nodeBonus = C.talentBonuses(P, anyChar, nodeCfg);
check('node investment is summed per level', nodeBonus.nodeBased && nodeBonus.lit === 1
  && nodeBonus.flat.some(Boolean), JSON.stringify(nodeBonus.flat));
const progress = C.talentProgress(P, anyChar, nodeCfg);
check('progress reports exp and player level', progress.exp > 0 && progress.reqLevel >= 1
  && Object.keys(progress.cost).length > 0, JSON.stringify({exp: progress.exp, req: progress.reqLevel}));
const grade = C.talentGrade(P, anyChar, 'star', progress.exp);
check('grade follows cumulative exp', !!grade && typeof grade.name === 'string', grade && grade.name);
const nodeResult = C.calculate(nodeCfg, P);
check('node investment reaches the panel total', nodeResult.talent.nodeBased
  && nodeResult.talent.flat.some(Boolean));
const zeroCfg = { ...cfg, talentNodes: { star: {}, pioneer: {} } };
check('empty node selection falls back to legacy tier', C.talentBonuses(P, anyChar, zeroCfg).nodeBased === false);

// Round 6: one-click fill, per-level material names, bonus summary.
const fillCfg = { ...cfg, talentNodes: { star: {}, pioneer: {} } };
const changed = C.talentFillAll(P, anyChar, fillCfg, 'star', starTree.grades[0].id);
check('fill-all lights a whole grade', changed > 0 && Object.keys(fillCfg.talentNodes.star).length === changed,
  String(changed));
const again = C.talentFillAll(P, anyChar, fillCfg, 'star', starTree.grades[0].id);
check('fill-all is idempotent', again === 0, String(again));
const filled = C.talentProgress(P, anyChar, fillCfg);
check('progress sums flat and permillage', filled.flat.some(Boolean) || filled.permillage.some(Boolean),
  JSON.stringify({flat: filled.flat, perm: filled.permillage}));
check('progress aggregates material labels', Object.keys(filled.cost).length > 0,
  JSON.stringify(filled.cost));
const costExample = starTree.nodes.find(n => n.levels.some(l => l.cost.length));
const label = C.talentCostLabel(P, 'star', costExample.levels[0].cost);
check('material names are human readable', /星之微粒|乐土币|星屑|誓言/.test(label), label);
const allCfg = { ...cfg, talentNodes: { star: {}, pioneer: {} } };
const allChanged = C.talentFillAll(P, anyChar, allCfg, 'star', null);
check('fill-all can light the whole tree', allChanged >= changed, String(allChanged));


// Round 7: online_tech_node_level rows are CUMULATIVE values at that level,
// not per-level increments. Investing N levels must yield exactly row N.
const c2 = P.characters.find(c => c.professionCategory === 2) || P.characters[0];
const st = C.talentTree(P, 'star', c2);
for (const [nid, want] of [[203, [0, 10, 10, 0, 0]], [207, [0, 50, 50, 0, 0]], [210, [50, 0, 0, 0, 0]]]) {
  const node = st.nodes.find(n => n.id === nid);
  if (!node) continue;
  const top = node.levels.length;
  const one = { ...cfg, talentNodes: { star: { [nid]: top }, pioneer: {} } };
  const b = C.talentBonuses(P, c2, one);
  const pr = C.talentProgress(P, c2, one);
  check(`node ${nid} Lv.${top} yields the cumulative row`, JSON.stringify(b.flat) === JSON.stringify(want),
    JSON.stringify(b.flat));
  check(`node ${nid} progress agrees`, JSON.stringify(pr.flat) === JSON.stringify(want), JSON.stringify(pr.flat));
  check(`node ${nid} not over-counted`, b.flat[1] <= 50 && b.flat[0] <= 50);
  const expSum = node.levels.reduce((a, l) => a + (l.exp || 0), 0);
  check(`node ${nid} experience still sums per level`, pr.exp === expSum, `${pr.exp} vs ${expSum}`);
}
check('legacy tier table uses cumulative rows',
  P.talents.star.byCategory['2'][1].flat[1] < 100,
  JSON.stringify(P.talents.star.byCategory['2'][1]));


// Round 8: upgrade_type 51 nodes are all-profession and must be counted once
// for every character, even when they physically live in another tree.
const watchChar = P.characters.find(c => c.professionCategory === 5) || P.characters[0];
const allLit = { ...cfg, character: watchChar.key, talentNodes: C.defaultTalentNodes(P, watchChar) };
const bd = C.talentBreakdown(P, watchChar, allLit);
check('watcher star HP = 810 (in-game value)', bd.star.flat[0] === 810, String(bd.star.flat[0]));
check('watcher star HP permillage = 300 (30%)', bd.star.perm[0] === 300, String(bd.star.perm[0]));
check('global nodes counted once', C.globalTalentNodes(P, 'star').nodes.length === 10,
  String(C.globalTalentNodes(P, 'star').nodes.length));
check('breakdown total = star + pioneer',
  bd.total.flat.every((v, i) => v === bd.star.flat[i] + bd.pioneer.flat[i]));
check('defaults light both trees',
  Object.keys(C.defaults(P).talentNodes.star).length > 70 &&
  Object.keys(C.defaults(P).talentNodes.pioneer).length > 250);
const flattened = C.calculate(allLit, P);
check('global bonus reaches the final panel', flattened.talent.flat[0] > 1800,
  String(flattened.talent.flat[0]));
// Manual flat adjustment must join the fixed-value bucket.
const flatAdjusted = C.calculate({ ...allLit, talentAdjustFlat: [120, 0, 0, 0, 0] }, P);
check('talentAdjustFlat adds to the panel', flatAdjusted.total[0] > flattened.total[0],
  `${flattened.total[0]} -> ${flatAdjusted.total[0]}`);


// Round 9: global (upgrade_type 51) nodes must be counted exactly once,
// including the two that physically live in the character's own tree.
const w2 = P.characters.find(c => c.professionCategory === 5) || P.characters[0];
const fullCfg = { ...cfg, character: w2.key, talentNodes: C.defaultTalentNodes(P, w2) };
const wbd = C.talentBreakdown(P, w2, fullCfg);
check('watcher star HP = 810 after global fix', wbd.star.flat[0] === 810, String(wbd.star.flat[0]));
check('watcher star HP percent = 30%', wbd.star.perm[0] === 300, String(wbd.star.perm[0]));
check('own global magic-defence not doubled', wbd.star.flat[4] === 130, String(wbd.star.flat[4]));
check('own global magic-defence percent not doubled', wbd.star.perm[4] === 300, String(wbd.star.perm[4]));
const wCalc = C.calculate(fullCfg, P);
check('formula breakdown exported', !!wCalc.formula && wCalc.formula.terms.length === 6);
check('formula terms sum to the flat total',
  wCalc.formula.terms.reduce((a, x) => a + x.values[0], 0) === wCalc.flat[0],
  `${wCalc.formula.terms.map(x => x.values[0]).join('+')} vs ${wCalc.flat[0]}`);
check('formula perm parts sum to the global permillage',
  wCalc.formula.permParts.reduce((a, x) => a + x.values[0], 0) === wCalc.permillage[0]);
// Unequipped slots contribute nothing.
const emptyGear = { ...fullCfg, weapon: { ...fullCfg.weapon, id: 0 },
                    offhand: { ...fullCfg.offhand, id: 0 }, charm: { ...fullCfg.charm, id: 0 } };
const noGear = C.calculate(emptyGear, P);
check('unequipped gear yields zero equipment bonus',
  noGear.weapon.every(v => v === 0) && noGear.offhand.every(v => v === 0)
  && noGear.tarot.every(v => v === 0));
check('unequipped gear lowers the panel', noGear.total[0] < wCalc.total[0],
  `${wCalc.total[0]} -> ${noGear.total[0]}`);


// Round 10: percent affixes multiply ONLY the whiteboard value. Evidence:
// BWIKI 《塔罗图鉴库》#2729 / 《附魔图鉴库》#2736 - 「所有词条的百分比数值
// 均为角色白板属性相对的百分比数值，即角色卸下所有装备后再减去天赋所增加
// 的属性后的属性值」.
const wbCfg = { ...cfg };
const wb = C.calculate(wbCfg, P);
check('calculate exposes whiteboard', Array.isArray(wb.whiteboard) && wb.whiteboard.length === 5);
check('whiteboard equals character base',
  JSON.stringify(wb.whiteboard) === JSON.stringify(wb.base));
check('addends are the non-base flat total',
  wb.addends.every((v, i) => v === wb.flat[i] - wb.base[i]));
check('final value = scaled whiteboard + addends',
  wb.total.every((v, i) => v === Math.floor(wb.base[i] * (1000 + wb.permillage[i]) / 1000) + wb.addends[i]),
  JSON.stringify(wb.total));
// Old (wrong) behaviour multiplied the whole flat total; prove the difference.
const oldTotal = wb.flat.map((v, i) => Math.floor(v * (1000 + wb.permillage[i]) / 1000));
check('whiteboard formula differs from whole-total formula',
  oldTotal.some((v, i) => v !== wb.total[i]), `${oldTotal[0]} vs ${wb.total[0]}`);
// Equipment base values are raw growth rows with no percent affixes.
const eqBase = C.equipmentBase(P, 'weapon', wbCfg.weapon);
check('equipmentBase returns five stats', !!eqBase && eqBase.values.length === 5);
const eqOff = C.equipmentBase(P, 'offhand', { ...wbCfg.offhand, id: 0 });
check('unequipped slot has no base value', eqOff === null);
// Combat formula documentation must cite the archived whiteboard definition.
check('panel formula cites whiteboard source',
  /白板/.test(B.formulas.find(f => f.id === 'panel')?.source || '') &&
  /塔罗图鉴库/.test(B.formulas.find(f => f.id === 'panel')?.source || ''));


// Round 12: battle power from client constants (const_param#132,
// battle_power_coefficient, unit_rarity.battle_power_adjust).
const W3 = sandbox.window.WIKI_WORLD_DATA || {};
const bpCfg = C.defaults(P);
const bpR = C.calculate(bpCfg, P);
const bp = C.battlePower(bpR, W3, P);
check('battle power weights from const_param#132',
  bp.hpWeight === 120 && bp.otherWeight === 200 && bp.constId === 132,
  `${bp.hpWeight}|${bp.otherWeight}`);
check('battle power is a positive integer in client magnitude',
  Number.isFinite(bp.total) && bp.total > 1500 && bp.total < 6000, String(bp.total));
check('battle power base = sum of stat/divisor',
  Math.abs(bp.base - bp.parts.reduce((a, b) => a + b, 0)) < 1e-9);
check('battle power applies rarity and profession percent',
  bp.total === Math.floor(bp.base * bp.rarity / 100 * bp.profession / 100),
  `${bp.base} × ${bp.rarity}% × ${bp.profession}% = ${bp.total}`);
const lower = C.calculate({ ...bpCfg, level: 1 }, P);
check('battle power follows panel changes',
  C.battlePower(lower, W3, P).total < bp.total,
  `${bp.total} -> ${C.battlePower(lower, W3, P).total}`);
check('client constants carried in world data',
  W3.battlePower?.coefficients?.length === 6 && Object.keys(W3.battlePower?.rarity || {}).length === 4);

// Round 14: the assembly formula is NOT recoverable from config data; the
// calculator must offer candidates, evidence and a calibration path instead
// of asserting a single unverified number.
const r14 = C.calculate(C.defaults(P), P);
const ev = W3.battlePower?.evidence || [];
check('battle power evidence states formula is compiled',
  ev.some(x => /IL2CPP|编译/.test(x)), String(ev.length));
check('battle power offers four candidates',
  (W3.battlePower?.candidates || []).length === 4);
const methodResults = (W3.battlePower?.candidates || []).map(c =>
  C.battlePower(r14, W3, P, {method: c.id}).total);
check('each candidate yields a distinct value',
  new Set(methodResults).size === 4, JSON.stringify(methodResults));
check('candidate selection is honoured',
  C.battlePower(r14, W3, P, {method: 'divisor-final'}).total <
  C.battlePower(r14, W3, P, {method: 'permille-final'}).total);
const calib = C.battlePower(r14, W3, P, {calibration: 3000});
check('calibration derives an implied multiplier',
  calib.impliedScale > 0 && calib.confidence === 'unverified',
  String(calib.impliedScale));
check('scaling applies to the result',
  C.battlePower(r14, W3, P, {scale: 2}).total ===
  2 * C.battlePower(r14, W3, P).total ||
  C.battlePower(r14, W3, P, {scale: 2}).total ===
  2 * C.battlePower(r14, W3, P).total + 1);
check('AI pathfinding data exported',
  (W3.aiMeta?.pathfinding?.moveTypes || []).length === 5 &&
  (W3.aiMeta?.pathfinding?.targetMethods || []).length === 18);

// Skill-axis images and names from the character archive.
check('lineSkills exported', Object.keys(P.lineSkills || {}).length > 140);
const slots = Object.values(P.lineSkills).flatMap(ranks => Object.values(ranks).flat()).filter(Boolean);
check('lineSkills carry images', slots.filter(s => s.image).length > 1600,
  String(slots.filter(s => s.image).length));

// Weapon-type filtering inputs used by the UI.
const mainType = (ch.weaponTypes || []).find(t => Number(t) !== 2);
check('character weapon types exported', mainType !== undefined, JSON.stringify(ch.weaponTypes));
check('weapon filter has matches', P.weapons.some(w => Number(w.typeId) === mainType));
check('common offhand type retained', P.weapons.some(w => Number(w.typeId) === 2));

// Combat constants, restraint matrix and the damage preview driven by them.
check('combat data loaded', !!B && Object.keys(B.constants || {}).length >= 8,
  B && Object.keys(B.constants || {}).join(','));
check('crit constants from const_param', B.constants.CritBaseChance.value === 10 && B.constants.CritBaseDamage.value === 30,
  JSON.stringify([B.constants.CritBaseChance, B.constants.CritBaseDamage]));
check('restraint matrix comes from speciality.param2',
  (B.restraints || []).length >= 8 && B.restraints.every(x => x.specialityId && x.source.includes('speciality#')),
  (B.restraints || []).map(x => `${x.fromName}->${x.toName}:${x.percent}`).join(' '));
const watcher = B.restraints.find(x => x.fromName === '守望者' && x.toName === '毁灭者');
const destroyer = B.restraints.find(x => x.fromName === '毁灭者' && x.toName === '守望者');
check('守望者→毁灭者 is 1.4', watcher && watcher.factor === 1.4 && watcher.percent === 140,
  JSON.stringify(watcher));
check('毁灭者→守望者 is 0.6', destroyer && destroyer.factor === 0.6 && destroyer.percent === 60,
  JSON.stringify(destroyer));
check('evaluate is a UI-only display value',
  watcher && watcher.evaluate === 130 && watcher.percent === 140,
  watcher && `${watcher.evaluate} vs ${watcher.percent}`);
check('both formulas expose structured variables',
  (B.formulas || []).length === 2 && B.formulas.every(f => (f.variables || []).length >= 5),
  (B.formulas || []).map(f => f.variables?.length).join('/'));
check('both formulas documented with sources',
  (B.formulas || []).length === 2 && B.formulas.every(f => f.expr && f.source && f.tables.length),
  (B.formulas || []).map(f => f.title).join(','));
check('formula sources reference real tables',
  (B.references || []).length >= 10 && B.references.some(x => x.table === 'const_param'));

const dc = C.damageDefaults(B);
const dmg = C.damage(r, B, dc);
check('damage preview finite', Number.isFinite(dmg.damage) && dmg.damage >= 0, String(dmg.damage));
check('damage preview sources recorded', !!dmg.sources.restraint && !!dmg.sources.critical);
const restraintHit = B.restraints.find(x => x.percent === 130);
const restrained = C.damage(r, B, { ...dc,
  attackCategory: restraintHit.from, defenseCategory: restraintHit.to });
const unrestrained = C.damage(r, B, { ...dc,
  attackCategory: restraintHit.from, defenseCategory: restraintHit.from });
check('client restraint raises damage', restrained.restraint === 1.3 && restrained.damage >= unrestrained.damage,
  `${unrestrained.damage} -> ${restrained.damage}`);
const watcherDamage = C.damage(r, B, { ...dc, attackCategory: 5, defenseCategory: 3 });
check('watcher bonus uses 1.4 in the preview', watcherDamage.restraint === 1.4,
  String(watcherDamage.restraint));
const destroyerDamage = C.damage(r, B, { ...dc, attackCategory: 3, defenseCategory: 5 });
check('destroyer penalty uses 0.6 in the preview', destroyerDamage.restraint === 0.6,
  String(destroyerDamage.restraint));
check('crit damage uses const_param +30%', dmg.criticalDamage === Math.round(dmg.damage * 1.3),
  `${dmg.damage} -> ${dmg.criticalDamage}`);
const capped = C.damage(r, B, { ...dc, vulnerability: 5000 });
check('damage cap from FixBedamageLimit', capped.vulnerability <= B.constants.FixBedamageLimit.value / 100 + 1e-9,
  String(capped.vulnerability));
check('high ground modifier from archived formula',
  C.damage(r, B, { ...dc, highGround: 'up' }).height === 1.15);

// Invalid input is reported instead of throwing NaN.
try { C.calculate(Object.assign({}, cfg, { character: '__missing__' }), P); check('unknown character rejected', false); }
catch (e) { check('unknown character rejected', /选择/.test(e.message), e.message); }

console.log(failed ? `\n${failed} FAILED` : '\nALL PASS');
process.exit(failed ? 1 : 0);
