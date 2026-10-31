"""Exercise actual offline infographic editing and image exports in Chromium."""
from pathlib import Path
import json
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
BASE=(ROOT/'index.html').as_uri()+'#/tools/infographic'

# A sample picture with alpha for the custom background upload test.
def sample_background():
    path=OUT/'infographic-upload-sample.png'
    image=Image.new('RGBA',(760,1180),(14,34,52,255))
    for y in range(0,1180,6):
        for x in range(0,760,6):image.putpixel((x,y),(36+(x//8)%190,72+(y//12)%150,150,255))
    image.save(path)
    return path

def ready(page):
    page.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920 && !document.querySelector('[data-ig=export]')?.disabled",timeout=60000)
def saved(page,id=9296):return page.evaluate('(id)=>JSON.parse(localStorage.getItem("socwiki.infographic.draft."+id))',id)
def pick(page,kind,query='',index=None,row=None):
    if kind in ['weapons','accessories','tarot'] and index is not None:
        while page.locator(f'[data-ig-pick={kind}]').count()<=index:
            page.locator(f'[data-ig-add-gear={kind}]').click();ready(page)
    locator=f'[data-ig-pick="{kind}"]'
    if index is not None:locator+=f'[data-index="{index}"]'
    if row is not None:locator+=f'[data-row="{row}"]'
    page.locator(locator).click()
    if query:page.locator('#ig-picker-search').fill(query)
def choose_first(page):
    b=page.locator('[data-ig-choice]').first;id=b.get_attribute('data-ig-choice');b.click();return id

def run():
    errors=[];remote=[];checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(offline=True,viewport={'width':1600,'height':1080},accept_downloads=True)
        page=context.new_page();page.add_init_script(r"window.posterText=[];for(const method of ['fillText','strokeText']){const original=CanvasRenderingContext2D.prototype[method];CanvasRenderingContext2D.prototype[method]=function(text,x,y,...args){if(this.canvas.width===1920)window.posterText.push({text:String(text),method,color:this.fillStyle,font:this.font,x:this.getTransform().transformPoint({x,y}).x,y:this.getTransform().transformPoint({x,y}).y,width:this.measureText(text).width*Math.hypot(this.getTransform().a,this.getTransform().b),scaleX:Math.hypot(this.getTransform().a,this.getTransform().b),scaleY:Math.hypot(this.getTransform().c,this.getTransform().d),size:parseFloat(this.font.match(/[\d.]+(?=px)/)[0])*Math.hypot(this.getTransform().c,this.getTransform().d),height:this.canvas.height});return original.call(this,text,x,y,...args);};}");page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('https:','http:')) else None)
        page.add_init_script("window.posterBadges=[];const draw=CanvasRenderingContext2D.prototype.drawImage;CanvasRenderingContext2D.prototype.drawImage=function(image,...args){if(this.canvas.width===1920&&args.length===4&&args[0]>=1700&&args[1]<186)window.posterBadges.push(args);return draw.call(this,image,...args);};")
        page.add_init_script("window.posterDots=[];const arc=CanvasRenderingContext2D.prototype.arc;CanvasRenderingContext2D.prototype.arc=function(x,y,r,...rest){if(this.canvas.width===1920&&x<360&&y>300&&r<=6)window.posterDots.push({r,alpha:this.globalAlpha});return arc.call(this,x,y,r,...rest);};")
        page.add_init_script("window.posterIcons=[];const icon=CanvasRenderingContext2D.prototype.drawImage;CanvasRenderingContext2D.prototype.drawImage=function(image,...args){if(this.canvas.width===1920&&args.length===4&&args[2]===args[3]&&args[2]>=16&&args[2]<=100)window.posterIcons.push({x:args[0],y:args[1],w:args[2]});return icon.call(this,image,...args);};")
        page.goto(BASE);ready(page)
        assert page.locator('.ig-character strong').inner_text()=='薇佩拉'
        assert page.locator('.ig-tier').evaluate_all('(els)=>els.map(e=>Number(e.dataset.rank))')==[11,9,7,5,3,1,0]
        pick(page,'character');assert page.locator('[data-ig-choice]').count()==177
        assert page.locator('[data-ig-choice]').first.get_attribute('data-ig-choice')=='9295'
        page.keyboard.press('Escape')
        # Both wordmark characters offer their baked art as a name mode.
        ready(page)
        assert page.eval_on_selector_all('[data-ig-title-mode]','els=>els.map(e=>e.dataset.igTitleMode)')==['text','image','reference']
        assert page.locator('[data-ig-title-status]').inner_text().startswith('保留薇佩拉')
        pick(page,'character','君士坦丁');choose_first(page);ready(page)
        assert page.locator('[data-ig-title-status]').inner_text().startswith('保留君士坦丁')
        assert page.eval_on_selector('[data-ig-title-mode=reference]',"e=>e.getAttribute('aria-pressed')")=='true'
        pick(page,'character','薇佩拉');choose_first(page);ready(page)
        assert page.locator('.ig-tier[data-rank="0"] button').count()==0
        assert page.locator('.ig-tier[data-rank="0"] img').count()==2
        assert page.locator('[data-ig-paint],[data-ig-field=star],[data-ig-field=weaponStar]').count()==0
        cycling=page.locator('.ig-tier[data-rank="11"] [data-ig-mark]').first
        cycle_id=cycling.get_attribute('data-ig-mark')
        for expected in ['required','optional',None]:
            page.locator('[data-ig-mark="'+cycle_id+'"]').click()
            assert saved(page)['marks'].get(cycle_id)==expected
        # Mark both recommendations directly in the actual source skill branches.
        for rank,side,mode in [(11,0,'required'),(9,0,'required'),(7,1,'required'),(5,0,'required'),(3,0,'optional'),(3,1,'required'),(1,0,'optional'),(1,1,'required')]:
            for _ in range(1 if mode=='required' else 2):page.locator(f'.ig-tier[data-rank="{rank}"] [data-ig-mark]').nth(side).click()
        assert len(saved(page)['marks'])==8
        assert page.locator('.ig-tree-node[data-mark=optional]').count()==2
        checks.append('177 characters in source order; descending actual skill branches and required/optional marks')
        pick(page,'exclusive','幽辉蛇吻');assert choose_first(page)=='9337'
        pick(page,'weapons','幽辉蛇吻',0);choose_first(page)
        pick(page,'weapons','丰饶匕首',1);choose_first(page)
        pick(page,'accessories','灾害瓶',0);choose_first(page)
        pick(page,'accessories','飞刃臂套',1);choose_first(page)
        for i,name in enumerate(['倒吊人的奉献','魔术师的梦想','恶魔的诱惑','正义的裁决']):
            pick(page,'tarot',name,i);choose_first(page)
        assert page.locator('[data-ig-engraving]').count()==10
        page.locator('.ig-engraving-option',has_text='宝剑+权杖').locator('input').check()
        page.locator('.ig-engraving-option',has_text='权杖+圣杯').locator('input').check()
        page.get_by_label('宝剑+权杖说明',exact=True).fill('适合需要移动后主动攻击的场景。')
        page.get_by_label('权杖+圣杯说明',exact=True).fill('需要技能循环时可选择，注意触发概率。')
        page.get_by_label('武器1红字备注',exact=True).fill('专武优先')
        page.get_by_label('装具1红字备注',exact=True).fill('补充功能')
        page.get_by_label('塔罗1红字备注',exact=True).fill('持续伤害')
        page.get_by_label('武器整组红字说明',exact=True).fill('按场景自由选择')
        page.get_by_label('装具整组红字说明',exact=True).fill('以实际队伍需求为准')
        page.get_by_label('塔罗整组红字说明',exact=True).fill('功能示例，搭配可调整')
        effect=page.locator('.ig-trait-info').text_content()
        for values in ['5%/10%/10%/15%/20%','0/0/0/0/15%','1/1/1/2/2','0/1/1/1/2','0/0/1/1/1']:assert values in effect,values
        assert '12%/16%/16%/20%/24%' in page.locator('.ig-weapon-info').text_content()
        checks.append('Exclusive weapon, compatible weapon filter, accessories, 22 tarot and all 10 engravings')
        # Add the two optional builds and fill all three through the pickers.
        for _ in range(2):page.locator('[data-ig=loadout-add]').click();ready(page)
        for row in range(3):
            page.locator(f'[data-ig-loadout="{row}"]').fill(['大招爆发流','隐身消能量','挂机备选'][row])
            pick(page,'skill','平射' if row==2 else '蚀骨击',0,row);choose_first(page)
            pick(page,'skill','蜕逃',1,row);assert page.locator('[data-ig-choice]').count()==1;choose_first(page)
            for slot,name in enumerate([['厄兆疫变','狂蛇之影','贪噬之牙'],['厄兆疫变','幽鳞潜袭','贪噬之牙'],['厄兆疫变','蛇影诡步','毒牙绽放']][row],2):
                pick(page,'skill',name,slot,row);choose_first(page)
        before=saved(page)['loadouts'][0]['slots']
        page.locator('[data-ig-move="1"][data-row="0"][data-index="2"]').click()
        assert saved(page)['loadouts'][0]['slots'][2:4]==[before[3],before[2]]
        page.locator('[data-ig-move="-1"][data-row="0"][data-index="3"]').click()
        assert saved(page)['loadouts'][0]['slots']==before
        checks.append('Three editable five-slot loadouts; initial basic and reaction pools; skill reordering')
        page.locator('[data-ig-field=author]').fill('工坊示例')
        page.locator('[data-ig-field=subtitle]').fill('角色养成一图流')
        page.locator('[data-ig-field=treeNotes]').fill('加点顺序和技能取舍可自由填写。\n本图的必点、选点标记仅作排版示例。')
        page.locator('[data-ig-notes]').click()
        page.keyboard.type('这是一张功能示例图，评分仅用于演示。\n先选角色，再标注必点和选点技能；三套搭配可按使用场景调整。\n装备、塔罗与刻印都能自由更换。')
        for i,score in enumerate([5,3,1.5,2,2.5,3]):page.locator(f'#ig-score-{i}').fill(str(score))
        assert saved(page)['scores']==[5,3,1.5,2,2.5,3]
        # The built-in six stay put; extra radars carry their own name, axes and scores.
        assert [row.inner_text().split('\n')[0] for row in page.locator('.ig-scores .ig-score').all()][:2]==['DOT','直伤']
        page.locator('[data-ig=radar-add]').click();ready(page)
        charts=saved(page)['radarCharts']
        assert len(charts)==1 and [a['name'] for a in charts[0]['axes']]==['维度一','维度二','维度三']
        page.locator('[data-ig-radar-name="0"]').fill('高难评分');ready(page)
        page.locator('[data-ig-field=radarTitle]').fill('自定义评分');ready(page)
        assert saved(page)['radarTitle']=='自定义评分'
        page.locator('[data-ig-radar-axis-name="0:0"]').fill('清杂');ready(page)
        page.locator('#ig-radar-score-0-0').fill('4');ready(page)
        page.locator('[data-ig-radar-axis-add="0"]').click();ready(page)
        charts=saved(page)['radarCharts']
        assert charts[0]['name']=='高难评分' and len(charts[0]['axes'])==4 and charts[0]['axes'][0]['name']=='清杂' and charts[0]['axes'][0]['score']==4
        page.locator('[data-ig-radar-axis-remove="0:0"]').click();ready(page)
        assert page.locator('[data-ig-radar-axis-remove="0:0"]').is_disabled()
        page.locator('[data-ig=radar-add]').click();page.locator('[data-ig=radar-add]').click();ready(page)
        assert len(saved(page)['radarCharts'])==3 and page.locator('[data-ig=radar-add]').is_disabled()
        page.locator('[data-ig-radar-remove="2"]').click();page.locator('[data-ig-radar-remove="1"]').click();ready(page)
        assert len(saved(page)['radarCharts'])==1
        # An unnamed axis keeps its slot; ceilings and display mode are per chart.
        page.locator('[data-ig-radar-axis-name="0:0"]').fill('');ready(page)
        charts=saved(page)['radarCharts']
        assert len(charts)==1 and charts[0]['axes'][0]['name']==''
        # The ceiling updates in place: typing must not re-render or move the page.
        page.locator('.ig-radar-charts').scroll_into_view_if_needed()
        before=page.evaluate("()=>[Math.round(window.scrollY),Math.round(document.querySelector('#ig-editor').parentElement.scrollTop)]")
        page.locator('[data-ig-radar-max="0"]').click();page.locator('[data-ig-radar-max="0"]').press('Control+a')
        page.locator('[data-ig-radar-max="0"]').type('10',delay=120);ready(page)
        assert page.evaluate("()=>[Math.round(window.scrollY),Math.round(document.querySelector('#ig-editor').parentElement.scrollTop)]")==before
        page.locator('#ig-radar-score-0-0').fill('8');ready(page)
        page.locator('[data-ig-radar-unit="0"]').select_option('percent');ready(page)
        charts=saved(page)['radarCharts']
        assert charts[0]['max']==10 and charts[0]['unit']=='percent' and charts[0]['axes'][0]['score']==8
        page.locator('[data-ig-radar-max="0"]').fill('4');ready(page)
        assert saved(page)['radarCharts'][0]['axes'][0]['score']==4
        page.locator('[data-ig-radar-max="0"]').fill('10');ready(page)
        # Each axis may carry its own ceiling; lowering one only clamps that axis.
        page.locator('[data-ig-radar-axis-max="0:0"]').fill('100');ready(page)
        page.locator('#ig-radar-score-0-0').fill('75');ready(page)
        charts=saved(page)['radarCharts']
        assert charts[0]['axes'][0]['max']==100 and charts[0]['axes'][0]['score']==75
        page.locator('[data-ig-radar-axis-max="0:0"]').fill('10');ready(page)
        assert saved(page)['radarCharts'][0]['axes'][0]['score']==10
        page.locator('[data-ig-radar-axis-max="0:0"]').fill('100');ready(page)
        # The block is reachable from the preview like every other region.
        assert 'radar' in page.eval_on_selector_all('.ig-preview .ig-hotspots [data-ig-jump]','els=>els.map(e=>e.dataset.igJump)')
        assert 'radar' in page.eval_on_selector('#ig-layout-select','e=>[...e.options].map(o=>o.value)')
        page.locator('.ig-preview .ig-hotspots [data-ig-jump=radar]').click()
        assert page.locator('.ig-radar-charts').is_visible()
        # The journal accepts pasted HTML; only the formatting subset survives.
        page.locator('.ig-notes-editor [data-ig-rich=source]').click()
        page.locator('[data-ig-field=notes]').fill('优先<b>魔攻</b>，<span style="color:#85d5e7;font-size:20px">福音</span>层。<script>alert(1)</script>')
        ready(page)
        assert '<b>魔攻</b>' in saved(page)['notes'] and 'alert' not in saved(page)['notes']
        page.locator('[data-ig-field=scoreText]').fill('持续伤害定位，副本与高难都好用。\n生存依赖队友，评分仅作排版示例。')
        assert saved(page)['scoreText'].startswith('持续伤害定位')
        ready(page)
        # Real pointer gestures, anchor zoom, original/awakened art and persistent positioning.
        ready(page);page.locator('[data-ig=background-edit]').first.click()
        page.locator('#ig-background-choices [data-ig-art=base]').click();ready(page)
        page.locator('[data-ig-background-scale]').fill('125');ready(page)
        box=page.locator('#ig-background-canvas').bounding_box();cx=box['x']+box['width']*.5;cy=box['y']+box['height']*.5
        page.mouse.move(cx,cy);page.mouse.down();page.mouse.move(cx+box['width']*.05,cy+box['height']*.03,steps=6);page.mouse.up();ready(page)
        moved=saved(page)['background'];assert moved['portrait']=='base' and abs(moved['x']-96)<1 and abs(moved['y']-32.4)<1,moved
        page.mouse.wheel(0,-160);ready(page);assert saved(page)['background']['scale']>moved['scale']
        before_scale=saved(page)['background']['scale'];handle=page.locator('.ig-background-handle').bounding_box()
        page.mouse.move(handle['x']+handle['width']/2,handle['y']+handle['height']/2);page.mouse.down();page.mouse.move(handle['x']-50,handle['y']-40,steps=5);page.mouse.up();ready(page)
        assert saved(page)['background']['scale']<before_scale
        page.locator('.ig-background-stage').focus();old_x=saved(page)['background']['x'];page.keyboard.press('ArrowRight');ready(page);assert abs(saved(page)['background']['x']-old_x-10)<.01
        page.screenshot(path=str(OUT/'infographic-background-dialog.png'))
        page.locator('[data-ig=background-done]').click();positioned=saved(page)['background'];page.reload();ready(page);assert saved(page)['background']==positioned
        page.locator('[data-ig=background-edit]').first.click();page.locator('[data-ig=background-reset]').click();page.locator('#ig-background-choices [data-ig-art=awakened]').click();ready(page)
        page.locator('[data-ig=background-done]').click();assert saved(page)['background']=={'portrait':'awakened','x':0,'y':0,'scale':1}
        # A supplied transparent wordmark survives file:// storage and a portable JSON roundtrip.
        page.locator('#ig-title-file').set_input_files(ROOT/'assets/brand/vipera-reference-title.png')
        page.locator('[data-cut=apply]:enabled').click()
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.customTitle?.startsWith('data:image/png;base64,')");ready(page)
        with page.expect_download() as uploaded_plan:page.locator('[data-ig=save-plan]').click()
        custom_plan=OUT/'infographic-custom-title-plan.json';uploaded_plan.value.save_as(custom_plan)
        page.locator('[data-ig=title-reset]').click();ready(page);assert saved(page)['customTitle'] is None
        page.locator('#ig-import-file').set_input_files(custom_plan)
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.customTitle?.startsWith('data:image/png;base64,')");ready(page)
        page.locator('[data-ig=title-reset]').click();ready(page)
        # A custom background comes from a local picture and survives draft storage.
        page.locator('#ig-background-file').set_input_files(sample_background())
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))?.backgroundImage?.startsWith('data:image/webp;base64,')");ready(page)
        assert saved(page)['background']['portrait']=='custom'
        assert page.locator('.ig-background-thumb').count()==1 and page.locator('[data-ig=background-image-reset]').count()==1
        page.locator('[data-ig=background-image-reset]').click();ready(page)
        assert saved(page)['backgroundImage'] is None and saved(page)['background']['portrait']=='awakened'
        checks.append('Original/awakened backgrounds, pointer dragging, wheel/handle zoom, keyboard nudging and reload persistence; custom wordmark JSON roundtrip')

        with page.expect_download() as downloaded:page.locator('[data-ig=export]').first.click()
        poster=OUT/'infographic-example.png';downloaded.value.save_as(poster)
        with Image.open(poster) as image:assert image.size==(1920,1080);image.verify()
        assert poster.stat().st_size<16*1024*1024
        painted=page.evaluate('window.posterText')
        assert any(t['text']=='by' and t['method']=='strokeText' for t in painted)
        signature=[t for t in painted if 'WikiSignature' in t['font'] and t['method']=='strokeText']
        assert set('工坊示例').issubset({t['text'] for t in signature})
        assert signature and all(abs(t['scaleX']-t['scaleY'])<1e-6 for t in signature)
        assert page.evaluate("document.fonts.check('62px WikiSignature')")
        assert page.evaluate("document.fonts.check('68px WikiSignatureLatin')")
        assert not any('资料：BWIKI' in t['text'] or '制作：' in t['text'] or t['text'].endswith(' 星') for t in painted)
        red=[t for t in painted if t['text']=='按场景自由选择' and t['method']=='fillText']
        assert red and all(t['color']=='#ff9292' and abs(t['x']+t['width']/2-1332)<1 for t in red)
        # The actual painted baseline follows each name, including a six-character Tarot name.
        for name,note in [('幽辉蛇吻','专武优先'),('灾害瓶','补充功能'),('倒吊人的奉献','持续伤害')]:
            name_draw=next(t for t in reversed(painted) if t['text']==name and t['x']>1072)
            note_draw=next(t for t in reversed(painted) if t['text']==note)
            assert 10<=note_draw['y']-name_draw['y']<=20,(name,name_draw,note_draw)
            assert abs(note_draw['x']+note_draw['width']/2-(name_draw['x']+name_draw['width']/2))<1
        badges=page.locator('.ig-profile-badges img')
        assert badges.evaluate_all('(els)=>els.map(e=>e.alt).filter(Boolean)')==['突袭者','法皇国','锐疾如风']
        assert badges.evaluate_all('(els)=>els.every(e=>e.complete&&e.naturalWidth>0)')
        assert page.locator('.ig-profile-badges .ig-profession-badge').evaluate('(e)=>e.getBoundingClientRect().width')==38
        badge_draws=page.evaluate('window.posterBadges');assert len(badge_draws)>=4 and all(abs(b[1]+b[3]/2-82.5)<1 for b in badge_draws) and all(b[2]<=56 for b in badge_draws)

        assert not any(t['y']<186 and any(word in t['text'] for word in ['传说','突袭者','法皇国','锐疾如风']) for t in painted)
        assert any(t['text']=='角色养成一图流' for t in painted)
        assert page.locator('.ig-lib-mark>span').all_text_contents()==['单打独斗']
        assert page.locator('.ig-branches path').count()==14
        paths=page.locator('.ig-branches path').evaluate_all('(els)=>els.map(e=>e.getAttribute("d"))');assert all('C' not in d for d in paths)
        assert page.locator('.ig-tier[data-branch=short]').evaluate_all('(els)=>els.map(e=>Number(e.dataset.rank))')==[9,5,1]
        assert page.locator('.ig-tier[data-branch=long]').evaluate_all('(els)=>els.map(e=>Number(e.dataset.rank))')==[11,7,3]
        assert '参考原图字标' in page.locator('.ig-title-controls').inner_text()
        assert '3000 × 2539' in page.locator('.ig-background-controls [data-ig-background-quality]').inner_text()
        off=page.locator('.ig-tree-node[data-mark=""]:not(.ig-initial-node) .ig-node-select>img').first
        assert 'grayscale(1)' in off.evaluate('(e)=>getComputedStyle(e).filter')
        assert any('加点顺序和技能取舍' in t['text'] for t in painted)
        page.locator('[data-ig-liberation]').click();assert '3 级' in page.locator('.ig-skill-detail').inner_text();page.keyboard.press('Escape')
        assert page.locator('[data-ig-field=titleColor]').input_value()=='#ef9b73'
        page.locator('[data-ig-field=titleColor]').fill('#79d1f2');ready(page)
        with page.expect_download() as colored:page.locator('[data-ig=export]').first.click()
        cyan_poster=OUT/'infographic-title-cyan.png';colored.value.save_as(cyan_poster)
        with Image.open(poster) as a,Image.open(cyan_poster) as b:
            assert a.crop((190,15,750,145)).tobytes()!=b.crop((190,15,750,145)).tobytes()
        page.locator('[data-ig-field=titleColor]').fill('#ef9b73');ready(page)
        for mode,style in [('required','solid'),('optional','dotted')]:
            border=page.locator('.ig-tree-node[data-mark='+mode+'] .ig-node-select>img').first.evaluate('(e)=>{const s=getComputedStyle(e);return [s.borderTopWidth,s.borderTopStyle];}')
            assert border==['3px',style],border
        assert page.get_by_label('区域底框透明度',exact=True).input_value()=='8'
        assert page.get_by_label('背景立绘透明度',exact=True).input_value()=='35'
        assert page.evaluate('window.posterDots.some(d=>d.r===1.5&&d.alpha===1)')
        page.evaluate('window.posterDots=[]')
        for label,value in [('技能标记圈粗细','4'),('区域底框透明度','38'),('背景立绘透明度','20')]:
            page.get_by_label(label,exact=True).fill(value);ready(page)
        assert saved(page)['markWidth']==4 and saved(page)['panelOpacity']==.62 and saved(page)['backgroundOpacity']==.8
        # Gear icons follow their own size setting and the rows grow with them.
        page.get_by_label('武器 / 装具 / 塔罗图标大小',exact=True).fill('72');ready(page)
        assert saved(page)['gearIconSize']==72
        assert page.evaluate('window.posterIcons.some(i=>i.w>60&&i.w<=72)')
        assert page.evaluate('window.posterDots.some(d=>d.r===2&&d.alpha===1)')
        assert page.locator('.ig-tree-node[data-mark=optional] .ig-node-select>img').first.evaluate('(e)=>getComputedStyle(e).borderTopWidth')=='4px'
        page.reload();ready(page)
        assert page.get_by_label('技能标记圈粗细',exact=True).input_value()=='4'
        assert page.get_by_label('区域底框透明度',exact=True).input_value()=='38'
        with page.expect_download() as style_plan:page.locator('[data-ig=save-plan]').click()
        style_path=OUT/'infographic-v18-style-plan.json';style_plan.value.save_as(style_path)
        page.get_by_label('背景立绘透明度',exact=True).fill('100');ready(page)
        assert saved(page)['backgroundOpacity']==0
        page.locator('#ig-import-file').set_input_files(style_path)
        page.wait_for_function("()=>document.querySelector('[data-ig-style=backgroundOpacity]').value==='20'");ready(page)
        with page.expect_download() as styled:page.locator('[data-ig=export]').first.click()
        styled.value.save_as(OUT/'infographic-v18-adjusted.png')
        for label,value in [('技能标记圈粗细','3'),('区域底框透明度','8'),('背景立绘透明度','35')]:
            page.get_by_label(label,exact=True).fill(value);ready(page)
        checks.append('Single row of profession/faction icons without rarity; true round dots; editable ring width and independent panel/portrait transparency with reload/JSON persistence')
        checks.append('1920x1080 landscape, straight alternating gray/colored branches, liberation cap, editable tree footer and recolorable offline vector title')
        checks.append('Initial nodes display only; three-state cycles; five-star slash values with zeroes; multiple engraving explanations; centered red notes and artistic signature')
        checks.append('Built-in six-axis radar untouched while extra custom radars keep their own name, axes and scores; a custom background comes from a local picture')
        with page.expect_download() as downloaded:page.locator('[data-ig=save-plan]').click()
        plan=OUT/'infographic-example.json';downloaded.value.save_as(plan);backup=json.loads(plan.read_text(encoding='utf8'));assert backup['format']=='socwiki-infographic'
        assert len(backup['state']['loadouts'])==3;assert backup['version']==6;assert len(backup['state']['engravings'])==2
        page.evaluate('scrollTo(0,0)');page.wait_for_timeout(250);page.screenshot(path=str(OUT/'infographic-desktop.png'))
        checks.append('Colored 1920x1080 PNG exports successfully from file://, offline; editable JSON export')
        # All ten engraving choices can render together without truncation.
        for option in page.locator('[data-ig-engraving]').all():
            if not option.is_checked():option.check()
        ready(page)
        with page.expect_download() as downloaded:page.locator('[data-ig=export]').first.click()
        all_engraving=OUT/'infographic-all-engravings.png';downloaded.value.save_as(all_engraving)
        with Image.open(all_engraving) as image:assert image.size==(1920,1080);image.verify()
        assert page.locator('.ig-density-note').is_visible()
        assert all_engraving.stat().st_size<16*1024*1024
        assert len(saved(page)['engravings'])==10
        page.locator('#ig-import-file').set_input_files(plan)
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296')).engravings.length===2");ready(page)
        checks.append('All ten engraving combinations plus explanations fit in the exported PNG')
        # A different character gets their own skill pools and draft, then recovers the first draft.
        pick(page,'character','歌洛莉亚');choose_first(page);ready(page)
        assert page.locator('.ig-character strong').inner_text()=='歌洛莉亚'
        assert page.locator('.ig-lib-mark>span').all_text_contents()==['厚积强发','圣枪·裁决']
        assert '普通文字' in page.locator('.ig-title-controls').inner_text()
        page.locator('[data-ig-field=author]').fill('Aurelia Nightingale');ready(page)
        latin=page.evaluate("window.posterText.filter(t=>t.font.includes('WikiSignatureLatin')&&t.method==='fillText')")
        for word in ['Aurelia','Nightingale']:
            word_draw=next(t for t in reversed(latin) if t['text']==word)
            assert 1500<=word_draw['x'] and word_draw['x']+word_draw['width']<=1896,word_draw
            assert abs(word_draw['scaleX']-word_draw['scaleY'])<1e-6
        with page.expect_download() as english:page.locator('[data-ig=export]').first.click()
        english.value.save_as(OUT/'infographic-normal-english.png')
        page.locator('[data-ig-field=author]').fill('阿呆Coney');ready(page)
        assert page.evaluate("window.posterText.some(t=>t.text==='Coney'&&t.font.includes('WikiSignatureLatin'))")
        assert page.evaluate("window.posterText.some(t=>t.text==='阿'&&t.font.includes('WikiSignature'))")
        with page.expect_download() as mixed:page.locator('[data-ig=export]').first.click()
        mixed.value.save_as(OUT/'infographic-normal-mixed.png')
        checks.append('Native 3000px lossless background, normal text titles, whole-word Latin cursive and mixed Chinese/English signatures')
        page.get_by_label('角色显示名',exact=True).fill('霁月·瑟蕾妮娅');ready(page)
        assert page.evaluate("Array.from(document.fonts).some(f=>f.family==='WikiTitleNormal'&&f.status==='loaded')")
        assert '新名字可离线输入' in page.locator('[data-ig-title-status]').inner_text()
        assert not page.locator('[data-ig-title-status]').evaluate('(e)=>e.classList.contains("ig-title-warning")')
        with page.expect_download() as title_png:page.locator('[data-ig=export-title]').click()
        title_file=OUT/'infographic-new-name-title.png';title_png.value.save_as(title_file)
        with Image.open(title_file) as title_image:
            assert title_image.mode=='RGBA' and title_image.getchannel('A').getextrema()==(0,255)
            assert title_image.width<=2400 and title_image.height<=481
        with page.expect_download() as new_plan:page.locator('[data-ig=save-plan]').click()
        title_plan=OUT/'infographic-title-plan.json';new_plan.value.save_as(title_plan)
        title_state=json.loads(title_plan.read_text(encoding='utf8'));assert title_state['version']==6 and title_state['state']['titleName']=='霁月·瑟蕾妮娅'
        page.reload();ready(page);assert page.get_by_label('角色显示名',exact=True).input_value()=='霁月·瑟蕾妮娅'
        page.locator('[data-ig=title-reset]').click();ready(page);assert page.get_by_label('角色显示名',exact=True).input_value()==''
        page.locator('#ig-import-file').set_input_files(title_plan);ready(page)
        page.wait_for_function("()=>document.querySelector('[data-ig-field=titleName]').value==='霁月·瑟蕾妮娅'")
        page.locator('[data-ig=title-reset]').click();ready(page)
        checks.append('Smaller profession badge centered with faction icons; new names render without a baked wordmark, export transparent PNG and persist through JSON/reload')

        pick(page,'character','贝拉');choose_first(page);ready(page)
        assert page.locator('.ig-lib-mark>span').all_text_contents()==['火力打击之道','轰隆隆！','停不下来啦！']
        pick(page,'character','歌洛莉亚');choose_first(page);ready(page)
        assert page.locator('.ig-tree-node[data-mark=required]').count()==0
        page.locator('[data-ig-field=author]').fill('另一份草稿')
        pick(page,'character','薇佩拉');choose_first(page);ready(page)
        assert page.locator('[data-ig-field=author]').input_value()=='工坊示例'
        assert saved(page)['loadouts']==backup['state']['loadouts']
        page.reload();ready(page);assert page.locator('[data-ig-field=author]').input_value()=='工坊示例'
        page.locator('[data-ig-field=author]').fill('临时改动');page.locator('#ig-import-file').set_input_files(plan);ready(page)
        page.wait_for_function("()=>document.querySelector('[data-ig-field=author]')?.value==='工坊示例'")
        assert saved(page)['treeNotes']==backup['state']['treeNotes'] and saved(page)['titleColor']==backup['state']['titleColor']
        checks.append('Per-character drafts, custom title color/tree notes persistence and JSON import roundtrip; 1/2/3 liberation skills')
        pick(page,'character','小力');choose_first(page);ready(page)
        assert '尚未收录立绘' in page.locator('.ig-notice').inner_text()
        assert page.locator('.ig-tree-node.unavailable').count()==12
        assert page.locator('.ig-tree-node.ig-initial-node').count()==2
        assert '未收录' in page.locator('.ig-cv').inner_text()
        checks.append('Incomplete source character uses explicit missing-art/CV/skill fallbacks')
        pick(page,'character','薇佩拉');choose_first(page);ready(page)
        for width in [360,390,768,820,1024,1440]:
            page.set_viewport_size({'width':width,'height':900});page.evaluate('scrollTo(0,0)');page.wait_for_timeout(250)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        page.set_viewport_size({'width':390,'height':844});page.evaluate('scrollTo(0,0)');page.wait_for_timeout(250)
        page.screenshot(path=str(OUT/'infographic-mobile-edit.png'))
        page.locator('[data-ig-view=preview]').click();page.screenshot(path=str(OUT/'infographic-mobile-preview.png'))
        page.locator('[data-ig=enlarge]').click();assert page.locator('.ig-full-preview').evaluate('(e)=>e.open')
        page.keyboard.press('Escape');assert not page.locator('.ig-full-preview').evaluate('(e)=>e.open')
        page.locator('[data-action=theme]').click();page.screenshot(path=str(OUT/'infographic-mobile-dark.png'))
        checks.append('360–1440px layouts, mobile editor/preview switch, full-size view, Escape and dark theme')
        page.locator('[data-ig=background-edit]').last.click();ready(page)
        stage=page.locator('.ig-background-stage');box=stage.bounding_box();tx=box['x']+box['width']*.55;ty=box['y']+box['height']*.5
        for pid,dx in [(101,-28),(102,28)]:stage.dispatch_event('pointerdown',{'pointerId':pid,'pointerType':'touch','clientX':tx+dx,'clientY':ty,'buttons':1})
        before_pinch=saved(page)['background']['scale']
        for pid,dx in [(101,-52),(102,52)]:stage.dispatch_event('pointermove',{'pointerId':pid,'pointerType':'touch','clientX':tx+dx,'clientY':ty,'buttons':1})
        for pid,dx in [(101,-52),(102,52)]:stage.dispatch_event('pointerup',{'pointerId':pid,'pointerType':'touch','clientX':tx+dx,'clientY':ty,'buttons':0})
        ready(page);assert saved(page)['background']['scale']>before_pinch*1.5
        assert stage.bounding_box()['x']>=0 and stage.bounding_box()['x']+stage.bounding_box()['width']<=390
        page.screenshot(path=str(OUT/'infographic-background-mobile.png'))
        page.keyboard.press('Escape');assert not page.locator('.ig-background-dialog').is_visible()
        checks.append('390px background editor, two-finger zoom and Escape dismissal')

        # Simulate a missing export asset: it must block the export, then recover on retry.
        failure_context=browser.new_context(offline=True);failure=failure_context.new_page();blocked=[False]
        def fail_once(route):
            if not blocked[0]:blocked[0]=True;route.abort()
            else:route.continue_()
        failure.route('**/data/infographic-assets/*.js',fail_once);failure.goto(BASE)
        failure.wait_for_selector('.ig-retry:not([hidden])',timeout=60000)
        assert failure.locator('[data-ig=export]').first.is_disabled()
        failure.locator('[data-ig=retry-render]').click();ready(failure);failure_context.close()
        checks.append('Missing-image export fails visibly, prevents partial exports, and can retry')
        assert not errors,errors;assert not remote,remote
        context.close();browser.close()
    report={'status':'passed','checks':checks,'errors':errors,'remoteRequests':remote,'poster':str(poster),'posterBytes':poster.stat().st_size}
    (OUT/'infographic-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    for check in checks:print('PASS '+check,flush=True)

if __name__=='__main__':run()
