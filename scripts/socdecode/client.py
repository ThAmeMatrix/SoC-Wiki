"""Local Unity TextAsset tables, decoded with the installation's own Lua runtime.

Only configuration bundles are executed, inside a fresh Lua state with filesystem,
process, module loading and network libraries removed. The running game is unused.
No account, player preferences, battle reports, or launcher databases are read.
"""
from __future__ import annotations
import ctypes as C
import hashlib
import json
import platform
from pathlib import Path

import UnityPy

OUTER_KEY = bytes.fromhex('3517f1c355786439404277591233cb7bb9')
TABLE_BUNDLES = ('lua_dbtemplate', 'lua_dbtemplateonline', 'lua_dbtemplateskill', 'lua_dbtemplatespeciality')
TABLES = (
    'online_role', 'online_role_unit', 'unit', 'profession', 'profession_category',
    'unit_model', 'unit_skin', 'unit_tag', 'unit_voice_language', 'unit_rarity',
    'online_role_life_story', 'online_unit_modify_level', 'online_unit_star',
    'online_unit_rank_modify', 'online_unit_rank_modify_rank', 'online_unit_rank_skill_line_modify',
    'unit_personality', 'unit_personality_skill', 'skill', 'buff', 'skill_keyword',
    'weapon_type', 'const_param', 'timestamp', 'target_method', 'range_select',
    'online_module_skill', 'unit_pool_skill',
    'online_weapon', 'online_weapon_modify', 'online_weapon_modify_level', 'online_weapon_rarity',
    'online_weapon_personality', 'online_weapon_personality_skill',
)

def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()

def game_root(path: Path) -> Path:
    for root in (path, path/'SwordOfConvallaria', path/'SoCLauncher/SwordOfConvallaria'):
        if (root/'assets/lua/lua_db.unity3d').is_file() and (root/'SoC_Data/Plugins/x86_64/slua.dll').is_file():
            return root.resolve()
    raise ValueError(f'未找到游戏客户端配置：{path}。请指定 SoCLauncher 或 SwordOfConvallaria 目录。')

def text_assets(path: Path) -> dict[str, bytes]:
    env = UnityPy.load(str(path))
    result = {}
    for obj in env.objects:
        if obj.type.name == 'TextAsset':
            data = obj.read()
            result[data.m_Name] = data.m_Script.encode('utf8', 'surrogateescape')
    return result

def decode_outer(data: bytes) -> bytes:
    result = bytes(value ^ OUTER_KEY[i % len(OUTER_KEY)] for i, value in enumerate(data))
    # Header expected by the local 64-bit XD Lua VM, before its positional XOR.
    if not result.startswith(bytes.fromhex('01584643810513e40018480b')):
        raise ValueError('不支持的客户端 Lua 格式；已停止，未猜测配置内容。')
    return result

BOOTSTRAP = r'''
Database={}; Global={}
class=function() return {} end
require=function(name)
    if name == 'DB/DBTemplateLoaderRead' then return Database.DBTemplateLoader end
    error('Unsupported configuration dependency: '..tostring(name))
end
-- Unit configuration captures references to game classes in post-load closures.
-- They are never called by this reader.
local function reference()
    return setmetatable({}, {__index=function(t,k)
        local v=reference(); rawset(t,k,v); return v
    end})
end
Game=reference()
os=nil; io=nil; package=nil; dofile=nil; loadfile=nil; loadstring=nil; debug=nil
'''
LOADER = r'''
Database.db_loader={Global=Global, data_mt={},
    load_lang_table=function() end,
    getTable=function() return {} end,
    data_post_func=function() end,
    split=function(s,sep)
        local a={} for x in string.gmatch(s,'[^'..(sep or '|')..']+') do a[#a+1]=x end
        return a
    end
}
'''

