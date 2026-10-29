"""Exercise variable builds and the optional styled commentary frame entirely offline."""
from pathlib import Path
import json
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'android/app/build/generated/wikiAssets/wiki' if '--android' in sys.argv else ROOT
OUT=ROOT/'test-results'

def ready(p):p.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920&&!document.querySelector('[data-ig=export]')?.disabled",timeout=60000)
def saved(p):return p.evaluate("JSON.parse(localStorage.getItem('socwiki.infographic.draft.9296'))")

with sync_playwright() as pw:
    browser=pw.chromium.launch();p=browser.new_page(offline=True,viewport={'width':1600,'height':1000},accept_downloads=True,reduced_motion='reduce');errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
    p.add_init_script("window.painted=[];const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(t,x,y,...a){if(this.canvas.width===1920)window.painted.push({text:String(t),font:this.font,color:this.fillStyle,x,y});return fill.call(this,t,x,y,...a);};")
    p.goto((BASE/'index.html').as_uri()+'#/tools/infographic');ready(p)
    assert p.locator('.ig-loadout').count()==1
    assert p.locator('[data-ig-remove-loadout]').is_disabled()
    assert not p.locator('[data-ig-commentary=enabled]').is_checked()
    assert not p.locator('.ig-commentary-fields').is_visible()
    assert p.locator('#ig-layout-select option[value=loadoutNotes]').count()==0
    # Five editable rows prove the old three-row bound has gone.
    p.locator('.ig-nav [data-ig-jump=loadouts]').click()
    for _ in range(4):p.locator('[data-ig=loadout-add]').click();ready(p)
    assert p.locator('.ig-loadout').count()==5
    p.locator('[data-ig-loadout="4"]').fill('持久战');ready(p)
    p.locator('[data-ig-pick=skill][data-row="4"][data-index="2"]').click()
    choice=p.locator('[data-ig-choice]').first;skill_id=int(choice.get_attribute('data-ig-choice'));choice.click();ready(p)
    assert saved(p)['loadouts'][4]['slots'][2]==skill_id
    p.locator('[data-ig-remove-loadout="1"]').click();ready(p)
    assert saved(p)['loadouts'][3]['name']=='持久战' and saved(p)['loadouts'][3]['slots'][2]==skill_id
    p.reload();ready(p);assert p.locator('.ig-loadout').count()==4
    p.locator('.ig-nav [data-ig-jump=loadoutNotes]').click();p.locator('[data-ig-commentary=enabled]').check();ready(p)
    text='先用控制技能限制敌人，再接爆发。第二轮视战况替换续航技能。'
    p.get_by_label('搭配解说内容',exact=True).fill(text)
    p.get_by_label('搭配解说字体',exact=True).select_option('serif')
    p.get_by_label('搭配解说对齐',exact=True).select_option('center')
    p.get_by_label('搭配解说字号',exact=True).fill('22')
    p.locator('[data-ig-commentary=bold]').check();p.locator('[data-ig-commentary=italic]').check()
    p.get_by_label('搭配解说文字颜色',exact=True).fill('#c7deef')
    p.get_by_label('搭配解说描边宽度',exact=True).fill('1');ready(p)
    p.locator('[data-ig=commentary-layout]').click()
    assert p.locator('#ig-layout-select').input_value()=='loadoutNotes'
    for key,value in [('w','650'),('h','180'),('x','380'),('y','690')]:p.locator(f'.ig-editor [data-ig-rect={key}]').fill(value);ready(p)
    assert saved(p)['layout']['loadoutNotes']=={'x':380,'y':690,'w':650,'h':180}
    assert p.locator('.ig-canvas-wrap [data-ig-layout-select=loadoutNotes]').count()==1
    paints=p.evaluate('painted');note=[x for x in paints if x['color']=='#c7deef' and '控制技能' in x['text']]
    assert note and '22px' in note[-1]['font'] and 'italic' in note[-1]['font'] and 'WikiTitleNormal' in note[-1]['font'],note
    p.locator('[data-ig=enlarge]').click()
    assert p.locator('.ig-full-preview [data-ig-layout-select=loadoutNotes]').count()==1
    p.locator('[data-ig-full-select]').select_option('loadoutNotes')
    p.locator('.ig-full-preview [data-ig-rect=w]').fill('680');ready(p)
    assert saved(p)['layout']['loadoutNotes']['w']==680
    p.locator('[data-ig-full-mode=view]').click();p.screenshot(path=str(OUT/'infographic-v115-loadouts-preview.png'))
    p.locator('[data-ig=close-preview]').click()
    with p.expect_download() as dl:p.locator('[data-ig=save-plan]').click()
    plan=OUT/'infographic-v115-loadouts-plan.json';dl.value.save_as(plan);expected=saved(p)
    p.locator('.ig-nav [data-ig-jump=loadoutNotes]').click();p.evaluate('painted=[]');p.locator('[data-ig-commentary=enabled]').uncheck();ready(p)
    assert saved(p)['loadoutCommentary']['text']==text
    assert p.locator('.ig-hotspots [data-ig-jump=loadoutNotes]').count()==0
    assert not any(x['color']=='#c7deef' for x in p.evaluate('painted'))
    assert p.locator('#ig-layout-select option[value=loadoutNotes]').count()==0
    for _ in range(3):p.locator('[data-ig-remove-loadout]').first.click();ready(p)
    assert p.locator('.ig-loadout').count()==1 and p.locator('[data-ig-remove-loadout]').is_disabled()
    # A legacy three-build plan has no explanation settings and must retain every build.
    legacy=json.loads(plan.read_text(encoding='utf8'));legacy['state']['loadouts']=legacy['state']['loadouts'][:3];del legacy['state']['loadoutCommentary']
    old=OUT/'infographic-v115-legacy-plan.json';old.write_text(json.dumps(legacy,ensure_ascii=False),encoding='utf8')
    p.locator('#ig-import-file').set_input_files(old);ready(p)
    assert saved(p)['loadouts']==legacy['state']['loadouts'] and not saved(p)['loadoutCommentary']['enabled']
    p.locator('#ig-import-file').set_input_files(plan);ready(p);assert saved(p)['loadouts']==expected['loadouts'] and saved(p)['loadoutCommentary']==expected['loadoutCommentary']
    p.reload();ready(p);assert saved(p)['loadoutCommentary']==expected['loadoutCommentary']
    with p.expect_download() as dl:p.locator('[data-ig=export]').first.click()
    dl.value.save_as(OUT/'infographic-v115-loadouts.png')
    p.set_viewport_size({'width':390,'height':844});p.locator('.ig-nav [data-ig-jump=loadoutNotes]').click();p.screenshot(path=str(OUT/'infographic-v115-loadouts-mobile.png'))
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    check=p.locator('[data-ig-commentary=enabled]').bounding_box();assert check['width']<=20 and check['height']<=20,check
    assert p.locator('[data-ig-commentary=enabled]').locator('..').bounding_box()['height']<40
    assert not errors,errors
    browser.close()
print('PASS default/minimum one, five editable builds, stable deletion, legacy migration, optional styled/resizable commentary, enlarged editing, JSON/reload/PNG and mobile layout')
