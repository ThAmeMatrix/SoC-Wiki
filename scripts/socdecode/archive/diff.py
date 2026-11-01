"""Differences between two archived versions, and inside changed resources."""
from __future__ import annotations

import collections
import difflib
import json

KINDS = ('added', 'removed', 'modified', 'renamed')
KIND_LABELS = {'added': '新增', 'removed': '删除', 'modified': '修改', 'renamed': '改名'}


def compare(old_entries, new_entries, categories=None):
    """Changes as ``(kind, old_entry, new_entry)`` sorted by path.

    Only ``categories`` present in both versions are compared, so a version
    that skipped audio does not look as if every sound was deleted.
    """
    if categories is not None:
        categories = set(categories)
        old_entries = [e for e in old_entries if e[1] in categories]
        new_entries = [e for e in new_entries if e[1] in categories]
    old = {e[0]: e for e in old_entries}
    new = {e[0]: e for e in new_entries}
    added = [e for path, e in new.items() if path not in old]
    removed = [e for path, e in old.items() if path not in new]
    changes = [('modified', old[path], e) for path, e in new.items()
               if path in old and (old[path][3] != e[3] or old[path][5] != e[5])]
    # Same content under a new path is a rename, not a delete plus an add.
    gone = collections.defaultdict(list)
    for entry in removed:
        gone[(entry[3], entry[5], entry[1])].append(entry)
    moved = set()
    for entry in added:
        candidates = gone.get((entry[3], entry[5], entry[1]))
        if candidates:
            previous = candidates.pop()
            moved.add(previous[0])
            moved.add(entry[0])
            changes.append(('renamed', previous, entry))
    changes += [('added', None, e) for e in added if e[0] not in moved]
    changes += [('removed', e, None) for e in removed if e[0] not in moved]
    changes.sort(key=lambda change: (change[2] or change[1])[0])
    return changes


def summarize(changes) -> dict:
    total = collections.Counter()
    categories = {}
    for kind, old, new in changes:
        entry = new or old
        total[kind] += 1
        cat = categories.setdefault(entry[1], {'counts': collections.Counter(), 'groups': {}, 'bytes': 0})
        cat['counts'][kind] += 1
        cat['groups'].setdefault(entry[2], collections.Counter())[kind] += 1
        cat['bytes'] += (new[4] if new else 0) - (old[4] if old else 0)
    return {
        'total': {kind: total.get(kind, 0) for kind in KINDS},
        'changes': sum(total.values()),
        'categories': {key: {'counts': {kind: value['counts'].get(kind, 0) for kind in KINDS},
                             'bytes': value['bytes'],
                             'groups': {group: dict(counter) for group, counter in sorted(value['groups'].items())}}
                       for key, value in sorted(categories.items())},
    }


def compare_sources(old: dict, new: dict) -> dict:
    """Client files that appeared, disappeared or changed (decoded-table markers excluded)."""
    old = {rel: value for rel, value in old.items() if '#' not in rel}
    new = {rel: value for rel, value in new.items() if '#' not in rel}
    added = sorted(rel for rel in new if rel not in old)
    removed = sorted(rel for rel in old if rel not in new)
    modified = sorted(rel for rel in new if rel in old and old[rel][1] != new[rel][1])
    return {'added': added, 'removed': removed, 'modified': modified,
            'counts': {'added': len(added), 'removed': len(removed), 'modified': len(modified)}}


# -- tables ------------------------------------------------------------------

def _key(rows_a, rows_b):
    for column in ('id', 'ID', 'Id', 'key'):
        ok = True
        for rows in (rows_a, rows_b):
            values = [json.dumps(row.get(column), sort_keys=True) if isinstance(row, dict) else None for row in rows]
            if any(v is None or v == 'null' for v in values) or len(set(values)) != len(values):
                ok = False
                break
        if ok:
            return column
    return None


def table_diff(rows_a, rows_b, limit=2000) -> dict:
    """Rows added, removed and changed (field by field) between two tables."""
    rows_a = rows_a if isinstance(rows_a, list) else []
    rows_b = rows_b if isinstance(rows_b, list) else []
    key = _key(rows_a, rows_b) if rows_a and rows_b else None

    def keyed(rows):
        if key:
            return {json.dumps(row.get(key), sort_keys=True, ensure_ascii=False): row for row in rows}
        return {str(index + 1): row for index, row in enumerate(rows)}

    a, b = keyed(rows_a), keyed(rows_b)
    columns_a = list(dict.fromkeys(k for row in rows_a if isinstance(row, dict) for k in row))
    columns_b = list(dict.fromkeys(k for row in rows_b if isinstance(row, dict) for k in row))
    columns = list(dict.fromkeys(([key] if key else []) + columns_b + columns_a))
    added = [b[k] for k in b if k not in a]
    removed = [a[k] for k in a if k not in b]
    changed = []
    for k in b:
        if k in a and a[k] != b[k]:
            left, right = a[k] if isinstance(a[k], dict) else {'值': a[k]}, b[k] if isinstance(b[k], dict) else {'值': b[k]}
            fields = [[column, left.get(column), right.get(column)]
                      for column in dict.fromkeys(list(right) + list(left)) if left.get(column) != right.get(column)]
            changed.append({'key': json.loads(k) if key else int(k), 'fields': fields,
                            'row': right})
    return {
        'key': key, 'columns': columns,
        'addedColumns': [c for c in columns_b if c not in columns_a],
        'removedColumns': [c for c in columns_a if c not in columns_b],
        'counts': {'rowsBefore': len(rows_a), 'rowsAfter': len(rows_b), 'added': len(added),
                   'removed': len(removed), 'changed': len(changed)},
        'added': added[:limit], 'removed': removed[:limit], 'changed': changed[:limit], 'limit': limit,
    }


