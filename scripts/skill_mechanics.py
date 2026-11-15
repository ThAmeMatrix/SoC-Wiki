"""Round 34: compile every skill's damage / effect resolution plan.

Source of truth, in order:
  1. `skill.desc` — the client's own localised skill text ("进行3次攻击，
     每次造成50%伤害"、"消耗所有能量和[多重爆裂]…追加每层40%物理伤害").
  2. `speciality` + `speciality.dynamic_param` — the decrypted Lua logic that
     grants stacks from TP, drains TP after the attack, boosts the bonus damage,
     declares multi-hit and knockback.  Spec ids and their Lua snippets are
     recorded on each plan as `from` evidence.
  3. `skill.idskill_follow` — the client's COMPOSITE skill chain. A single
     cast is resolved as several ordered sub-skills, each with its own
     `damage_factor` and its own `speciality_ids`. 1278 client skills declare
     it (842 two-stage, 241 three-stage, 101 four-stage, …). 「百无禁忌」
     11450 (40%) → 11451 (100%) is one of them; 11451 carries three
     `MODIFY_ATTRIBUTE` rows whose Lua `active_param` reads
     `target.temp_attributes.tp_max - target.temp_attributes.tp`, i.e. the
     second segment's factor scales with the target's MISSING energy.
  4. `skill` columns (`damage_factor`, `hit_method`, `damage_type`, …).

The engine consumes `WIKI_BATTLE_MECH.skillPlans[id]`:
  g      hit groups [[count, percentFactor], …] — each hit settles separately
  h      total number of base hits
  chain  ordered client skill chain: [{id,n,df,dt,sp,boost,effects}, …]
         boost   conditional damage modifiers on that segment
                 [{spec, attr, pct, when}] — evaluated by the engine's Lua VM
                 at segment resolution, NOT hardcoded to any character
         effects every other speciality on that segment, so a composite skill
                 shows its buffs / debuffs / knockback / sub-casts too
  cons   consumption rules {tp: 1 = all energy, b: buffId, n: fixed stack count}
  bonus  extra damage segments [[percentPerConsumed, boostPercent, damageType], …]
  knock  knockback cells parsed from the description
  fx     human-readable effect lines for the step detail
  from   spec ids / Lua snippets that justify the derived numbers

    python -X utf8 scripts/extract_battle_mechanics.py
"""
from __future__ import annotations

import re

# ---- description patterns -------------------------------------------------
# "造成1次20%的伤害，3次50%的伤害" / "造成3次60%的伤害"
RE_MIXED = re.compile(r'(\d+)\s*次\s*(?:的)?\s*(\d+)\s*%')
# "进行3次攻击，每次造成50%伤害" / "造成8次伤害，每次造成20%[范围伤害]"
RE_PER_HIT = re.compile(r'(?:进行|连续|攻击)\s*(\d+)\s*次\s*(?:攻击|伤害)?[，,、;；\s]*每次造成\s*(\d+)\s*%')
RE_PER_HIT2 = re.compile(r'造成\s*(\d+)\s*次\s*(?:攻击|伤害)[，,、;；\s]*每次造成\s*(\d+)\s*%')
# "造成3次60%的伤害" (no 每次) also covered by RE_MIXED.
RE_COUNT = re.compile(r'(?:进行|造成|攻击|连续)\s*(\d+)\s*次\s*(?:攻击|伤害|连击)')
RE_SEGMENTS = re.compile(r'(\d+)\s*段\s*(?:攻击|伤害|连击)')
RE_EACH = re.compile(r'每次造成\s*(\d+)\s*%')
RE_FACTOR = re.compile(r'造成\s*(\d+)\s*%')
RE_CONSUME_TP = re.compile(r'消耗所有能量|消耗全部能量|耗尽能量')
RE_CONSUME_BUFF = re.compile(r'消耗(?:所有|全部)?(?:能量和)?[\[【]([^\]】]+)[\]】]')
RE_CONSUME_LAYERS = re.compile(r'消耗\s*(\d+)\s*层[\[【]([^\]】]+)[\]】]')
RE_BONUS = re.compile(r'追加每层\s*(\d+)\s*%\s*(物理|魔法|穿透)?')
RE_BOOST = re.compile(r'(?:通过此效果|该效果|由此)?造成的伤害提高\s*(\d+)\s*%')
RE_KNOCK = re.compile(r'击退\s*(\d+)\s*格')
# 「技能变更为：[瞬身袭]」/「技能变更为[大清洗]」/「变为[星核·位移]」.
# 153 client skills declare a post-cast skill swap in their own text.
RE_SWAP = re.compile(r'(?:技能)?变更为[：:]?\s*[\[【]([^\]】]+)[\]】]')
RE_SWAP_TURNS = re.compile(r'(?:技能)?(?:保留|持续)\s*(\d+)\s*回合')
# 「使所有〈铃兰之剑〉己方进行额外[协同响应]，效果：对自身范围3格内敌人，
#   造成50%物攻值加魔攻值的[穿透伤害]」— generic coordinated-response data.
RE_COORD = re.compile(r'(?:所有|全部)[〈<]([^〉>]+)[〉>][^。\n]{0,20}?额外[\[【]?协同响应')
RE_COORD_HIT = re.compile(r'自身范围\s*(\d+)\s*格内敌人[，,、]?造成\s*(\d+)%\s*物攻值加魔攻值')
RE_FX = [
    (re.compile(r'无视\s*(\d+)%\s*防御|无视防御'), '无视防御'),
    (re.compile(r'穿透伤害'), '穿透伤害'),
    (re.compile(r'准备\s*1\s*回合'), '准备 1 回合'),
    (re.compile(r'击退\s*(\d+)\s*格'), '击退'),
    (re.compile(r'回复\s*(\d+)%\s*生命'), '回复生命'),
    (re.compile(r'暴击率提高\s*(\d+)%'), '暴击率提高'),
    (re.compile(r'若重复攻击相同目标[，,]?伤害降低\s*(\d+)%'), '重复命中衰减'),
]