class LuaTables:
    def __init__(self, dll: Path):
        if platform.system() != 'Windows' or C.sizeof(C.c_void_p) != 8:
            raise RuntimeError('客户端提取需要 Windows 64 位 Python。已导出的 JSON 可在其他平台处理。')
        self.lib = C.CDLL(str(dll))
        p, i, s = C.c_void_p, C.c_int, C.c_char_p
        signatures = {
            'luaL_newstate': ([],p), 'luaL_openlibs': ([p],None), 'lua_close': ([p],None),
            'luaL_loadbuffer': ([p,s,C.c_size_t,s],i), 'lua_pcall': ([p,i,i,i],i),
            'lua_type': ([p,i],i), 'lua_gettop': ([p],i), 'lua_settop': ([p,i],None),
            'lua_tolstring': ([p,i,C.POINTER(C.c_size_t)],p), 'lua_tonumber': ([p,i],C.c_double),
            'lua_toboolean': ([p,i],i), 'lua_pushnil': ([p],None), 'lua_next': ([p,i],i),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.lib,name); fn.argtypes=args; fn.restype=result
            setattr(self,name,fn)
        self.L = self.luaL_newstate()
        if not self.L: raise MemoryError('无法创建 Lua 配置读取器')
        self.luaL_openlibs(self.L)
        self.run(BOOTSTRAP)

    def close(self):
        if self.L: self.lua_close(self.L); self.L=None

    def string(self, index):
        length=C.c_size_t(); ptr=self.lua_tolstring(self.L,index,C.byref(length))
        return C.string_at(ptr,length.value).decode('utf8') if ptr else None

    def value(self, index, depth=0):
        kind=self.lua_type(self.L,index)
        if kind==0:return None
        if kind==1:return bool(self.lua_toboolean(self.L,index))
        if kind==3:
            value=self.lua_tonumber(self.L,index)
            return int(value) if value.is_integer() else value
        if kind==4:return self.string(index)
        if kind==5:
            if depth>8:raise ValueError('配置表嵌套层数异常')
            absolute=index if index>0 else self.lua_gettop(self.L)+index+1
            result={}; self.lua_pushnil(self.L)
            while self.lua_next(self.L,absolute):
                key=self.value(-2,depth+1); result[key]=self.value(-1,depth+1)
                self.lua_settop(self.L,-2)
            return result
        raise ValueError(f'配置导出包含非数据值，Lua type={kind}')

    def run(self, code: str | bytes, name='socdecode', capture=False, assign=False):
        if isinstance(code,str):code=code.encode('utf8')
        top=self.lua_gettop(self.L)
        try:
            error=self.luaL_loadbuffer(self.L,code,len(code),name.encode('utf8'))
            if not error:error=self.lua_pcall(self.L,0,1 if (capture or assign) else 0,0)
            if error:raise ValueError(f'{name}: {self.string(-1)}')
            if capture:return self.value(-1)
            if assign:
                # Set the returned config into a global via the native API; no text eval.
                fn=self.lib.lua_setfield;fn.argtypes=[C.c_void_p,C.c_int,C.c_char_p];fn.restype=None
                fn(self.L,-10002,b'CURRENT_TABLE')
        finally:self.lua_settop(self.L,top)

    def setup(self, scripts):
        self.run(decode_outer(scripts['DBTemplateLoaderRead']), 'DBTemplateLoaderRead')
        for i in range(1,10):
            self.run(decode_outer(scripts[f'db_template{i}']), f'db_template{i}')
        self.schema=self.run('local o={} for k,v in pairs(Database) do if v.param_index then o[k:sub(2)]=v.param_index end end return o',capture=True)
        self.run(LOADER)

    def table(self, name, data):
        if name not in self.schema:raise ValueError(f'配置缺少字段定义：{name}')
        self.run(decode_outer(data),name,assign=True)
        # Resolve column indices from the game's own schema, without invoking
        # relationship postprocessors or deriving meanings from column positions.
        rows=self.run('''
            local result={}
            for _,v in ipairs(CURRENT_TABLE.datas) do
                local row={}
                for key,col in pairs(Database._'''+name+'''.param_index) do
                    if key:sub(1,2) ~= 'm_' then row[key]=rawget(v,col) end
                end
                result[#result+1]=row
            end
            if #result ~= CURRENT_TABLE.data_len then error('Row count mismatch') end
            CURRENT_TABLE=nil
            return result
        ''',capture=True)
        return [row for _,row in sorted(rows.items())]

def extract_tables(game: Path, cache: Path, force=False):
    sources=[game/'assets/lua'/f'{name}.unity3d' for name in ('lua_db',*TABLE_BUNDLES)]
    sources.extend([game/'SoC_Data/Plugins/x86_64/slua.dll',game/'assets/resource_version.unity3d',game/'assets/asset_bundle.unity3d'])
    hashes={str(p.relative_to(game)).replace('\\','/'):digest(p) for p in sources}
    fingerprint=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    folder=cache/fingerprint; manifest=folder/'manifest.json'
    if not force and manifest.exists() and all((folder/f'{name}.json').is_file() for name in TABLES):
        print('使用已校验客户端缓存 '+fingerprint[:12],flush=True)
        return {name:json.loads((folder/f'{name}.json').read_text('utf8')) for name in TABLES},json.loads(manifest.read_text('utf8'))
    vm=LuaTables(game/'SoC_Data/Plugins/x86_64/slua.dll'); result={}
    try:
        vm.setup(text_assets(sources[0]))
        for bundle in TABLE_BUNDLES:
            scripts=text_assets(game/'assets/lua'/f'{bundle}.unity3d')
            for name in TABLES:
                if name in scripts:
                    result[name]=vm.table(name,scripts[name])
                    print(f'读取 {name}: {len(result[name])} 条',flush=True)
        absent=set(TABLES)-result.keys()
        if absent:raise ValueError('客户端缺少必要配置表：'+', '.join(sorted(absent)))
    finally:vm.close()
    version=json.loads(text_assets(game/'assets/resource_version.unity3d')['resource_version'])
    meta={'fingerprint':fingerprint,'version':version,'files':hashes,'tableCounts':{n:len(r) for n,r in result.items()}}
    folder.mkdir(parents=True,exist_ok=True)
    for name,rows in result.items():(folder/f'{name}.json').write_text(json.dumps(rows,ensure_ascii=False,separators=(',',':')),'utf8')
    manifest.write_text(json.dumps(meta,ensure_ascii=False,indent=2),'utf8')
    return result,meta