# -- text --------------------------------------------------------------------

def pretty(text: str, ext: str) -> str:
    """JSON is compared line by line after indenting; everything else as is."""
    if ext == '.json' or text[:1] in '{[':
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    return text


def text_diff(left: str, right: str, context=3, cap=200000) -> dict:
    """Side-by-side rows grouped in hunks: ``t`` is e(qual) d(elete) i(nsert) r(eplace)."""
    a, b = left.splitlines(), right.splitlines()
    truncated = len(a) > cap or len(b) > cap
    a, b = a[:cap], b[:cap]
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=len(a) + len(b) > 4000)
    hunks = []
    added = removed = 0
    for group in matcher.get_grouped_opcodes(context):
        rows = []
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                rows += [{'t': 'e', 'a': i + 1, 'b': j + 1, 'l': a[i], 'r': b[j]} for i, j in zip(range(i1, i2), range(j1, j2))]
                continue
            removed += i2 - i1
            added += j2 - j1
            if tag == 'delete':
                rows += [{'t': 'd', 'a': i + 1, 'b': None, 'l': a[i], 'r': None} for i in range(i1, i2)]
            elif tag == 'insert':
                rows += [{'t': 'i', 'a': None, 'b': j + 1, 'l': None, 'r': b[j]} for j in range(j1, j2)]
            else:
                for n in range(max(i2 - i1, j2 - j1)):
                    i, j = i1 + n, j1 + n
                    rows.append({'t': 'r', 'a': i + 1 if i < i2 else None, 'b': j + 1 if j < j2 else None,
                                 'l': a[i] if i < i2 else None, 'r': b[j] if j < j2 else None})
        first, last = group[0], group[-1]
        hunks.append({'a': [first[1] + 1, last[2]], 'b': [first[3] + 1, last[4]], 'rows': rows})
    return {'hunks': hunks, 'added': added, 'removed': removed, 'linesBefore': len(a), 'linesAfter': len(b),
            'truncated': truncated}


def report(meta: dict, summary: dict, changes, sources: dict, labels: dict, cap=300) -> str:
    """Readable record of one version and what changed since its parent."""
    lines = [f"# 资源版本 {meta['label']}", '',
             f"- 版本号：`{meta['id']}`",
             f"- 游戏资源版本：{meta.get('game', {}).get('changeNumber') or '未知'}",
             f"- 资源总数：{meta['entries']:,}（{meta['bytes'] / 2**20:,.1f} MB）",
             f"- 解析耗时：{meta['durationSeconds']:.1f} 秒",
             f"- 对比版本：{meta.get('parent') or '无（首个版本）'}", '']
    if not meta.get('parent'):
        lines += ['首个版本，全部资源记为新增。', '']
        for key, value in meta['counts'].items():
            lines.append(f"- {labels.get(key, key)}：{value['n']:,} 项")
        return '\n'.join(lines) + '\n'
    total = summary['total']
    lines += [f"共 {summary['changes']:,} 处变化：新增 {total['added']:,} · 修改 {total['modified']:,} · "
              f"删除 {total['removed']:,} · 改名 {total['renamed']:,}", '',
              f"客户端文件：新增 {sources['counts']['added']:,} · 修改 {sources['counts']['modified']:,} · "
              f"删除 {sources['counts']['removed']:,}", '']
    grouped = collections.defaultdict(list)
    for kind, old, new in changes:
        grouped[(new or old)[1]].append((kind, old, new))
    for key, items in grouped.items():
        counts = summary['categories'][key]['counts']
        lines += [f"## {labels.get(key, key)}（{len(items):,}）", '',
                  '新增 {added} · 修改 {modified} · 删除 {removed} · 改名 {renamed}'.format(**counts), '']
        for kind, old, new in items[:cap]:
            if kind == 'renamed':
                lines.append(f"- {KIND_LABELS[kind]} `{old[0]}` → `{new[0]}`")
            else:
                lines.append(f"- {KIND_LABELS[kind]} `{(new or old)[0]}`")
        if len(items) > cap:
            lines.append(f"- ……另有 {len(items) - cap:,} 项，请在资源浏览器中查看")
        lines.append('')
    return '\n'.join(lines) + '\n'
