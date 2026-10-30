"""Resolve exact texture names through the client's asset bundle catalog."""
from collections import OrderedDict
from pathlib import Path
import hashlib
import io
import json
import UnityPy
from .client import text_assets, digest

class Assets:
    def __init__(self, game: Path):
        self.root=game/'assets'
        self.mapping=json.loads(text_assets(self.root/'asset_bundle.unity3d')['asset_bundle'])
        self.cache=OrderedDict();self.files={};self.manifest={};self.missing=[]

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
