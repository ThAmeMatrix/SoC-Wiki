from pathlib import Path
import json
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'
def read_js(path):
 s=path.read_text(encoding='utf8');return json.JSONDecoder().raw_decode(s[s.index('=')+1:])[0]
index=read_js(ROOT/'data/index.js');chars=[c for c in index['pages'] if c['type']=='character' and not c.get('redirect')]
reference=[c for c in chars if '可邂逅角色' in c.get('categories',[]) and '召唤物' not in c.get('categories',[])]
assert len(reference)==158
assert {5997,8774,8640,8632,5672}.isdisjoint(c['id'] for c in reference)
keys=['attack','magic','defense','resistance','health','agility'];maxima=dict.fromkeys(keys,0);chosen=None
for c in chars:
 f=read_js(ROOT/f"data/pages/{c['id']}.js").get('rawFields',{});stats=c.get('stats',{})
 vals=[stats.get(field) or f.get('满级满星'+field) or (f.get('初始敏捷') if field=='敏捷' else None) for field in ['物攻','魔攻','物防','魔防','生命','敏捷']]
 if c in reference:
  for key,v in zip(keys,vals):
   try:maxima[key]=max(maxima[key],float(v))
   except (TypeError,ValueError):pass
 if c['id']==9296:chosen=vals
assert maxima=={'attack':1718,'magic':1718,'defense':814,'resistance':800,'health':4335,'agility':288},maxima
def ready(p):p.wait_for_function("()=>document.querySelector('#ig-canvas')?.width===1920&&!document.querySelector('[data-ig=export]')?.disabled",timeout=60000)
def check_canvas_stats(p):
 paints=p.evaluate('statPaints')
 for key,v in zip(keys,chosen):
  expected=float(v)/maxima[key]*100;texts=[str(v),f'/ {int(maxima[key])}',f'{expected:.1f}%']
  matches=[paints[i:i+3] for i in range(len(paints)-2) if [r['text'] for r in paints[i:i+3]]==texts]
  assert matches,texts
  current,maximum,share=matches[-1]
  assert current['color']!=maximum['color'] and ('700 ' in current['font'] or 'bold ' in current['font']),matches[-1]
  assert current['y']<maximum['y'] and maximum['y']==share['y']
  assert maximum['x']+maximum['width']<=share['x']-share['width']+.1
with sync_playwright() as pw:
 b=pw.chromium.launch();p=b.new_page(viewport={'width':1600,'height':1000},offline=True,accept_downloads=True);errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
 p.add_init_script(r"""window.groupBounds=[];window.statPaints=[];const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(t,x,y,...rest){if(/^(?:[-\d.]+|\/ (?:[-\d.]+|—)|[\d.]+%)$/.test(String(t)))window.statPaints.push({text:String(t),x,y,color:this.fillStyle,font:this.font,width:this.measureText(t).width});if(String(t).startsWith('交流群')){const m=this.measureText(t),a=this.getTransform(),tl=a.transformPoint({x:x-m.actualBoundingBoxLeft,y:y-m.actualBoundingBoxAscent}),br=a.transformPoint({x:x+m.actualBoundingBoxRight,y:y+m.actualBoundingBoxDescent});window.groupBounds.push({top:tl.y,left:tl.x,bottom:br.y,right:br.x});}return fill.call(this,t,x,y,...rest);};""")
 p.goto((ROOT/'index.html').as_uri()+'#/tools/infographic');ready(p)
 bars=p.locator('.ig-stat-bars progress');assert bars.count()==6
 for i,(key,v) in enumerate(zip(keys,chosen)):
  expected=float(v)/maxima[key]*100
  assert abs(float(bars.nth(i).get_attribute('value'))-expected)<.001
  row=p.locator(f'.ig-stat-card[data-stat-key={key}]')
  assert row.locator('.ig-stat-current').inner_text()==str(v)
  assert row.locator('.ig-stat-max').inner_text()=='/ '+str(int(maxima[key]))
  assert str(int(maxima[key])) in bars.nth(i).get_attribute('aria-valuetext')
  assert '不含召唤物' in bars.nth(i).get_attribute('aria-valuetext')
 assert p.locator('.ig-mobility [data-stat-key=movement] b').inner_text()=='4'
 assert p.locator('.ig-mobility [data-stat-key=jump] b').inner_text()=='2'
 assert p.locator('.ig-mobility progress,.ig-mobility em,.ig-mobility .ig-stat-max').count()==0
 positions=p.locator('.ig-stat-card').evaluate_all('(els)=>els.map(e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y}))')
 assert positions[0]['y']==positions[1]['y']<positions[2]['y']==positions[3]['y']<positions[4]['y']==positions[5]['y']
 assert positions[0]['x']==positions[2]['x']==positions[4]['x']<positions[1]['x']==positions[3]['x']==positions[5]['x']
 check_canvas_stats(p)
 for theme in range(2):
  assert p.locator('.ig-stat-current').first.evaluate("el=>{const s=getComputedStyle(el),m=getComputedStyle(el.closest('.ig-stat-card').querySelector('.ig-stat-max'));return Number(s.fontWeight)>=700&&s.color!==m.color}")
  p.locator('[data-action=theme]').click()
 p.locator('.ig-nav [data-ig-jump=topText]').click();p.get_by_label('顶部自定义文字',exact=True).fill('交流群：123456789');ready(p)
 p.locator('.ig-nav [data-ig-jump=layout]').click();p.locator('#ig-layout-select').select_option('topText')
 for key,v in [('w','500'),('h','40'),('x','1000'),('y','0')]:p.locator(f'[data-ig-rect={key}]').fill(v);ready(p)
 bound=p.evaluate('groupBounds.at(-1)');assert bound['top']>=3 and bound['bottom']<=37,bound
 p.locator('.ig-nav [data-ig-jump=typography]').click();p.get_by_label('正文字体',exact=True).select_option('serif');ready(p)
 check_canvas_stats(p)
 bound=p.evaluate('groupBounds.at(-1)');assert bound['top']>=3 and bound['bottom']<=37,bound
 with p.expect_download() as dl:p.locator('[data-ig=export]').first.click()
 dl.value.save_as(OUT/'infographic-v114-stats.png')
 p.locator('.ig-nav [data-ig-jump=stats]').click();p.screenshot(path=str(OUT/'infographic-v114-stats-editor.png'))
 p.set_viewport_size({'width':390,'height':844});assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 p.reload();ready(p);assert p.locator('.ig-stat-bars progress').count()==6
 assert not errors,errors;b.close()
print(json.dumps({'status':'passed','referenceCharacters':len(reference),'excludedEntries':len(chars)-len(reference),'maxima':maxima,'checks':['summons and summoned companions excluded from reference maxima','six current/max values and percentages independently verified in editor and canvas','current values highlighted in light/dark editor and PNG with distinct, non-overlapping text','two-column six-stat order, separate mobility values without percentages','group text actual glyph bounds including serif at canvas top','offline PNG export, reload, mobile layout']},ensure_ascii=False))