def _norm(name: str) -> str:
    return re.sub(r'[\s\[\]【】·、,，。:：\-—]', '', name or '')


def _buff_id(name, buffs, by_name):
    key = _norm(name)
    if not key:
        return None
    if key in by_name:
        return by_name[key]
    # suffix / prefix match, e.g. "多重爆裂层数" → "多重爆裂"
    for k, bid in by_name.items():
        if k and (k in key or key in k) and min(len(k), len(key)) >= 2:
            return bid
    return None


def _groups(desc, skill):
    out = []
    for m in RE_MIXED.finditer(desc):
        n, f = int(m.group(1)), int(m.group(2))
        if 0 < n <= 20 and 0 < f <= 2000:
            out.append([n, f])
    if not out:
        m = RE_PER_HIT.search(desc) or RE_PER_HIT2.search(desc)
        if m:
            n, f = int(m.group(1)), int(m.group(2))
            if 0 < n <= 20 and 0 < f <= 2000:
                out.append([n, f])
    if not out:
        m = RE_COUNT.search(desc) or RE_SEGMENTS.search(desc)
        if m:
            n = int(m.group(1))
            e = RE_EACH.search(desc) or RE_FACTOR.search(desc)
            f = int(e.group(1)) if e else int(skill.get('df') or 0)
            if 0 < n <= 20 and f > 0:
                out.append([n, f])
    # de-duplicate keeping order
    seen, uniq = set(), []
    for g in out:
        k = tuple(g)
        if k not in seen:
            seen.add(k); uniq.append(g)
    return uniq


# Client attribute_type.json `type` values that change a damage FACTOR rather
# than a base stat. Only these become a segment boost; e.g. modifier 29
# DAMAGE_FACTOR (+30% when the target is missing 1 energy) is a factor, while
# PHYSIC_ATTACK (+15%) is a base stat already handled by attr().
DAMAGE_FACTOR_TYPES = {
    'DAMAGE_FACTOR', 'DAMAGE', 'DAMAGE_MODIFY', 'FINAL_DAMAGE',
    'FINAL_DAMAGE_MULTIPLY', 'PHYSIC_DAMAGE', 'SPELL_DAMAGE',
    'FIX_DAMAGE', 'CRIT_DAMAGE',
}


