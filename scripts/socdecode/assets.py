"""Resolve exact texture names through the client's asset bundle catalog."""
from collections import OrderedDict
from pathlib import Path
import hashlib
import io
import json
import os
import UnityPy
from .client import text_assets, digest, game_root

def _extract_asset(job):
    """Worker for :meth:`Assets.prefetch`: load one bundle and encode one texture.

    Runs in a separate process, so it may only use imports and plain arguments.
    ``bundle_sha`` is computed by the caller, because hashing a large bundle once
    per asset dominates the whole run otherwise.
    Returns ``(name, None)`` when the texture cannot be resolved.
    """
    root, bundle, name, bundle_sha = job
    try:
        import UnityPy as _unity
        path = Path(root) / (bundle + '.unity3d')
        if not path.is_file():
            return (name, None)
        wanted = name.rsplit('/', 1)[-1]
        data = None
        for obj in _unity.load(str(path)).objects:
            if obj.type.name not in ('Texture2D', 'Sprite'):
                continue
            candidate = obj.read()
            if candidate.m_Name == wanted:
                data = candidate
                break
        if data is None:
            return (name, None)
        picture = data.image.convert('RGBA')
        stream = io.BytesIO()
        picture.save(stream, format='WEBP', lossless=True, method=4)
        content = stream.getvalue()
        return (name, bundle, content, picture.width, picture.height,
                bundle_sha, hashlib.sha256(content).hexdigest())
    except Exception:
        return (name, None)

class Assets:
    def __init__(self, game: Path):
        game=game_root(game)
        self.root=game/'assets'
        self.mapping=json.loads(text_assets(self.root/'asset_bundle.unity3d')['asset_bundle'])
        self.cache=OrderedDict();self.files={};self.manifest={};self.missing=[]
        # Wiki root, set by reuse() so reused textures can be read back from disk.
        self.store=None

    def reuse(self, previous, root: Path):
        """Re-use textures an earlier run already extracted.

        Keeps an entry only when its output file still exists *and* the source
        bundle is byte-identical, so a client update invalidates it automatically.
        """
        if not previous:return 0
        self.store=root
        bundle_sha={};kept=0
        for name,info in previous.items():
            if not isinstance(info,dict) or not info.get('path'):continue
            if not (root/info['path']).is_file():continue
            bundle=info.get('bundle')
            if not bundle:continue
            # 清单里存的是相对包路径（已带 .unity3d），旧的映射可能不带后缀。
            source=self.root/(bundle if bundle.endswith('.unity3d') else bundle+'.unity3d')
            if not source.is_file():continue
            if bundle not in bundle_sha:bundle_sha[bundle]=digest(source)
            if bundle_sha[bundle]!=info.get('bundleSha256'):continue
            self.manifest[name]=info;kept+=1
        return kept

    def content(self, relative):
        """Bytes of an already-extracted asset; reused ones are read back from the Wiki."""
        if relative in self.files:return self.files[relative]
        if self.store:
            target=self.store/relative
            if target.is_file():return target.read_bytes()
        return b''

    def prefetch(self, names, workers=None, log=None):
        """Extract several textures in parallel; already-known names are skipped."""
        wanted=[];seen=set()
        for name in names:
            if not name or name in self.manifest or name in seen:continue
            seen.add(name)
            bundle=self.mapping.get(name,name)
            if not isinstance(bundle,str) or '..' in Path(bundle).parts:continue
            wanted.append((bundle,name))
        if not wanted:return 0
        if len(wanted)==1:
            # A single texture is not worth spinning up a worker pool.
            self.get(wanted[0][1])
            return len(self.manifest)
        # Hash each bundle once in the parent: doing it per asset costs minutes.
        bundle_sha={}
        for bundle,_ in wanted:
            if bundle in bundle_sha:continue
            source=self.root/(bundle if bundle.endswith('.unity3d') else bundle+'.unity3d')
            bundle_sha[bundle]=digest(source) if source.is_file() else ''
        jobs=[(str(self.root),bundle,name,bundle_sha[bundle]) for bundle,name in wanted]
        from concurrent.futures import ProcessPoolExecutor
        # 立绘解码很吃内存，进程数刻意保守，避免并行把内存顶满后进程被杀。
        workers=workers or min(4,(os.cpu_count() or 2))
        if log:log(f'  并行提取客户端资源：{len(jobs)} 个，{workers} 个进程')
        done=0
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for name,*rest in pool.map(_extract_asset,jobs,chunksize=1):
                    if rest[0] is None:
                        self.missing.append(name);continue
                    bundle,content,width,height,source_sha,sha=rest
                    relative='assets/client/'+sha[:24]+'.webp'
                    self.files[relative]=content
                    self.manifest[name]={'path':relative,'bundle':bundle,'bundleSha256':source_sha,
                        'sha256':sha,'width':width,'height':height}
                    done+=1
        except Exception:
            # 子进程崩溃（超大贴图或 native 解码失败）时退回顺序提取，结果完全一致。
            if log:log('  并行提取中断，改为顺序提取剩余资源')
            for job in jobs:
                if job[2] not in self.manifest:self.get(job[2])
        return done

    def get(self, name):
        if not name:return ''
        if name in self.manifest:return self.manifest[name]['path']
        bundle=self.mapping.get(name,name)
        if not isinstance(bundle,str) or '..' in Path(bundle).parts:raise ValueError('资源目录索引异常')
        path=self.root/(bundle+'.unity3d')
        if not path.is_file():self.missing.append(name);return ''
        if bundle not in self.cache:
            env=UnityPy.load(str(path));objects={}
            for obj in env.objects:
                if obj.type.name in ('Texture2D','Sprite'):
                    data=obj.read();objects[data.m_Name]=data
            self.cache[bundle]=objects
            if len(self.cache)>3:self.cache.popitem(last=False)
        data=self.cache[bundle].get(name.rsplit('/',1)[-1])
        if data is None:self.missing.append(name);return ''
        picture=data.image.convert('RGBA')
        stream=io.BytesIO();picture.save(stream,format='WEBP',lossless=True,method=4)
        content=stream.getvalue();sha=hashlib.sha256(content).hexdigest()
        relative='assets/client/'+sha[:24]+'.webp'
        self.files[relative]=content
        self.manifest[name]={'path':relative,'bundle':str(path.relative_to(self.root)).replace('\\','/'),
            'bundleSha256':digest(path),'sha256':sha,'width':picture.width,'height':picture.height}
        return relative
