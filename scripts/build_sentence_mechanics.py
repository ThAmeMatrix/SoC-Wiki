#!/usr/bin/env python3
"""Sentence-level mechanism map: every sentence of a skill / personality
description -> client speciality rows -> the engine code that executes them.

    python -X utf8 scripts/build_sentence_mechanics.py

Outputs
  data/sentence-mechanics.js  window.WIKI_SENTENCE_MECHANICS
      skills[id]   = {n, s: [{t, s:[specIds], b:[buffIds], k:[skillIds], c:[commonIds]}], x:[specIds]}
      specs[id]    = {t, at, p, n, text, refs:[commonIds], st, c?, kids?:[specIds], link?}
      buffs[id]    = {n, d, sp:[specIds], et}
      personalities[rowId] = {n, stars: {star: [skillIds]}}
  data/mechanics-code.js      window.WIKI_MECHANICS_CODE
      common[id]   = {label, cat, doc, client?, anchors:[{f,l,sym,role,code}], count}
      meta         = coverage statistics + gaps

Everything is derived from the decrypted client tables (data/battle-mech.js,
data/skill-mechanics.js, output/archive/.../配置表) and the engine source
(battle-sim-core.js, indexed by scripts/engine_index.py). Line numbers are
recomputed on every build, so they never go stale after an engine edit.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_index import EngineIndex, spread  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / 'output' / 'archive' / 'library' / '当前版本' / '配置表'
OUT_SENT = ROOT / 'data' / 'sentence-mechanics.js'
OUT_CODE = ROOT / 'data' / 'mechanics-code.js'


def load_js(name, var):
    text = (ROOT / 'data' / name).read_text('utf8')
    marker = 'window.' + var + '='
    return json.JSONDecoder().raw_decode(text[text.index(marker) + len(marker):])[0]


def table(name):
    for p in CFG.rglob(name + '.json'):
        try:
            return json.loads(p.read_text('utf8'))
        except ValueError:
            pass
    return []


def num(v, d=0):
    try:
        return int(float(str(v if v not in (None, '') else d)))
    except (TypeError, ValueError):
        return d


def clean(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', str(s or ''))).strip()


def norm(s):
    return re.sub(r'[\s\[\]【】「」“”"\'·•‧・]', '', clean(s))


# ---------------------------------------------------------------------------
# Core (non-speciality) mechanisms. Each names the engine symbols that carry
# it; anchors are resolved against the live source on every build.
CORE = {
    'damage': ('伤害结算', '伤害', ['function dealDamage(', 'function zoneFactors(', 'function castSkill('],
               '技能的伤害段先按 攻击力×倍率 − 防御 求基础值（攻−防下限为攻击力 5%），再依次乘以造成伤害区（加算，下限 −50%）、'
               '受到伤害区（易伤/免伤逐来源连乘，上限 300%）、职业克制、受伤/濒死、高低差与暴击，最后由 dealDamage() 扣除护盾与生命并派发受击时点。'),
    'pierce': ('穿透伤害', '伤害', ['function dealDamage(', "pierce: true"],
               '穿透伤害不计防御与增减伤/免伤，只受「造成/受到穿透伤害修正」（上限 230%），且不暴击；持续伤害默认按穿透结算。'),
    'heal': ('治疗结算', '治疗', ['function heal('],
             '治疗量 = 来源属性×倍率，乘以施法者治疗加成与目标「受到治疗」修正；受治疗逆转等状态会把治疗转为穿透伤害。'),
    'energy': ('能量（TP）', '资源', ['function usable(', "n === 'TP'"],
               '施放技能扣除消耗能量，行动结束回复 1 点；RECOVER_ATTRIBUTE / STEAL_TP 等特技直接增减 TP，能量不足的技能不会进入 AI 候选。'),
    'cooldown': ('技能冷却', '资源', ['function usable(', 'u.cd[s.id] ='],
                 '施放后写入冷却回合，每次行动结束 −1；冷却未清零的技能不可用（usable()）。'),
    'range': ('射程与选格', '范围', ['function targetCells(', 'function castRangeOffsets(', 'function rangeMods('],
              '射程取客户端 range_min/range_max 与 target_select 形状（菱形/十字/单向线…），叠加 SKILL_RANGE / EXTEND_CAST_RANGE 等修正；平射会被弹道上的敌人阻挡。'),
    'area': ('作用范围（AOE）', '范围', ['function areaCells(', 'function displayAreaOf('],
             '作用范围由 aoe_param 解码为菱形/十字/矩形/方向线等几何，DISPLAY_AOE 可替换实际结算范围；范围内每个合法目标分别结算伤害与命中后时点。'),
    'instant': ('瞬发', '行动', ['function act('],
                '描述开头带 [瞬发] 的技能施放后不结束行动：按 CHECK_STATE → DO_SKILL → MOVE_OR_IDLE 用剩余移动力继续行动，直到放出非瞬发技能。'),
    'swap': ('技能变更', '技能链', ['function replaceSkill(', 'function applySwapTimers('],
             '「技能变更为[X]」由 overwritten_skill_id / REPLACE_SKILL 驱动：替换技能槽、重建派生索引，并按保留回合在到期后换回。'),
    'knockback': ('击退/位移', '位移', ['function knockback('],
                  '击退方向按手册规则（对角线距离减半）；撞到单位/障碍/高差>2 停止并造成撞击伤害，下落高差>2 受坠落伤害，深水/深渊直接击败。'),
    'move': ('移动与传送', '位移', ['function moveUnit(', 'function approachField('],
             '移动按移动力与地形消耗寻路，高差≥2 每步额外 0.5；传送/瞬移类特技直接改写坐标并重新结算地块与光环。'),
    'extra_action': ('再行动', '行动', ['function act(', "ACTED_ACT(inst"],
                     '再行动（ACTED_ACT / RE_ROUND）在当前行动后立即获得新的行动机会；p[0] 限定可用技能，「行动后」时点每次行动只触发一次。'),
    'shield': ('护盾', '防御', ['function dealDamage(', "s.t === 'PHYSIC_ARMOR'"],
               '物理/魔法护盾按 属性×百分比×层数 计算，伤害先扣除对应类型护盾值再扣生命；护盾完全抵挡时部分减益不生效。'),
    'buff': ('状态（增益/减益）', '状态', ['function addBuff(', 'function removeBuff(', 'function buffOn('],
             '状态按 buff 表的互斥类别、层数上限与持续回合叠加；end_time 决定在行动开始或结束时递减；状态自身的特技在其 active_time 派发，active_param 不满足时状态保持休眠。'),
    'condition': ('触发条件（Lua）', '条件', ['function cond(', 'function luaEnv('],
                  '特技的 active_param 是客户端 Lua 表达式，由内置解释器在触发时求值：owner=特技持有者、target=事件另一方、skill=当前技能；求值失败计入覆盖率报告。'),
    'dynamic': ('动态参数（Lua）', '条件', ['function resolvedSpec('],
                'dynamic_param 在每次结算前运行客户端 Lua，按层数/属性/状态改写 param0–3（例如「每层+10%物攻」）。'),
    'limits': ('触发次数限制', '条件', ['function limitOk(', 'function scopedLimitOk('],
               'limit_count / limit_count_turn 按持有者计数；limit_count_command / per_entity_command / per_entity_turn 再按「一次行动 / 目标 / 回合」细分。'),
    'backstab': ('背击/侧击', '伤害', ['function relPos('],
                 '按攻击者相对目标朝向判定正面/侧面/背后，背击派发 45/46 时点并参与 FORCE_BACKSTAB 与方向条件判定。'),
    'height': ('高低差', '伤害', ['function heightOf('],
               '高处攻击低处（高差≥2）伤害提高、反之降低，另叠加 HEIGHT_ATTACK 特技；射程与范围的高低限制同样按高差判定。'),
    'field': ('地形与地块状态', '地形', ['function setFieldStatus(', 'function runFieldSpecs('],
              '地块状态（燃烧/冰冻/烟雾…）由 OPERATION 改写，按 field_status 的优先级与不可覆盖规则；进入/停留时派发地块特技，地块光环（如烟雾隐身）由 refreshAuras() 授予。'),
    'summon': ('召唤物', '召唤', ['function spawnUnitFrom('],
               '召唤物是完整单位：继承模板属性与技能、拥有独立行动回合；客户端 cast_limit / total_limit 限制同屏与总次数。'),
    'stacks': ('层数', '状态', ['function addBuff('],
               '同一状态再次施加时层数累加至 stack_count 上限，持续回合取较长者；层数参与动态参数、消耗与 BUFF_STACK_MODIFY_ATTRIBUTE 计算。'),
    'consume': ('消耗层数/能量', '资源', ["CONSUME_BUFF(inst", "MULTI_CONSUME_TP"],
                '「消耗N层[X]」按层扣除状态并把消耗量写入后续伤害段；「消耗所有能量」按消耗量放大技能效果。'),
    'hp_attenuation': ('受伤/濒死', '状态', ["hpAttenuation"],
                       '生命低于阈值进入受伤/濒死，按 hp_attenuation 表修正造成与受到的伤害。'),
    'restrain': ('职业克制', '伤害', ['restrain'],
                 '攻击被克制职业时造成伤害提高、反之降低（profession_restrain），在伤害公式的克制区相乘。'),
    'ai': ('AI 施放决策', 'AI', ['function decide(', 'function evaluate('],
           '自动对局按技能分组优先级（个性/携带/普攻）、skill_orders 与客户端 15 个选位比较器为每个「技能×站位×目标」打分，取最高分执行。'),
}

# Sentence keywords -> core mechanism / speciality type.
KEYWORDS = [
    (r'穿透伤害', 'core:pierce'),
    (r'造成[^。；]{0,40}?伤害|伤害倍率|附加[^。；]{0,20}伤害|伤害[^。；]{0,6}(提高|降低|减少|额外)|倍率', 'core:damage'),
    (r'治疗|回复[^。；]{0,12}生命|恢复[^。；]{0,12}生命', 'core:heal'),
    (r'能量', 'core:energy'),
    (r'冷却', 'core:cooldown'),
    (r'击退|后退|拉近|拉至|拉到', 'core:knockback'),
    (r'传送|瞬移|位移|冲锋|跳跃至|移动到', 'core:move'),
    (r'射程', 'core:range'),
    (r'范围|区域|\d+\s*[\*×xX]\s*\d+|菱形|十字|直线|周围', 'core:area'),
    (r'瞬发', 'core:instant'),
    (r'变更为', 'core:swap'),
    (r'召唤', 'core:summon'),
    (r'护盾', 'core:shield'),
    (r'驱散|清除[^。；]{0,8}(减益|增益|状态|效果)', 'type:DISPEL'),
    (r'移除|解除|获得[^。；]{0,12}免疫', 'type:REMOVE_BUFF'),
    (r'免疫', 'type:IMMUNE'),
    (r'闪避', 'type:EVADE'),
    (r'格挡', 'type:PARRY'),
    (r'反击', 'type:COUNTER_ATTACK'),
    (r'警戒', 'type:ALERT_ATTACK'),
    (r'援护|协防', 'type:ASSIST_DEFENCE'),
    (r'协攻|援攻|协同响应', 'type:ASSIST_ATTACK'),
    (r'先制', 'type:FIRST_HIT'),
    (r'嘲讽', 'type:TAUNT'),
    (r'再移动', 'type:ACTED_MOVE'),
    (r'再行动|额外行动|再动', 'core:extra_action'),
    (r'光环', 'type:AURA'),
    (r'复活|不屈', 'type:REBORN'),
    (r'背击|背后|背面|侧面', 'core:backstab'),
    (r'高低差|高处|低处|高度', 'core:height'),
    (r'地形|地块|地表', 'core:field'),
    (r'抉择|选择使用', 'type:SKILL_GROUP'),
    (r'消耗', 'core:consume'),
    (r'\d+\s*层|层数', 'core:stacks'),
    (r'受伤|濒死', 'core:hp_attenuation'),
    (r'克制', 'core:restrain'),
    (r'持续\s*\d+\s*回合|回合|拥有\[[^]]+\]效果|获得\[[^]]+\]效果', 'core:buff'),
    (r'次数|最多\s*\d+\s*次|每回合\s*\d+\s*次', 'core:limits'),
]
KEYWORD_RE = [(re.compile(p), ref) for p, ref in KEYWORDS]

# Fallback for sentences with no speciality / buff / keyword match. These are
# mostly personality cards and passive descriptions that state a bare stat
# modifier or a trigger timing. They resolve to the SAME code anchors used by
# the common catalog (attr() / fire()), never to a guessed speciality row.
ATTR_SENTENCE = [
    (re.compile(r'暴击率|暴击伤害|暴伤'), 'CRIT_RATIO'),
    (re.compile(r'物攻|物理攻击'), 'PHYSIC_ATTACK'),
    (re.compile(r'魔攻|魔法攻击'), 'SPELL_ATTACK'),
    (re.compile(r'物防|物理防御'), 'PHYSIC_DEFENCE'),
    (re.compile(r'魔防|魔法防御'), 'SPELL_DEFENCE'),
    (re.compile(r'攻防|攻击.*防御|物攻.*物防'), 'PRIMARY_ATTRIBUTES'),
    (re.compile(r'生命值?|血量'), 'HP_MAX'),
    (re.compile(r'速度|移动力'), 'MOBILITY'),
    (re.compile(r'护盾'), 'ARMOR_FACTOR'),
    # Bare 「攻击提升8%」/「防御提高20%」 without a 物/魔 qualifier.
    (re.compile(r'攻击(?:力)?(?:提高|提升|增加|降低)'), 'PHYSIC_ATTACK'),
    (re.compile(r'防御(?:力)?(?:提高|提升|增加|降低)'), 'PHYSIC_DEFENCE'),
]
TIMING_SENTENCE = [
    (re.compile(r'战斗开始|加入战斗'), 25),
    (re.compile(r'回合开始'), 26),
    (re.compile(r'行动开始'), 27),
    (re.compile(r'回合结束|行动结束'), 28),
    (re.compile(r'被击败|被击杀|死亡时'), 12),
    (re.compile(r'击败|击杀'), 11),
    (re.compile(r'被攻击后|受到伤害后|受到一定伤害'), 8),
    (re.compile(r'被攻击前|被攻击时'), 4),
    (re.compile(r'主动攻击时|攻击前|攻击时'), 2),
    (re.compile(r'攻击后|使用技能后'), 3),
]
USAGE_SENTENCE = re.compile(r'每场战斗最多使用|最多同时存在|每回合最多|只能被选择\s*\d+\s*次|使用次数')

# Speciality types the sentence keywords hint at (bonus when matching rows).
TYPE_HINTS = {
    'core:damage': {'DAMAGE', 'ADDITIONAL_ATTRIBUTE_DAMAGE', 'ATTRIBUTE_DAMAGE', 'ADDITIONAL_ATTACK', 'MULTI_ATTACK', 'SUB_ATTACK',
                    'MODIFY_ATTRIBUTE', 'BUFF_STACK_MODIFY_ATTRIBUTE', 'HIT_COUNT_MODIFY_ATTRIBUTE', 'DISTANCE_MODIFY_ATTRIBUTE'},
    'core:heal': {'RECOVER_ATTRIBUTE', 'PERCENT_HEAL', 'RECOVER_HP_BY_DAMAGE', 'PARASITIC_RECOVERY'},
    'core:energy': {'RECOVER_ATTRIBUTE', 'STEAL_TP', 'MULTI_CONSUME_TP'},
    'core:cooldown': {'SKILL_CD', 'SKILL_CD_MAX'},
    'core:knockback': {'KNOCKBACK', 'KNOCKBACK_SELF', 'HOOK', 'KNOCKBACK_ADD_BUFF'},
    'core:move': {'TELEPORT', 'TARGET_TELEPORT', 'JUMP_MOVE', 'BLINK', 'CHARGE', 'SHADOW_STEP', 'EXCHANGE_POSITION', 'ACTED_MOVE'},
    'core:range': {'SKILL_RANGE', 'EXTEND_CAST_RANGE'},
    'core:area': {'AOE', 'DISPLAY_AOE', 'AOE_EXTEND', 'TARGET_SELECT'},
    'core:swap': {'REPLACE_SKILL', 'GET_EXTRA_SKILL'},
    'core:summon': {'PLACE_UNIT', 'PLACE_UNIT_INHERIT_ATTR'},
    'core:shield': {'PHYSIC_ARMOR', 'SPELL_ARMOR'},
    'core:extra_action': {'ACTED_ACT', 'RE_ROUND'},
    'core:field': {'OPERATION', 'IGNORE_FIELDSTATUS'},
    'core:consume': {'CONSUME_BUFF', 'MULTI_CONSUME_TP', 'REMOVE'},
    'core:limits': {'SKILL_COUNT', 'SPECIALITY_COUNT_TURN', 'GLOBAL_LIMIT_COUNT_COMMAND'},
}

LINK_TYPES = {'CAST_SKILL', 'MAKE_OTHER_CAST_SKILL', 'MAKE_BUFF_SOURCE_CAST_SKILL', 'MAKE_DYNAMIC_CAST_SKILL',
              'MAKE_SUMMONER_CAST_SKILL', 'DELAY_CAST_SKILL', 'DELAY_SKILL', 'FORCE_CAST_SKILL', 'CONDITION_SKILL',
              'ADDITIONAL_ATTACK', 'ASSIST_ATTACK', 'ASSIST_COUNTER_ATTACK', 'COUNTER_ATTACK', 'ALERT_ATTACK',
              'FIRST_HIT', 'REPLACE_SKILL', 'GET_EXTRA_SKILL', 'ABSORB'}
BUFF_TYPES = {'BUFF', 'BUFF_BUNDLE_GAIN', 'BUFF_ADD_REPLACE', 'BUFF_ADD_MODIFY', 'BUFF_TRANSFER'}
ATTR_TYPES = {'MODIFY_ATTRIBUTE', 'PREWAR_MODIFY_ATTRIBUTE', 'BUFF_STACK_MODIFY_ATTRIBUTE', 'BUFF_MODIFY_ATTRIBUTE',
              'CONVERT_ATTRIBUTE', 'SPECIFY_ATTRIBUTE_VALUE', 'HIT_COUNT_MODIFY_ATTRIBUTE', 'DISTANCE_MODIFY_ATTRIBUTE',
              'MOVE_ATTACK', 'RECOVER_ATTRIBUTE'}
# Chinese words a description uses for each client attribute.
ATTR_WORDS = {
    'HP_MAX': ('生命',), 'HP': ('生命',), 'TP': ('能量',), 'TP_MAX': ('能量',),
    'PHYSIC_ATTACK': ('物攻', '物理攻击', '攻击'), 'SPELL_ATTACK': ('魔攻', '魔法攻击', '攻击'),
    'PHYSIC_DEFENCE': ('物防', '物理防御', '防御'), 'SPELL_DEFENCE': ('魔防', '魔法防御', '防御'),
    'ATTACK': ('攻击',), 'DEFENCE': ('防御',), 'PRIMARY_ATTRIBUTES': ('攻防', '主属性', '生命'),
    'SPEED': ('速度',), 'MOBILITY': ('移动',), 'CRIT_RATIO': ('暴击率', '暴击'), 'CRIT_DAMAGE': ('暴击伤害', '暴伤'),
    'DAMAGE': ('伤害',), 'BEDAMAGE': ('受到伤害', '受到的伤害', '免伤'), 'HEAL_FACTOR': ('治疗',),
    'BE_HEAL_FACTOR': ('受到治疗', '受治疗'), 'SKILL_RANGE': ('射程',), 'KNOCKBACK_DISTANCE': ('击退',),
    'RANGE_DAMAGE': ('范围伤害',), 'BE_RANGE_DAMAGE': ('范围伤害',), 'SINGLE_DAMAGE': ('单体',),
    'BE_SINGLE_DAMAGE': ('单体',), 'PHYSIC_DAMAGE': ('物理伤害',), 'SPELL_DAMAGE': ('魔法伤害',),
    'BE_PHYSIC_DAMAGE': ('物理伤害',), 'BE_SPELL_DAMAGE': ('魔法伤害',), 'PIERCE_DAMAGE': ('穿透',),
    'BE_ARMOR_FACTOR': ('护盾',), 'ARMOR_FACTOR': ('护盾',),
}
# Description time phrases -> active_time ids that implement them (client
# active_time enum, verified against data/battle-mech.js timings).
TIMING_WORDS = [
    ('战斗开始', {25}), ('回合开始', {26, 27, 52}), ('行动开始', {27, 52}), ('回合结束', {28, 51}),
    ('行动结束', {28, 51}), ('行动后', {43}), ('待机', {30}), ('攻击前', {2, 33}), ('攻击后', {3, 47}),
    ('被攻击前', {15, 62}), ('被攻击后', {4, 63}), ('受到伤害', {8, 48}), ('造成伤害', {7, 22, 53}),
    ('击败', {11, 21}), ('被击败', {12}), ('暴击', {9, 10}), ('治疗', {17, 18}), ('格挡', {13, 14}),
    ('闪避', {19, 20}), ('反击', {31, 32}), ('援护', {34, 35, 36, 37}), ('协攻', {39, 40}),
    ('不屈', {44}), ('使用技能后', {47}), ('获得', {58}), ('移除', {65}),
]
# Rows that are plumbing, never stated in prose (AI / preview / range shape).
NON_DESCRIBED = {'AOE', 'DISPLAY_AOE', 'FORCE_STOP', 'IGNORE_FORCE_STOP', 'CONVERT_ANIM', 'FORCE_INITIATIVE',
                 'IGNORE_HP_ATTENUATION', 'GLOBAL_LIMIT_COUNT_COMMAND', 'TARGET_SELECT', 'SKILL_GROUP'}
# Client types with no battle effect (animation / UI / sound only).
# STRAIGHT 「直行」 only exists on a test buff and the scripted 逆塔「战车」BOSS
# path animation; it does not change any rule the auto-battle observes.
VISUAL_TYPES = {'CONVERT_ANIM', 'PLAY_EFFECT', 'PLAY_SOUND', 'SHOW_TIPS', 'CAMERA', 'ANIM', 'BUBBLE', 'STRAIGHT'}
# Compound sparam keys that only drive animation / skill preview UI, or whose
# every client row uses the engine's default value (aoe_multiple: all false).
VISUAL_SJ = {'idle', 'is_preview', 'hide_preview', 'teleport', 'not_wait_end'}
DEFAULT_SJ = {'aoe_multiple'}
# Keys with NO engine reader, individually audited against the 192-game sweep
# (work/_gap65.cjs + targeted probes). Each entry records WHY no handler is
# needed: either zero dispatches by cup units, or the existing logic is already
# equivalent. Honest provenance beats a bare "未实装" label in the wiki.
#   key: (fires in sweep, verdict text)
AUDITED_SJ = {
    'no_large_center_bias': (126, '5 行全属大维齐尔「以血筑国」后续召唤链（CAST_SKILL → aim=ground）。'
                                 '客户端 sparam_name 写的是「AOE多重释放|优先级|是否预览」，键名是编辑器遗留字段；'
                                 '引擎选格本就没有「大范围中心偏好」，该声明等价于默认行为。'),
    'trap': (115, 'sj.trap=[177,178] 是芬恩冰寒/爆裂地刺的同组 id 列表。全量 115 次放置中，'
                  '按组计数与按单 id 计数完全一致（场上从未同时出现 177 与 178）；'
                  '现有 complete_cast_limit 同屏上限已等价。'),
    'cast_on_leave': (55, '3 行 MAKE_BUFF_SOURCE_CAST_SKILL「被攻击时找全场本体释放技能」。'
                          '插桩核对全量 55 次派发，本体均存活，subCast() 的 caster.alive 检查零丢弃；'
                          '客户端语义（离场时仍施放）在赛事中无触发场景。'),
    'find_trap': (7, '已实装：BLINK 按 id 找枪灵陷阱并落在其上，结算停留触发。'),
}
NEVER_FIRED_SJ = {
    'force', 'exclusive', 'allow_zero_tp', 'row_push_pull', 'damage_buffer_num',
    'exclude_count_restore', 'exclude_turn_count_restore', 'buff_id',
    'direction_knockback', 'absolute_height_limit', 'direction_line',
}

# ▲ is a buff-level marker INSIDE a bracket ([▲物防2][▲魔防2]), not a
# bullet — splitting on it produced fragments like "[" / "▲物防2][".
SPLIT = re.compile(r'(?<=[。；;])|\n+|(?=[•◆●■])')
BRACKET = re.compile(r'[\[【]\s*([^\[\]【】]{1,24}?)\s*[\]】]')
NUMBER = re.compile(r'(\d+(?:\.\d+)?)')


def split_sentences(desc: str) -> list[str]:
    text = clean(desc).replace('\\n', '\n')
    parts = [p.strip(' ，,') for p in SPLIT.split(text) if p and p.strip(' ，,。；;')]
    out = []
    for p in parts:
        # A bare category prefix 「（物理伤害）」 belongs to the next sentence.
        if out and re.fullmatch(r'[（(][^）)]{1,8}[）)]', out[-1]):
            out[-1] = out[-1] + p
        # A short tail with no sentence-ending punctuation is the remainder of
        # the previous sentence (source data can end mid-sentence, e.g.
        # 「…；并获得」). Keep it attached instead of showing a bare fragment.
        elif (out and len(p) <= 5 and not re.search(r'[。；;！!？?]$', p)
              and not re.fullmatch(r'[\[【][^\[\]【】]{1,24}[\]】]', p)):
            out[-1] = out[-1] + p
        else:
            out.append(p)
    return out


def bigrams(s: str) -> set[str]:
    s = norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


class Builder:
    def __init__(self):
        self.M = load_js('battle-mech.js', 'WIKI_BATTLE_MECH')
        self.D = load_js('battle-sim.js', 'WIKI_BATTLE_SIM')
        try:
            self.cup = load_js('match-cup.js', 'WIKI_MATCH_CUP')
        except (OSError, ValueError):
            self.cup = {'teams': []}
        try:
            self.SM = load_js('skill-mechanics.js', 'WIKI_SKILL_MECHANICS')
        except (OSError, ValueError):
            self.SM = {'skills': {}}
        self.ix = EngineIndex()
        self.skills = {str(k): dict(v) for k, v in self.M['skills'].items()}
        # battle-mech.js keeps only the first 120 chars of each skill
        # description (runtime bundle size). The sentence wiki must cover
        # EVERY sentence, so prefer the full build-time text when available.
        try:
            full = load_js('skill-desc-full.js', 'WIKI_SKILL_DESC_FULL')
        except (OSError, ValueError):
            full = {}
            print('警告：缺少 data/skill-desc-full.js，逐句索引将退回到 120 字截断的描述；'
                  '请先运行 scripts/extract_battle_mechanics.py', flush=True)
        self.full_desc_count = 0
        for sid, text in (full or {}).items():
            if sid in self.skills and text:
                self.skills[sid]['desc'] = clean(text)
                self.skills[sid]['descTruncated'] = False
                self.full_desc_count += 1
        for sk in self.skills.values():
            if len(sk.get('desc') or '') >= 120 and 'descTruncated' not in sk:
                sk['descTruncated'] = True
        self.specs = {str(k): v for k, v in self.M['specs'].items()}
        self.buffs = {str(k): v for k, v in self.M['buffs'].items()}
        self.timings = {int(k): v for k, v in (self.M.get('timings') or {}).items()}
        self.spec_type_rows = {r.get('type'): r for r in table('speciality_type')}
        self.attr_rows = {r.get('type'): r for r in table('attribute_type')}
        self.attr_by_id = {num(r.get('id')): r.get('type') for r in table('attribute_type')}
        self.effect_rows = {r.get('type'): r for r in table('buff_effect_type')}
        self.buff_by_name = defaultdict(list)
        for bid, b in self.buffs.items():
            self.buff_by_name[norm(b.get('n'))].append(bid)
        self.skill_by_name = defaultdict(list)
        for sid, s in self.skills.items():
            self.skill_by_name[norm(s.get('n'))].append(sid)
        # Parameter displays already decoded by extract_battle_rules.py.
        self.param_display = {}
        for sk in (self.SM.get('skills') or {}).values():
            for step in sk.get('chain') or []:
                if step.get('id') is not None and step.get('params'):
                    self.param_display[str(step['id'])] = step['params']
        self.common: dict[str, dict] = {}
        self.out_specs: dict[str, dict] = {}
        self.out_buffs: dict[str, dict] = {}
        self.usage = Counter()

    # ---- common catalog ---------------------------------------------------
    def common_ref(self, cid: str) -> str:
        if cid in self.common:
            return cid
        kind, _, key = cid.partition(':')
        ix = self.ix
        entry = {'label': key, 'cat': kind, 'doc': '', 'anchors': []}
        if kind == 'type':
            row = self.spec_type_rows.get(key) or {}
            entry['label'] = f"{row.get('name') or key}（{key}）"
            names = [row.get(f'param{i}_name') for i in range(4)]
            entry['client'] = {'speciality_type': num(row.get('id')), 'params': names,
                               'sparam': row.get('sparam_name') or ''}
            lines = []
            h = ix.handlers.get(key)
            stub = ix.handler_is_stub(key) if h else True
            readers = ix.handler_readers(key) if h else []
            if h:
                entry['anchors'].append(ix.anchor(h, '声明型占位（由下方读取点生效）' if stub else '效果处理器 EFFECTS.' + key))
            for no in readers:
                lines.append(no)
                entry['anchors'].append(ix.anchor(no, '声明的读取函数', 0, 8))
            for no in spread(ix.consumers.get(key, []), ix, 4):
                if no in lines:
                    continue
                lines.append(no)
                entry['anchors'].append(ix.anchor(no, '读取/派发点'))
            note = ix.comment_before(h) if h else ''
            entry['doc'] = note
            body = '\n'.join(ix.lines[h - 1:ix.handler_end.get(key, h)]) if h else ''
            if 'animation only' in body or key in VISUAL_TYPES:
                entry['impl'] = 'visual'
            elif key in ix.static_types or stub:
                entry['impl'] = 'decl' if lines else ('stub' if h else 'missing')
            else:
                entry['impl'] = 'impl'
            if not h and not lines:
                entry['impl'] = 'missing'
        elif kind == 'at':
            at = int(key)
            meta = self.timings.get(at) or {}
            entry['label'] = f"{meta.get('label') or ('时点 ' + key)}（active_time {at}）"
            sites = ix.timings.get(at, [])
            for no in spread(sites, ix, 5):
                entry['anchors'].append(ix.anchor(no, '派发 fire(' + key + ')', 1, 3))
            if at == 1:
                for sym, role in (('attr', '属性型常驻特技在 attr() 中结算'),
                                  ('refreshAuras', '光环特技由 refreshAuras() 授予'),
                                  ('runSkillSpecs', '技能自带 at=1 特技随施放结算')):
                    no = ix.first_def(sym)
                    if no:
                        entry['anchors'].append(ix.anchor(no, role, 0, 4))
            entry['impl'] = 'impl' if (sites or at == 1) else 'missing'
            entry['doc'] = '客户端 active_time 时点：特技只在该时点被派发，fire() 收集持有者全部特技（含状态带来的特技），按 sparam.priority 与声明顺序依次结算。'
        elif kind == 'attr':
            row = self.attr_rows.get(key) or {}
            entry['label'] = f"{row.get('name') or key}（{key}）"
            for no in spread(ix.attrs.get(key, []), ix, 3):
                entry['anchors'].append(ix.anchor(no, '读取属性', 1, 3))
            no = ix.first_def('attr')
            if no:
                entry['anchors'].append(ix.anchor(no, '属性汇总 attr()：基础值 + 常驻/状态/光环修正', 0, 6))
            entry['impl'] = 'impl'
            entry['doc'] = '属性由 attr() 汇总：基础值、MODIFY_ATTRIBUTE / CONVERT_ATTRIBUTE / 光环（同类取最高）与条件型修正逐项累加。'
        elif kind == 'eff':
            row = self.effect_rows.get(key) or {}
            entry['label'] = f"{row.get('name') or key}（{key}）"
            for no in spread(ix.effects.get(key, []), ix, 4):
                entry['anchors'].append(ix.anchor(no, '状态效果判定', 1, 3))
            entry['impl'] = 'impl' if entry['anchors'] else 'tag'
            entry['doc'] = '状态的 buff_effect_type：控制类（晕眩/冰冻/封技…）在行动/施放前判定，其余作为条件与驱散/免疫的分类标签。'
        elif kind == 'lua':
            for no in spread(ix.lua.get(key, []), ix, 3):
                entry['anchors'].append(ix.anchor(no, 'Lua API 实现', 0, 4))
            entry['label'] = f'Lua：{key}'
            entry['impl'] = 'impl' if entry['anchors'] else 'missing'
            entry['doc'] = '客户端 Lua 条件/动态参数里调用的 API，由引擎内置解释器提供同名实现。'
        elif kind == 'sj':
            for no in spread(ix.sj.get(key, []), ix, 3):
                entry['anchors'].append(ix.anchor(no, '复合参数读取', 1, 4))
            entry['label'] = f'复合参数 sparam.{key}'
            entry['impl'] = ('impl' if entry['anchors'] else
                             'visual' if key in VISUAL_SJ else
                             'tag' if key in DEFAULT_SJ else
                             'audited' if (key in AUDITED_SJ or key in NEVER_FIRED_SJ) else 'missing')
            if entry['anchors']:
                entry['doc'] = ('客户端特技的 JSON 复合参数，导出为 spec.sj，由对应处理器读取。' +
                                (' ' + AUDITED_SJ[key][1] if key in AUDITED_SJ else ''))
            elif key in VISUAL_SJ:
                entry['doc'] = '只影响动画 / 技能预览表现，不改变战斗结算。'
            elif key in DEFAULT_SJ:
                entry['doc'] = '客户端所有行都取默认值，与引擎默认行为一致。'
            elif key in AUDITED_SJ:
                fires, verdict = AUDITED_SJ[key]
                entry['doc'] = f'【已核实·192 场全量扫描 {fires} 次派发】{verdict}'
            elif key in NEVER_FIRED_SJ:
                entry['doc'] = ('【已核实·192 场全量扫描 0 次派发】持有该参数的特技未被赛事单位携带，'
                                '自动对局无需实现；保留条目供客户端数据核对。')
            else:
                entry['doc'] = '客户端特技的 JSON 复合参数，自动对局尚未读取。'
        elif kind == 'core':
            label, cat, symbols, doc = CORE[key]
            entry.update(label=label, cat='core', group=cat, doc=doc, impl='impl')
            for sym in symbols:
                no = ix.first_def(sym.replace('function ', '').rstrip('(')) if sym.startswith('function ') else ix.find(sym)
                if no:
                    entry['anchors'].append(ix.anchor(no, sym.replace('function ', '').rstrip('(') + '()' if sym.startswith('function ') else '相关实现', 0, 6))
        elif kind == 'id':
            for no in ix.ids.get(int(key), [])[:4]:
                entry['anchors'].append(ix.anchor(no, '专属处理（引擎按 id 识别）', 2, 4))
            entry['label'] = f'#{key} 专属处理'
            entry['impl'] = 'impl'
            entry['doc'] = '引擎为该技能/特技/状态编写的专属逻辑或修正说明。'
        elif kind == 'note':
            notes = {
                'narrative': ('描述性文字（无结算逻辑）', '说明',
                              '这一句是角色背景、名称注释或 UI 提示，客户端没有对应的特技行，'
                              '自动对局也没有需要执行的逻辑；逐句索引仍保留它，避免与上下文断句错位。'),
                'source': ('客户端原文被截断', '说明',
                           '客户端 skill.desc 在本句结束前就到头了（原表即如此）。'
                           '逐句索引保留残句并标注，不臆造未导出的机制。'),
            }
            label, cat, doc = notes.get(key, notes['narrative'])
            entry.update(label=label, cat='note', group=cat, impl='note', doc=doc)
        self.common[cid] = entry
        return cid

    # ---- params -----------------------------------------------------------
    def param_text(self, sid: str, spec: dict) -> str:
        shown = self.param_display.get(sid)
        if shown:
            bits = []
            for p in shown:
                val = p.get('display') or p.get('value')
                if val in (None, '', 0, '0'):
                    continue
                bits.append(f"{p.get('name') or '参数'} {val}")
            if bits:
                return '，'.join(bits)
        row = self.spec_type_rows.get(spec.get('t')) or {}
        bits = []
        for i, v in enumerate(spec.get('p') or []):
            if not v:
                continue
            name = row.get(f'param{i}_name') or f'p{i}'
            kind = row.get(f'param{i}_type') or ''
            if kind == 'buff' and str(v) in self.buffs:
                val = '[' + clean(self.buffs[str(v)].get('n')) + ']'
            elif kind == 'skill' and str(v) in self.skills:
                val = '「' + clean(self.skills[str(v)].get('n')) + '」'
            elif kind in ('attribute', 'attr') and v in self.attr_by_id:
                at = self.attr_by_id[v]
                val = (self.attr_rows.get(at) or {}).get('name') or at
            elif kind == 'bool':
                val = '是'
            else:
                val = str(v)
            bits.append(f'{name} {val}')
        if spec.get('s') and not spec.get('sj'):
            bits.append(f"{row.get('sparam_name') or 'sparam'} {str(spec['s'])[:40]}")
        for k, v in (spec.get('sj') or {}).items():
            bits.append(f'{k}={json.dumps(v, ensure_ascii=False)}')
        return '，'.join(bits)

    # ---- specs ------------------------------------------------------------
    def spec_entry(self, sid: str, depth: int = 0) -> str | None:
        sid = str(sid)
        spec = self.specs.get(sid)
        if not spec:
            return None
        if sid in self.out_specs:
            return sid
        t, at = spec.get('t'), num(spec.get('at'))
        refs = [self.common_ref('type:' + t), self.common_ref(f'at:{at}')]
        status = self.common[refs[0]].get('impl')
        if self.common[refs[1]].get('impl') == 'missing':
            status = 'timing-missing'
        cond = spec.get('c') or ''
        if cond:
            refs.append(self.common_ref('core:condition'))
            for name in sorted(set(re.findall(r'[:.]\s*([A-Za-z_]\w*)\s*\(', cond)) |
                               set(re.findall(r'\.(temp_\w+|isCurrentSummoned|isSummoned|changed_buffs)\b', cond))):
                if name in ('format', 'floor', 'ceil', 'min', 'max', 'insert', 'remove'):
                    continue
                ref = self.common_ref('lua:' + name)
                if ref not in refs:
                    refs.append(ref)
        if spec.get('dp'):
            refs.append(self.common_ref('core:dynamic'))
        if spec.get('lt') or spec.get('lc') or spec.get('lcc') or spec.get('lcpec') or spec.get('lcpet'):
            refs.append(self.common_ref('core:limits'))
        for key in (spec.get('sj') or {}):
            refs.append(self.common_ref('sj:' + key))
        if int(sid) in self.ix.ids:
            refs.append(self.common_ref('id:' + sid))
        timing = (self.timings.get(at) or {}).get('label') or f'时点{at}'
        tname = (self.spec_type_rows.get(t) or {}).get('name') or t
        params = self.param_text(sid, spec)
        entry = {'t': t, 'at': at, 'p': spec.get('p'), 'n': clean(spec.get('n'))[:80],
                 'text': f'【{timing}】{tname}' + (f'：{params}' if params else ''),
                 'refs': list(dict.fromkeys(refs)), 'st': status}
        if cond:
            entry['c'] = cond.strip()[:400]
        if spec.get('dp'):
            entry['dp'] = str(spec['dp']).strip()[:300]
        self.out_specs[sid] = entry
        self.usage[t] += 1
        kids = []
        if depth < 2:
            p0 = (spec.get('p') or [0])[0]
            if t in BUFF_TYPES:
                ids = [p0] if p0 else []
                ids += [num(x) for x in re.split(r'[|,]', str(spec.get('s') or '')) if num(x)]
                for bid in ids[:6]:
                    b = self.buff_entry(str(bid), depth + 1)
                    if b:
                        entry.setdefault('buffs', []).append(b)
            if t in LINK_TYPES and str(p0) in self.skills:
                entry['link'] = str(p0)
                for ksid in (self.skills[str(p0)].get('sp') or [])[:10]:
                    if self.spec_entry(str(ksid), depth + 1):
                        kids.append(str(ksid))
        if kids:
            entry['kids'] = kids
        return sid

    def buff_entry(self, bid: str, depth: int) -> str | None:
        b = self.buffs.get(bid)
        if not b:
            return None
        if bid in self.out_buffs:
            return bid
        entry = {'n': clean(b.get('n')), 'd': clean(b.get('d'))[:160], 'sp': [], 'refs': [self.common_ref('core:buff')]}
        if b.get('et'):
            entry['et'] = b['et']
            entry['refs'].append(self.common_ref('eff:' + b['et']))
        if int(bid) in self.ix.ids:
            entry['refs'].append(self.common_ref('id:' + bid))
        self.out_buffs[bid] = entry
        for sid in (b.get('sp') or [])[:10]:
            if self.spec_entry(str(sid), depth):
                entry['sp'].append(str(sid))
        return bid

    # ---- sentences --------------------------------------------------------
    def score(self, sentence: str, sent_bg: set, sent_nums: set, sent_terms: set,
              sent_hints: set, spec: dict) -> float:
        s = 0.0
        name = clean(spec.get('n'))
        # Editor names start with "[角色]-技能-…"; only the tail describes it.
        tail = name.split('-')[-1] if '-' in name else name
        bg = bigrams(tail)
        if bg:
            s += 6.0 * len(bg & sent_bg) / max(4, len(bg))
        t = spec.get('t')
        p = spec.get('p') or []
        if t in BUFF_TYPES and p and str(p[0]) in self.buffs:
            bname = norm(self.buffs[str(p[0])].get('n'))
            if bname in sent_terms:
                s += 5
            elif bname and len(bname) >= 2 and bname in norm(sentence):
                s += 3
            else:
                # The sentence often paraphrases the buff's own description
                # (「受到伤害降低10%」) instead of naming it.
                dbg = bigrams(self.buffs[str(p[0])].get('d') or '')
                if dbg:
                    s += 4.0 * len(dbg & sent_bg) / max(6, len(dbg))
        if t in LINK_TYPES and p and str(p[0]) in self.skills:
            linked = self.skills[str(p[0])]
            if norm(linked.get('n')) in sent_terms:
                s += 5
            else:
                dbg = bigrams(linked.get('desc') or '')
                if dbg:
                    s += 4.0 * len(dbg & sent_bg) / max(6, len(dbg))
        # DISPEL / REMOVE_BUFF / IMMUNE / BUFF_ADD_MODIFY name their buff in p0/p2.
        for v in p[:3]:
            if str(v) in self.buffs and t not in BUFF_TYPES:
                bname = norm(self.buffs[str(v)].get('n'))
                if bname and (bname in sent_terms or (len(bname) >= 2 and bname in norm(sentence))):
                    s += 4
                    break
        if t in ATTR_TYPES and p:
            aid = p[1] if t in ('BUFF_STACK_MODIFY_ATTRIBUTE', 'BUFF_MODIFY_ATTRIBUTE', 'CONVERT_ATTRIBUTE') else p[0]
            words = ATTR_WORDS.get(self.attr_by_id.get(num(aid)), ())
            if any(w in sentence for w in words):
                s += 2.5
        label = (self.timings.get(num(spec.get('at'))) or {}).get('label') or ''
        if label and label not in ('任意',) and label[:3] in sentence:
            s += 2
        for word, ats in TIMING_WORDS:
            if word in sentence and num(spec.get('at')) in ats:
                s += 1.5
                break
        for ref, types in TYPE_HINTS.items():
            if ref in sent_hints and t in types:
                s += 1.5
                break
        if 'type:' + str(t) in sent_hints:
            s += 2
        for v in p[1:]:
            if v and str(abs(v)) in sent_nums:
                s += 0.8
        return s

    def map_skill(self, sid: str) -> dict | None:
        sk = self.skills.get(sid)
        if not sk:
            return None
        desc = sk.get('desc') or ''
        sentences = split_sentences(desc) if desc else []
        feats = []
        for text in sentences:
            terms = {norm(x) for x in BRACKET.findall(text)}
            hints = {ref for rx, ref in KEYWORD_RE if rx.search(text)}
            feats.append((text, bigrams(text), set(NUMBER.findall(text)), terms, hints))
        rows = [{'t': f[0], 's': [], 'b': [], 'k': [], 'c': []} for f in feats]
        extra = []
        for spid in sk.get('sp') or []:
            spid = str(spid)
            spec = self.specs.get(spid)
            if not spec or not self.spec_entry(spid):
                continue
            best, best_i = 0.0, -1
            for i, f in enumerate(feats):
                sc = self.score(f[0], f[1], f[2], f[3], f[4], spec)
                if sc > best:
                    best, best_i = sc, i
            if best_i >= 0 and best >= 1.5:
                rows[best_i]['s'].append(spid)
            elif len(feats) == 1 and self.specs[spid].get('t') not in NON_DESCRIBED:
                # A one-sentence description states the whole skill; every
                # effect row belongs to it.
                rows[0]['s'].append(spid)
            else:
                extra.append(spid)
        for i, f in enumerate(feats):
            text, _bg, _nums, terms, hints = f
            for term in terms:
                for bid in self.buff_by_name.get(term, [])[:1]:
                    if self.buff_entry(bid, 1) and bid not in rows[i]['b']:
                        rows[i]['b'].append(bid)
                for ksid in self.skill_by_name.get(term, [])[:1]:
                    if ksid != sid and ksid not in rows[i]['k']:
                        rows[i]['k'].append(ksid)
            for ref in sorted(hints):
                rows[i]['c'].append(self.common_ref(ref))
        # Skill-intrinsic facts attach to the sentence that states them.
        intrinsic = []
        if sk.get('dt') in (1, 2, 4) or sk.get('dmg'):
            intrinsic.append('core:pierce' if sk.get('dt') == 4 else 'core:damage')
        if sk.get('dt') == 3:
            intrinsic.append('core:heal')
        if (sk.get('desc') or '').lstrip('（(').startswith(('物理伤害', '魔法伤害', '穿透伤害', '支援', '治疗')) and '瞬发' in desc[:20]:
            intrinsic.append('core:instant')
        for ref in intrinsic:
            ref = self.common_ref(ref)
            if rows and not any(ref in r['c'] for r in rows):
                rows[0]['c'].append(ref)
        if int(sid) in self.ix.ids and rows:
            rows[0]['c'].append(self.common_ref('id:' + sid))
        # Every sentence must resolve to SOMETHING traceable. Sentences that
        # matched no speciality / buff / keyword still state a real mechanic —
        # an attribute modifier, a trigger timing or a usage cap — or are pure
        # flavour text. Classify them explicitly instead of leaving a blank row.
        for r in rows:
            if r['s'] or r['b'] or r['k'] or r['c']:
                continue
            text = r['t']
            refs = []
            for rx, attr in ATTR_SENTENCE:
                if rx.search(text):
                    refs.append('attr:' + attr)
                    break
            if not refs:
                for rx, at in TIMING_SENTENCE:
                    if rx.search(text):
                        refs.append('at:' + str(at))
                        break
            if not refs and USAGE_SENTENCE.search(text):
                refs.append('core:limits')
            if not refs and len(text) >= 8 and not re.search(r'\d|提高|增加|获得|造成|触发|使用|变为|存在', text):
                refs.append('note:narrative')
            if not refs:
                refs.append('note:narrative')
            for ref in refs:
                r['c'].append(self.common_ref(ref))
        for r in rows:
            for key in ('s', 'b', 'k', 'c'):
                if not r[key]:
                    del r[key]
        return {'n': clean(sk.get('n')), 'd': clean(desc), 's': rows, **({'x': extra} if extra else {})}

    # ---- skill universe ---------------------------------------------------
    def roster_kits(self):
        out = []
        for r in self.D.get('roster', []):
            out.append((r.get('name'), r.get('pageId') or 0, r.get('kit') or {}))
        for t in self.cup.get('teams', []):
            for m in t.get('members', []):
                out.append((m.get('name'), 0, m.get('kit') or {}))
        return out

    @staticmethod
    def kit_ids(kit):
        ids = [kit.get('basic')]
        for k in ('actives', 'initial', 'reactive', 'leader', 'feature', 'personality', 'chain',
                  'bossSequence', 'choice', 'derived', 'eliteComp', 'module'):
            ids += list(kit.get(k) or [])
        ids += [x[2] for x in kit.get('ranks') or [] if len(x) > 2]
        return [str(x) for x in ids if x]

    def closure(self, ids):
        seen, stack = set(), list(ids)
        while stack:
            sid = str(stack.pop())
            if sid in seen or sid not in self.skills:
                continue
            seen.add(sid)
            for spid in self.skills[sid].get('sp') or []:
                spec = self.specs.get(str(spid))
                if not spec:
                    continue
                p0 = (spec.get('p') or [0])[0]
                if spec.get('t') in LINK_TYPES and str(p0) in self.skills:
                    stack.append(str(p0))
                if spec.get('t') in BUFF_TYPES and str(p0) in self.buffs:
                    for bsp in self.buffs[str(p0)].get('sp') or []:
                        bspec = self.specs.get(str(bsp)) or {}
                        q0 = (bspec.get('p') or [0])[0]
                        if bspec.get('t') in LINK_TYPES and str(q0) in self.skills:
                            stack.append(str(q0))
            for key in ('fl', 'scid', 'ovid'):
                if self.skills[sid].get(key):
                    stack.append(str(self.skills[sid][key]))
        return seen

    def personalities(self):
        rows = defaultdict(list)
        for r in table('unit_personality_skill'):
            rows[num(r.get('idunit_personality'))].append(r)
        names = {num(r.get('id')): r.get('name') for r in table('unit_personality')}
        out = {}
        for pid, items in rows.items():
            stars = {}
            for star in range(1, 6):
                best = {}
                for r in items:
                    if num(r.get('star')) > star:
                        continue
                    g = num(r.get('skill_group_id'))
                    if g not in best or num(r.get('star')) > num(best[g].get('star')):
                        best[g] = r
                stars[star] = [str(num(best[g].get('skill_id'))) for g in sorted(best) if num(best[g].get('skill_id'))]
            out[str(pid)] = {'n': names.get(pid) or '', 'stars': stars}
        return out

    def page_skill_ids(self):
        ids = set()
        for f in (ROOT / 'data' / 'pages').glob('1*.js'):
            text = f.read_text('utf8')
            m = re.search(r'"clientSource":\{[^}]*"table":"skill","rowId":(\d+)', text)
            if m:
                ids.add(m.group(1))
        return ids

    # ---- run --------------------------------------------------------------
    def run(self):
        kits = self.roster_kits()
        roster_ids = set()
        for _n, _p, kit in kits:
            roster_ids |= self.closure(self.kit_ids(kit))
        pers = self.personalities()
        pers_ids = {sid for p in pers.values() for ids in p['stars'].values() for sid in ids}
        universe = roster_ids | self.closure(pers_ids) | self.closure(self.page_skill_ids())
        universe |= {str(k) for k in (self.SM.get('skills') or {})}
        universe = {sid for sid in universe if sid in self.skills and self.skills[sid].get('desc')}
        out_skills = {}
        for sid in sorted(universe, key=int):
            item = self.map_skill(sid)
            if item and item['s']:
                out_skills[sid] = item
        used_pers = {k: v for k, v in pers.items() if any(any(s in out_skills for s in ids) for ids in v['stars'].values())}
        # Always ensure the core catalog is complete for the browser.
        for key in CORE:
            self.common_ref('core:' + key)
        return out_skills, used_pers, roster_ids

    def stats(self, out_skills, roster_ids):
        sent = sum(len(v['s']) for v in out_skills.values())
        mapped = sum(1 for v in out_skills.values() for r in v['s'] if r.get('s') or r.get('b') or r.get('k') or r.get('c'))
        with_spec = sum(1 for v in out_skills.values() for r in v['s'] if r.get('s'))
        gaps = Counter()
        gap_specs = defaultdict(list)
        roster_specs = set()
        for sid in roster_ids:
            for spid in (self.skills.get(sid) or {}).get('sp') or []:
                roster_specs.add(str(spid))
        for spid, e in self.out_specs.items():
            if e['st'] in ('missing', 'stub', 'timing-missing'):
                key = (e['st'], e['t'], e['at'] if e['st'] == 'timing-missing' else '')
                gaps[key] += 1
                if spid in roster_specs and len(gap_specs[key]) < 4:
                    gap_specs[key].append(spid)
        lua_missing = sorted(k[4:] for k, v in self.common.items() if k.startswith('lua:') and v.get('impl') == 'missing')
        return {'skills': len(out_skills), 'sentences': sent, 'mapped': mapped, 'withSpec': with_spec,
                'specs': len(self.out_specs), 'buffs': len(self.out_buffs), 'common': len(self.common),
                'anchors': sum(len(v['anchors']) for v in self.common.values()),
                'gaps': [{'status': k[0], 'type': k[1], 'at': k[2], 'count': n, 'rosterSamples': gap_specs[k]}
                         for k, n in gaps.most_common(60)],
                'luaMissing': lua_missing}


def write_js(path: Path, var: str, payload, header: str):
    path.write_text(header + f'window.{var}=' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + ';\n', 'utf8')


SHARDS = 64
SHARD_DIR = ROOT / 'data' / 'sentence-mechanics'


def shard_of(skill_id) -> int:
    return int(skill_id) % SHARDS


def closure_specs(b: 'Builder', skill: dict) -> tuple[set, set]:
    """Spec + buff ids one skill's page needs (sentences, extra rows, nested
    buff / linked-skill rows), so each shard is self-contained."""
    specs, buffs = set(), set()
    stack = [x for r in skill['s'] for x in r.get('s', [])] + list(skill.get('x', []))
    bstack = [x for r in skill['s'] for x in r.get('b', [])]
    while stack or bstack:
        while stack:
            sid = stack.pop()
            if sid in specs or sid not in b.out_specs:
                continue
            specs.add(sid)
            e = b.out_specs[sid]
            stack += e.get('kids', [])
            bstack += e.get('buffs', [])
        while bstack:
            bid = bstack.pop()
            if bid in buffs or bid not in b.out_buffs:
                continue
            buffs.add(bid)
            stack += b.out_buffs[bid].get('sp', [])
    return specs, buffs


def write_shards(b: 'Builder', out_skills: dict, pers: dict, meta: dict) -> int:
    """data/sentence-mechanics/<n>.js — one file per skill-id bucket. A skill
    page loads exactly one shard (~100 KiB) instead of the whole 6 MiB map."""
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    for old in SHARD_DIR.glob('*.js'):
        old.unlink()
    buckets: dict[int, dict] = defaultdict(lambda: {'skills': {}, 'specs': {}, 'buffs': {}})
    for sid, item in out_skills.items():
        bk = buckets[shard_of(sid)]
        bk['skills'][sid] = item
        specs, buffs = closure_specs(b, item)
        for x in specs:
            bk['specs'][x] = b.out_specs[x]
        for x in buffs:
            bk['buffs'][x] = b.out_buffs[x]
    total = 0
    for n, bk in sorted(buckets.items()):
        path = SHARD_DIR / f'{n}.js'
        body = json.dumps(bk, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        path.write_text('/* Generated by scripts/build_sentence_mechanics.py */\n'
                        f'(window.WIKI_SENTENCE_SHARDS=window.WIKI_SENTENCE_SHARDS||{{}})[{n}]={body};\n', 'utf8')
        total += path.stat().st_size
    # Index: which skills exist + personalities (small, always loaded with the shard).
    index = {'v': 1, 'shards': SHARDS, 'meta': meta,
             'skills': sorted(out_skills, key=int), 'personalities': pers}
    write_js(OUT_SENT, 'WIKI_SENTENCE_INDEX', index,
             '/* Generated by scripts/build_sentence_mechanics.py: sentence-mechanism index (shards in data/sentence-mechanics/). */\n')
    return total


def main(argv=None) -> int:
    if not (ROOT / 'data' / 'battle-mech.js').exists():
        print('跳过逐句机制：缺少 data/battle-mech.js')
        return 0
    b = Builder()
    out_skills, pers, roster_ids = b.run()
    st = b.stats(out_skills, roster_ids)
    meta = {k: v for k, v in st.items() if k not in ('gaps', 'luaMissing')}
    meta['engine'] = 'battle-sim-core.js'
    meta['engineLines'] = len(b.ix.lines)
    shard_bytes = write_shards(b, out_skills, pers, meta)
    write_js(OUT_CODE, 'WIKI_MECHANICS_CODE',
             {'v': 1, 'meta': {**meta, 'gaps': st['gaps'], 'luaMissing': st['luaMissing']}, 'common': b.common},
             '/* Generated by scripts/build_sentence_mechanics.py: common mechanisms with engine code anchors. */\n')
    print(f"逐句机制：{st['skills']} 个技能 / {st['sentences']} 句（{st['mapped']} 句已映射，{st['withSpec']} 句命中客户端特技），"
          f"{st['specs']} 条特技、{st['buffs']} 个状态、{st['common']} 个通用机制、{st['anchors']} 处代码锚点 → "
          f"{OUT_SENT.relative_to(ROOT)} ({OUT_SENT.stat().st_size // 1024} KiB) + {SHARDS} 个分片 "
          f"({shard_bytes // 1024} KiB), {OUT_CODE.relative_to(ROOT)} ({OUT_CODE.stat().st_size // 1024} KiB)")
    if '--gaps' in (argv or sys.argv):
        for g in st['gaps'][:40]:
            print('  gap', g)
        print('  lua missing', st['luaMissing'][:60])
    return 0


if __name__ == '__main__':
    sys.exit(main())