def _follow_chain(sid, skills, specs, attrs):
    """Resolve the client's `idskill_follow` chain into ordered segments.

    Every speciality on every segment is preserved: conditional damage
    modifiers become `boost`, everything else becomes `effects`. No skill id
    is special-cased — the numbers and the activation Lua come straight from
    the decoded tables.
    """
    out = []
    attrs = {str(k): v for k, v in (attrs or {}).items()}
    cur, seen, guard = str(sid), set(), 0
    while cur and cur not in seen and guard < 10:
        sk = skills.get(cur)
        if not sk:
            break
        seen.add(cur); guard += 1
        seg = {'id': int(cur), 'n': sk.get('n') or '', 'df': int(sk.get('df') or 0),
               'dt': int(sk.get('dt') or 0),
               'sp': [int(x) for x in (sk.get('sp') or []) if x],
               'boost': [], 'effects': []}
        for x in seg['sp']:
            sx = specs.get(str(x))
            if not sx:
                continue
            t, at = sx.get('t') or '', _int(sx.get('at'))
            p = sx.get('p') or [0, 0, 0, 0]
            when = (sx.get('c') or sx.get('dp') or '')[:200]
            pct = _int(p[2] if len(p) > 2 else 0) or _int(p[1] if len(p) > 1 else 0)
            atype = attrs.get(str(_int(p[0]) if len(p) else 0), '')
            if (t == 'MODIFY_ATTRIBUTE' and at in (1, 2, 4) and pct
                    and atype in DAMAGE_FACTOR_TYPES):
                seg['boost'].append({'spec': int(x), 'attr': _int(p[0]),
                                     'attrName': atype, 'pct': pct,
                                     'when': when, 'name': sx.get('n') or ''})
            elif t == 'MODIFY_ATTRIBUTE':
                # Base-stat modifiers stay in `effects` for the composite view
                # but must not be double-counted as a segment factor.
                seg['effects'].append({'spec': int(x), 't': t, 'at': at,
                                       'n': sx.get('n') or '', 'p': p[:4], 'when': when})
            elif t and t not in ('SKILL_RANGE', 'MULTI_ATTACK', 'SUB_ATTACK', 'AOE',
                                 'MODIFY_ATTRIBUTE', 'GET_EXTRA_SKILL', 'IMMUNE'):
                seg['effects'].append({'spec': int(x), 't': t, 'at': at,
                                       'n': sx.get('n') or '', 'p': p[:4], 'when': when})
        out.append(seg)
        nxt = _int(sk.get('fl'))
        cur = str(nxt) if nxt else None
    return out


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def derive_plans(skills, specs, buffs, attrs=None, unit_tags=None):
    """Return {skillId(str): plan} for every skill with resolvable mechanics."""
    # Out_* dictionaries use integer keys; JSON serialises them as strings.
    # Normalise here so spec / buff lookups work in both contexts.
    specs = {str(k): v for k, v in specs.items()}
    buffs = {str(k): v for k, v in buffs.items()}
    skills = {str(k): v for k, v in skills.items()}
    # Skill-name → id and unit-tag-name → id, for the description-declared
    # 「技能变更为：[X]」and 〈阵营〉 coordinated responses.
    skill_by_name = {}
    for sid, sk in skills.items():
        key = _norm(sk.get('n'))
        if key and key not in skill_by_name:
            skill_by_name[key] = int(sid)
    tag_by_name = {}
    for tid, tname in (unit_tags or {}).items():
        key = _norm(tname)
        if key and key not in tag_by_name:
            tag_by_name[key] = int(tid)
    by_name = {}
    for bid, b in buffs.items():
        n = _norm(b.get('n'))
        if n and n not in by_name:
            by_name[n] = int(bid)
    # Prefer the exact, shortest named buff for ambiguous lookups.
    by_name = dict(sorted(by_name.items(), key=lambda kv: len(kv[0])))

    plans = {}
    stats = {'groups': 0, 'consume': 0, 'bonus': 0, 'knock': 0, 'chains': 0, 'boosts': 0}
    for sid, sk in skills.items():
        desc = sk.get('descFull') or sk.get('desc') or ''
        sp = sk.get('sp') or []
        df = int(sk.get('df') or 0)
        dt = int(sk.get('dt') or 0)
        groups = _groups(desc, sk)
        # Client `idskill_follow`: one cast, several ordered sub-skills.
        chain = _follow_chain(sid, skills, specs, attrs)
        chain_damage = [x for x in chain if x['df'] > 0]
        if len(chain_damage) > 1 and (not groups or (len(groups) == 1 and groups[0][0] == 1)):
            groups = [[1, x['df']] for x in chain_damage]
        if len(chain) > 1:
            stats['chains'] += 1
        stats['boosts'] += sum(len(x['boost']) for x in chain)

        # Multi-hit / at=2 spec evidence from the decrypted speciality rows.
        spec_hits, evidence = [], []
        for x in sp:
            sx = specs.get(str(x))
            if not sx:
                continue
            t = sx.get('t')
            if t in ('MULTI_ATTACK', 'SUB_ATTACK'):
                n = int((sx.get('p') or [0])[0] or 0)
                if 0 < n <= 20:
                    spec_hits.append([n, df or 100])
            if t == 'SPECIAL_SKILL_CONSUME' or (t == 'RECOVER_ATTRIBUTE' and
                    (sx.get('at') == 3) and (sx.get('p') or [0, 0])[1] < 0) or \
                    (t == 'BUFF' and 'temp_attributes.tp' in (sx.get('dp') or '')) or \
                    (t == 'MODIFY_ATTRIBUTE' and 'MuiltyBoom' in (sx.get('c') or '')):
                evidence.append(str(x))
        if not groups and spec_hits:
            groups = spec_hits[:1]

        # ---- consumption + bonus -----------------------------------------
        cons, bonus = {}, []
        desc_tp = bool(RE_CONSUME_TP.search(desc))
        if desc_tp or any(
                specs.get(str(x), {}).get('t') == 'RECOVER_ATTRIBUTE' and
                specs.get(str(x), {}).get('at') == 3 and
                (specs.get(str(x), {}).get('p') or [0, 0])[1] < 0 for x in sp):
            cons['tp'] = 2 if desc_tp else 1
            cons['apply'] = 1 if desc_tp else 0
        m = RE_CONSUME_BUFF.search(desc)
        if m:
            bid = _buff_id(m.group(1), buffs, by_name)
            if bid:
                cons['b'] = bid
                cons['apply'] = 1
        m = RE_CONSUME_LAYERS.search(desc)
        if m:
            bid = _buff_id(m.group(2), buffs, by_name)
            if bid:
                cons['b'] = bid; cons['n'] = int(m.group(1))
        if not cons.get('b'):
            for x in sp:
                sx = specs.get(str(x)) or {}
                if sx.get('t') == 'SPECIAL_SKILL_CONSUME':
                    p = sx.get('p') or []
                    if len(p) >= 3 and p[2]:
                        cons['b'] = int(p[2])
                        if p[3]:
                            cons['n'] = int(p[3])
                        break
        bm = RE_BONUS.search(desc)
        gb = RE_BOOST.search(desc)
        if bm:
            kind = bm.group(2) or '物理'
            bonus.append([int(bm.group(1)), int(gb.group(1)) if gb else 0,
                          4 if kind == '穿透' else 2 if kind == '魔法' else 1])
        if bonus and cons:
            cons['apply'] = 1        # bonus damage needs a definitive total
        if cons:
            stats['consume'] += 1
        if bonus:
            stats['bonus'] += 1
        if groups and (len(groups) > 1 or groups[0][0] > 1):
            stats['groups'] += 1

        km = RE_KNOCK.search(desc)
        knock = int(km.group(1)) if km else 0
        if knock:
            stats['knock'] += 1

        # ---- display effects ---------------------------------------------
        fx = []
        for g in groups:
            fx.append(f'{g[0]} 段 × {g[1]}%')
        if cons.get('tp'):
            fx.append('消耗所有能量')
        if cons.get('b'):
            nm = (buffs.get(str(cons['b'])) or {}).get('n') or f"buff #{cons['b']}"
            fx.append(f"消耗 [{nm}]{' ' + str(cons['n']) + ' 层' if cons.get('n') else ' 全部层数'}")
        for b in bonus:
            fx.append(f'追加每层 {b[0]}% {"穿透" if b[2] == 4 else "魔法" if b[2] == 2 else "物理"}伤害')
            if b[1]:
                fx.append(f'该追加伤害提高 {b[1]}%')
        if knock:
            fx.append(f'击退 {knock} 格')
        for rx, label in RE_FX:
            mm = rx.search(desc)
            if mm:
                fx.append(label + (f' {mm.group(1)}' if mm.groups() and mm.group(1) else ''))

        # A plan is only useful when it changes resolution or explains it.
        # Only a MULTI-STAGE client chain (idskill_follow) forces a new plan;
        # a single-stage skill's composite effects are compiled at runtime by
        # the engine from `skills[id].sp`, so we must NOT turn every plain
        # skill into an "interesting" plan (that would route them through the
        # segment loop and change their hit counts).
        # Client `skill_cast_id`: the real cast skill (15934 → 15968) carries
        # the damage / CAST_SKILL chain. Keep the id so the engine can resolve
        # the whole 协同号令 pipeline from data instead of description text.
        cast_id = int(sk.get('scid') or 0)
        # 「技能变更为：[X]」— resolve the target from the client's own REPLACE_SKILL
        # rows first (authoritative), then the skill name in the description.
        swap_to = int(sk.get('ovid') or 0)
        swap_name = ''
        sm = RE_SWAP.search(desc)
        if sm:
            swap_name = sm.group(1).strip()
            if not swap_to:
                for x in sp:
                    sx = specs.get(str(x)) or {}
                    if sx.get('t') == 'REPLACE_SKILL' and int(sx.get('p', [0])[0] or 0) == int(sid):
                        swap_to = int(sx.get('p', [0, 0])[1] or 0)
                        break
            if not swap_to:
                swap_to = skill_by_name.get(_norm(swap_name), 0)
            # 「贯日强击」/「瞬身袭」swap back and forth through a buff that
            # carries REPLACE_SKILL at=1 (buff 7509 → spec 25150/25164).
            if not swap_to:
                for q in specs.values():
                    if q.get('t') == 'REPLACE_SKILL' and int(q.get('p', [0])[0] or 0) == int(sid):
                        swap_to = int(q.get('p', [0, 0])[1] or 0)
                        break
        # Only text AFTER the swap phrase may declare its duration — earlier
        # "（持续2回合）" clauses describe terrain, not the skill swap.
        tm = RE_SWAP_TURNS.search(desc[sm.end():]) if sm else None
        swap_turns = int(tm.group(1)) if tm else 0
        # Generic 〈阵营〉额外协同响应 from skill description.
        coord = None
        cm = RE_COORD.search(desc)
        if cm:
            hm = RE_COORD_HIT.search(desc)
            coord = {'faction': cm.group(1).strip(),
                     'tag': tag_by_name.get(_norm(cm.group(1)), 0),
                     'radius': int(hm.group(1)) if hm else 3,
                     'factor': int(hm.group(2)) if hm else 50,
                     'mixed': True}
        has_chain = len(chain) > 1
        interesting = (groups and (len(groups) > 1 or groups[0][0] > 1 or
                                   groups[0][1] != df)) or cons or bonus or knock or fx or has_chain \
            or cast_id or swap_to or coord
        if not interesting:
            continue
        if not groups and df > 0 and dt in (1, 2, 4):
            groups = [[1, df]]

        plan = {'g': groups, 'h': max(1, sum(g[0] for g in groups))}
        # A Status-class 「协同号令」/「号令」skill has damage_factor 0 and
        # carries only an AOE speciality, yet its client description declares
        # a piercing-damage hit over that area. Parse the factor here instead
        # of hard-coding skill ids (麦莎·SP 全装甲集火号令！ = 80%).
        pierce = re.search(r'造成\s*(\d+)%\s*[^。；\n]{0,24}穿透伤害', desc)
        # `skill_cast_id` is authoritative: 15934's cast skill 15968 has
        # damage_factor 80 / damage_type 4 (穿透). Prefer the client column
        # over the localised description text.
        cast_df = int((skills.get(str(cast_id)) or {}).get('df') or 0)
        if (pierce or cast_df) and any(specs.get(str(x), {}).get('t') == 'AOE' for x in sp):
            plan['pierce'] = cast_df or int(pierce.group(1))
            plan['pierceArea'] = 1
        # Attach the full composite view wherever a plan already exists;
        # the engine also has a runtime compiler as a fallback.
        plan['chain'] = chain
        if cast_id:
            plan['castId'] = cast_id
        if swap_to:
            plan['swapTo'] = swap_to
            plan['swapName'] = swap_name
            if swap_turns:
                plan['swapTurns'] = swap_turns
        if coord:
            plan['coord'] = coord
        if cons:
            plan['cons'] = cons
        if bonus:
            plan['bonus'] = bonus
        if knock:
            plan['knock'] = knock
        if fx:
            plan['fx'] = fx[:10]
        if evidence:
            plan['from'] = evidence[:8]
        if dt:
            plan['dt'] = dt
        plans[str(sid)] = plan
    return plans, stats
