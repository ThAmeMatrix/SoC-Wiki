"""Reviewable local updates with byte-exact backups and guarded rollback."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import uuid

def sha(data):return hashlib.sha256(data).hexdigest()

def within(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()) or path==root.resolve():
        raise ValueError('更新路径超出 Wiki 根目录：'+str(relative))
    return path

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.socdecode-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()

def apply(root: Path, files: dict[str,bytes], expected: dict[str,str|None], backups: Path):
    changed={}
    for name,content in files.items():
        path=within(root,name);before=path.read_bytes() if path.exists() else None
        if (sha(before) if before is not None else None)!=expected[name]:
            raise RuntimeError(f'文件在预览后被修改，请重新生成更新：{name}')
        if before!=content:changed[name]=(before,content)
    if not changed:return None
    folder=backups/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    manifest={'wiki':str(root.resolve()),'status':'prepared','files':[]}
    for name,(before,after) in changed.items():
        if before is not None:atomic(within(folder/'files',name),before)
        manifest['files'].append({'path':name,'before':sha(before) if before is not None else None,'after':sha(after)})
    atomic(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))
    written=[]
    try:
        for name,(before,after) in changed.items():
            path=within(root,name)
            if (sha(path.read_bytes()) if path.exists() else None)!=expected[name]:
                raise RuntimeError(f'检测到并发修改，已停止：{name}')
            atomic(path,after);written.append(name)
    except BaseException:
        for name in reversed(written):
            before,after=changed[name];path=within(root,name)
            if sha(path.read_bytes())!=sha(after):continue
            if before is None:path.unlink()
            else:atomic(path,before)
        manifest['status']='failed-restored'
        atomic(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))
        raise
    manifest['status']='applied'
    atomic(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))
    return folder

def rollback(folder: Path):
    manifest=json.loads((folder/'manifest.json').read_text('utf8'))
    if manifest['status']!='applied':raise ValueError('此备份不处于可回滚状态')
    root=Path(manifest['wiki']);payloads={}
    # Validate the entire operation before touching any destination.
    for item in manifest['files']:
        path=within(root,item['path'])
        if not path.is_file() or sha(path.read_bytes())!=item['after']:
            raise RuntimeError('更新之后文件已发生变化，拒绝覆盖：'+item['path'])
        before=None
        if item['before'] is not None:
            before=within(folder/'files',item['path']).read_bytes()
            if sha(before)!=item['before']:raise ValueError('备份校验失败：'+item['path'])
        payloads[item['path']]=before
    restored=[]
    after_contents={item['path']:within(root,item['path']).read_bytes() for item in manifest['files']}
    try:
        for name,before in payloads.items():
            path=within(root,name)
            if sha(path.read_bytes())!=sha(after_contents[name]):raise RuntimeError('回滚期间文件被修改：'+name)
            if before is None:path.unlink()
            else:atomic(path,before)
            restored.append(name)
    except BaseException:
        for name in reversed(restored):
            path=within(root,name);expected=payloads[name]
            if (path.read_bytes() if path.exists() else None)==expected:atomic(path,after_contents[name])
        raise
    manifest['status']='rolled-back'
    atomic(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))
    return len(payloads)
