/* Semantic matching adapted from evangelpeach/llzj. See THIRD_PARTY_NOTICES.md. */
window.WikiSemantic=(()=>{
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const GROUP_MAP = {
  '定身': ['晕眩','睡眠','冰封','冰柩','失衡','被讽','跳过回合','嘲讽','魅惑'],
  '干扰': ['致盲','目眩','沙尘','缠缚','缴械','衰弱','强制直行','▼移动','×主动技','×被动技','×反应技','×援护','▼束缚视界','能量阻滞'],
  '控制': ['晕眩','睡眠','冰封','冰柩','失衡','被讽','跳过回合','嘲讽','魅惑','致盲','目眩','沙尘','缠缚','缴械','衰弱','强制直行','▼移动','×主动技','×被动技','×反应技','×闪避','击退','打断'],
  '行为减益': ['×主动技','×被动技','×反应技','×装备技','×符文技','×闪避','致盲','强制直行','晕眩','睡眠','冰封','嘲讽','▼移动'],
  '持续伤害': ['灼烧','感染','生命流失','圣痕','蚀炎','冻伤','次级冻伤','剧毒','流血','点燃','能量反噬'],
  '生命流失': ['冻伤','次级冻伤','剧毒','流血','点燃','能量反噬'],
  '属性减益': ['▼攻击','▼物防','▼魔防','▼暴击','▼暴伤','▼伤害','易伤','▼速度','▼受治疗'],
  '属性增益': ['▲攻击','▲伤害','▲暴击','▲暴伤','▲物防','▲魔防','免伤'],
  '攻击属性减益': ['▼攻击','▼伤害','▼暴击','▼暴伤'],
  '防御属性减益': ['▼物防','▼魔防','易伤'],
  '防御属性增益': ['▲物防','▲魔防','免伤'],
  '冰封类': ['冰封','冰柩']
};
/* 语义同义词表：关键词片段 -> 原文写法的正则（可扩展） */
const SEM_MAP = {
  '百分比': '\\d{1,3}%',
  '我方': '(?:己方|我方|友军|友方)',
  '己方': '(?:己方|我方|友军|友方)',
  '友方': '(?:己方|我方|友军|友方)',
  '友军': '(?:己方|我方|友军|友方)',
  '敌方': '(?:敌方|敌人|敌军)',
  '敌人': '(?:敌方|敌人|敌军)',
  '敌军': '(?:敌方|敌人|敌军)',
  '增益': '(?:▲|增益)',
  '减益': '(?:▼|减益)',
  '吸血': '(?:吸血|生命汲取)',
  '生命汲取': '(?:生命汲取|吸血)'
};
/* 广义词展开为「自身|成员」正则，长键优先 */
for(const g of Object.keys(GROUP_MAP).sort((a,b)=>b.length-a.length)){
  SEM_MAP[g] = '(?:' + [g, ...GROUP_MAP[g]].map(escRe).join('|') + ')';
}
/* 命中广义词时显示「XX类」标签 */
function groupHitTag(frag, kw){
  if(!frag || !kw) return '';
  const {rest} = parseCamp(kw);
  const k = rest || kw;
  for(const g of Object.keys(GROUP_MAP).sort((a,b)=>b.length-a.length)){
    if(k.includes(g)){
      const hit = GROUP_MAP[g].filter(m=>frag.includes(m));
      if(hit.length) return `<span class="gtg" title="${esc(g)}类：${esc(hit.slice(0,3).join('、'))}">⟡${esc(g)}类</span>`;
    }
  }
  return '';
}
const ALLY_RE = /我方|己方|友方|友军/;
const ENEMY_RE = /敌方|敌人|敌军/;
function campRe(camp){ return camp === 'ally' ? ALLY_RE : ENEMY_RE; }
/* 从关键词中提取阵营约束：返回 {camp:'ally'|'enemy'|null, rest:剩余关键词} */
function parseCamp(kw){
  let camp = null, rest = kw;
  if(ALLY_RE.test(kw)){ camp = 'ally'; rest = kw.replace(ALLY_RE, ''); }
  else if(ENEMY_RE.test(kw)){ camp = 'enemy'; rest = kw.replace(ENEMY_RE, ''); }
  rest = rest.replace(/^[的之与和或]+|[的之与和或]+$/g, '').trim();
  return {camp, rest};
}
/* 阵营约束匹配：rest 命中且（若有阵营约束）文本含对应阵营词；无命中返回 null */
function matchWithCamp(text, kw, camp){
  if(!text) return null;
  if(camp && !campRe(camp).test(text)) return null;
  if(!kw){
    if(!camp) return null;
    const cr = execAll(new RegExp(campRe(camp).source, 'gi'), text, 20);
    return cr.length ? cr : null;
  }
  const rs = findMatches(text, kw);
  return rs.length ? rs : null;
}
/* 检测文本中的阵营标签 */
function campTags(text){
  const tags = [];
  if(!text) return tags;
  if(ALLY_RE.test(text)) tags.push('己方');
  if(ENEMY_RE.test(text)) tags.push('敌方');
  if(/自身/.test(text)) tags.push('自身');
  return tags;
}
function campTagHtml(text){
  return campTags(text).map(t=>`<span class="ctag ${t==='己方'?'ally':t==='敌方'?'enemy':'self'}">${t}</span>`).join('');
}
function escRe(s){return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}
function hasSem(kw){return Object.keys(SEM_MAP).some(w=>kw.includes(w))}
/* 将关键词切分为正则单元：语义词→(?:正则|原词)，普通字符→转义字符 */
function buildUnits(kw){
  const units = [];
  let i = 0;
  while(i < kw.length){
    let matched = false;
    for(const w of Object.keys(SEM_MAP)){
      if(kw.startsWith(w, i)){
        units.push('(?:' + SEM_MAP[w] + '|' + escRe(w) + ')');
        i += w.length; matched = true; break;
      }
    }
    if(!matched){ units.push(escRe(kw[i])); i++; }
  }
  return units;
}
function execAll(re, t, limit){
  const ranges = [];
  let m, guard = 0;
  re.lastIndex = 0;
  while((m = re.exec(t)) && guard++ < limit){
    if(m[0].length === 0){ re.lastIndex++; continue; }
    ranges.push({idx:m.index, len:m[0].length});
    re.lastIndex = m.index + m[0].length;
  }
  return ranges;
}
/* 模糊匹配：①精确子串 ①b语义无间隔 ②字符间允许0-3个任意字符 ③分词AND */
/* 原子术语表：并列类别词，不参与分词拆分（搜「穿透伤害」不命中「物理伤害」） */
const ATOM_WORDS = ['物理范围伤害','物理伤害','魔法伤害','穿透伤害','范围伤害','远程伤害','持续伤害','灵感伤害','百分比伤害','真实伤害','固定伤害','协同伤害','反弹伤害','穿透易伤','冰火易伤','火属性','冰属性','雷属性','沙属性','暗属性','光属性','物理护盾','魔法护盾','属性减益','属性增益','生命流失','能量反噬'];
function isAtom(kw){ return ATOM_WORDS.some(a=>kw.includes(a)); }

function findMatches(text, kw){
  if(!kw || !text) return [];
  const t = String(text), tl = t.toLowerCase(), k = kw.toLowerCase();
  // ① 精确
  let ranges = [];
  let i = tl.indexOf(k);
  while(i >= 0){ ranges.push({idx:i, len:kw.length}); i = tl.indexOf(k, i+kw.length); }
  if(ranges.length) return ranges;
  const sem = hasSem(kw);
  // ①b 语义无间隔（如「百分比」命中「10%」）
  if(sem){
    ranges = execAll(new RegExp(buildUnits(kw).join(''), 'gi'), t, 20);
    if(ranges.length) return ranges;
  }
  // ② 近距离模糊（关键词≥3字）
  if(kw.length >= 3){
    ranges = execAll(new RegExp(buildUnits(kw).join('[\\s\\S]{0,3}?'), 'gi'), t, 20);
    if(ranges.length) return ranges;
  }
  // ③ 分词 AND：原子术语不拆分（避免「穿透伤害」拆成「穿透」+「伤害」误命中「物理伤害」）
  if(isAtom(kw)) return [];
  let segsList = [];
  const segs = kw.split(/[的之与和或]/).filter(p=>p.length>=2);
  if(segs.length >= 2){
    segsList = [segs];
  } else if(kw.length >= 4){
    for(let i=2;i<=kw.length-2;i++) segsList.push([kw.slice(0,i), kw.slice(i)]);
  }
  for(const ss of segsList){
    let all = [], ok = true;
    for(const seg of ss){
      const rs = findMatches(t, seg);
      if(!rs.length){ ok = false; break; }
      all = all.concat(rs);
    }
    if(ok){ all.sort((a,b)=>a.idx-b.idx); return all; }
  }
  return [];
}
function findMatch(text, kw){
  const r = findMatches(text, kw);
  return r.length ? r[0] : null;
}
/* 匹配级别：3=精确子串 2=语义 1=近距离模糊 0.5=分词AND 0=无 */
function matchLevel(text, kw){
  if(!kw || !text) return 0;
  const t = String(text), tl = t.toLowerCase(), k = kw.toLowerCase();
  if(tl.includes(k)) return 3;
  try{
    if(hasSem(kw) && new RegExp(buildUnits(kw).join(''), 'i').test(t)) return 2;
    if(kw.length >= 3 && new RegExp(buildUnits(kw).join('[\\s\\S]{0,3}?'), 'i').test(t)) return 1;
  }catch(e){}
  return 0.5;
}
function hl(text, kw){
  if(!kw) return esc(text);
  const {camp, rest} = parseCamp(kw);
  let parts = [];
  if(rest) parts = parts.concat(findMatches(text, rest));
  if(camp) parts = parts.concat(execAll(new RegExp(campRe(camp).source, 'gi'), text, 30));
  if(!rest && !camp) parts = findMatches(text, kw);
  if(!parts.length) return esc(text);
  parts.sort((a,b)=>a.idx-b.idx);
  let result = '', pos = 0;
  for(const r of parts){
    if(r.idx < pos) continue;
    result += esc(text.slice(pos, r.idx)) + '<mark>' + esc(text.substr(r.idx, r.len)) + '</mark>';
    pos = r.idx + r.len;
  }
  return result + esc(text.slice(pos));
}
function snippet(text, kw, len=46){
  if(!text) return '';
  const {rest} = parseCamp(kw);
  const m = findMatch(text, rest || kw);
  if(!m) return String(text).slice(0, len) + (text.length>len?'…':'');
  const start = Math.max(0, m.idx-14);
  const end = Math.min(text.length, m.idx + m.len + len - 20);
  return (start>0?'…':'') + text.slice(start, end) + (end<text.length?'…':'');
}


return {findMatches,matchWithCamp,parseCamp,matchLevel,hl,snippet,groupHitTag};})();
