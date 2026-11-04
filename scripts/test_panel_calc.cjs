const fs = require('fs');
const path = require('path');
const vm = require('vm');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'data', 'panel-data.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'panel-calc.js'), 'utf8'), sandbox);
const P = sandbox.window.WIKI_PANEL_DATA, C = sandbox.window.WikiPanelCalc;
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
check('enchant permillage recorded', boosted.permillage[1] === 100, String(boosted.permillage[1]));

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
check('talent bonuses raise the panel', talented.total.some((v, i) => v > r.total[i]),
  r.total.join('/') + ' -> ' + talented.total.join('/'));
check('talent step recorded', talented.extras.some(e => e.key === 'talent'));
const adjusted = C.calculate(Object.assign({}, cfg, { talentAdjust: [100, 0, 0, 0, 0] }), P);
check('talent manual adjust applied', adjusted.total[0] > r.total[0],
  r.total[0] + ' -> ' + adjusted.total[0]);

// Weapon-type filtering inputs used by the UI.
const mainType = (ch.weaponTypes || []).find(t => Number(t) !== 2);
check('character weapon types exported', mainType !== undefined, JSON.stringify(ch.weaponTypes));
check('weapon filter has matches', P.weapons.some(w => Number(w.typeId) === mainType));
check('common offhand type retained', P.weapons.some(w => Number(w.typeId) === 2));

// Invalid input is reported instead of throwing NaN.
try { C.calculate(Object.assign({}, cfg, { character: '__missing__' }), P); check('unknown character rejected', false); }
catch (e) { check('unknown character rejected', /选择/.test(e.message), e.message); }

console.log(failed ? `\n${failed} FAILED` : '\nALL PASS');
process.exit(failed ? 1 : 0);
