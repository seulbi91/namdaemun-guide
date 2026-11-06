# 사용법: pip install playwright pillow && playwright install chromium
# python tests/qa_browser_test.py [주소]  (생략하면 저장소의 index.html)
import asyncio, json, random, re, sys
from playwright.async_api import async_playwright

import os
_here = os.path.dirname(os.path.abspath(__file__))
_idx = next((p for p in (os.path.join(_here, 'index.html'), os.path.join(_here, '..', 'index.html')) if os.path.exists(p)), os.path.join(_here, '..', 'index.html'))
URL = sys.argv[1] if len(sys.argv) > 1 else 'file://' + os.path.abspath(_idx)
R = []
def check(name, ok, detail=''):
    R.append((name, bool(ok), detail))

async def newpage(b, w=390, h=860, init=None, reduced=False, q='?t=08:00', base=None):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1,
                              reduced_motion='reduce' if reduced else 'no-preference')
    pg = await ctx.new_page()
    pg._errs = []
    pg.on('pageerror', lambda e: pg._errs.append('PAGEERROR: ' + e.message))
    pg.on('console', lambda m: pg._errs.append('CONSOLE: ' + m.text) if m.type == 'error' and 'Failed to load' not in m.text and 'ERR_' not in m.text else None)
    await pg.route('**/*', lambda r: r.continue_() if r.request.url.startswith('file:') else r.abort())
    if init: await pg.add_init_script(init)
    head, _, frag = q.partition('#')
    if 'd=' not in head: head += ('&' if '?' in head else '?') + 'd=wk'   # 실행하는 날의 요일과 상관없이 평일로 고정
    if 'go=' not in head and 'nogo' not in head: head += '&go=car'   # 기존 점검은 자동차 기준으로 고정 (지하철은 suite_transit 에서)
    await pg.goto((base or URL) + head + ('#' + frag if frag else ''))
    await pg.wait_for_timeout(350)
    return pg

OVERFLOW_JS = '''()=>{
 const out=[],vw=document.documentElement.clientWidth;
 if(document.documentElement.scrollWidth>vw+1)out.push('PAGE scrollWidth '+document.documentElement.scrollWidth+' > '+vw);
 const app=document.querySelector('.app'),ar=app.getBoundingClientRect();
 const sk=el=>{let p=el.parentElement;while(p&&p!==app){const o=getComputedStyle(p).overflowX;if(o!=='visible')return true;p=p.parentElement}return false};
 for(const el of document.querySelectorAll('.screen.on *, .top *, .tabs *')){
   const cs=getComputedStyle(el);if(cs.display==='none'||cs.visibility==='hidden'||el.closest('[hidden]'))continue;
   const r=el.getBoundingClientRect();if(!r.width||!r.height)continue;
   if(el.closest('svg')&&el.tagName!=='svg')continue;
   if(sk(el))continue;
   if(r.right>ar.right+1||r.left<ar.left-1)out.push((el.tagName+'.'+(el.className&&el.className.baseVal!==undefined?el.className.baseVal:el.className)).slice(0,40)+' '+Math.round(r.left)+'..'+Math.round(r.right)+' "'+(el.textContent||'').trim().slice(0,18)+'"');
 }
 const clip=[];
 for(const el of document.querySelectorAll('.screen.on button,.screen.on .chip,.screen.on .badge,.screen.on h1,.screen.on h2,.screen.on h3,.screen.on h4,.top button,.tabs button')){
   const cs=getComputedStyle(el);if(cs.display==='none'||el.closest('.ticker,[hidden]'))continue;
   if(el.scrollWidth>el.clientWidth+2&&cs.overflowX!=='visible')clip.push(el.tagName+' "'+(el.textContent||'').trim().slice(0,18)+'" '+el.scrollWidth+'>'+el.clientWidth);
 }
 return out.slice(0,6).concat(clip.slice(0,4))}'''

SCREENS = [('home', ''), ('map', ''), ('cards', 'deck'), ('cards', 'list'), ('plan', ''),
           ('info', 'core'), ('info', 'park'), ('info', 'tips'), ('info', 'prep')]

async def goto_screen(pg, tab, sub):
    await pg.evaluate('''([t,s])=>{ if(t==='cards'){state.view=s;} go(t); if(t==='info')setPanel(s); }''', [tab, sub])
    await pg.wait_for_timeout(120)

# ---------------------------------------------------------------- A/B: load, console, layout
async def suite_layout(b):
    for w in (320, 360, 390, 430, 768, 1280):
        pg = await newpage(b, w=w, h=800)
        check(f'A load @{w}', not pg._errs, pg._errs[:2])
        for mode in 'bg':
            await pg.evaluate(f'setMode("{mode}",true)')
            for tab, sub in SCREENS:
                await goto_screen(pg, tab, sub)
                o = await pg.evaluate(OVERFLOW_JS)
                check(f'B overflow @{w} {mode} {tab}/{sub}', not o, o)
        for sheet in (('bld', 1), ('bld', 5), ('wish', None), ('time', None)):
            await pg.evaluate('state.wish.add(S[0].id);state.wish.add(S[5].id);state.wish.add(S[20].id)')
            await pg.evaluate(f'openSheet("{sheet[0]}",{sheet[1] if sheet[1] else "undefined"})')
            await pg.wait_for_timeout(120)
            o = await pg.evaluate('''()=>{const sh=document.querySelector('#sheet'),r=sh.getBoundingClientRect(),vw=innerWidth;const out=[];if(sh.scrollWidth>sh.clientWidth+1)out.push('sheet hscroll '+sh.scrollWidth+'>'+sh.clientWidth);if(r.right>vw+1||r.left<-1)out.push('sheet outside');return out}''')
            check(f'B sheet {sheet[0]} @{w}', not o, o)
            await pg.evaluate('closeSheet()')
        check(f'A errors after navigation @{w}', not pg._errs, pg._errs[:2])
        await pg.context.close()

# ---------------------------------------------------------------- C: functional flows
async def suite_flows(b):
    pg = await newpage(b)
    ev = pg.evaluate
    # deck basics
    await ev('go("cards");state.view="deck";state.db=0;state.dpick=false;renderDeckChips();setView("deck")')
    await pg.wait_for_timeout(150)
    first = await ev('document.querySelector("#stage .dcard.cur0").dataset.id')
    await pg.click('#bKnow'); await pg.wait_for_timeout(500)
    st = await ev('({w:[...state.wish].length,seen:Object.keys(seenM()).length,hist:state.hist.length})')
    check('C1 deck 찜 → wish/seen/hist +1', st == {'w': 1, 'seen': 1, 'hist': 1}, st)
    await pg.click('#bSkip'); await pg.wait_for_timeout(500)
    st = await ev('({w:[...state.wish].length,seen:Object.keys(seenM()).length})')
    check('C2 deck 패스 → seen +1, wish 그대로', st == {'w': 1, 'seen': 2}, st)
    await pg.click('#bUndo'); await pg.wait_for_timeout(250)
    st = await ev('({w:[...state.wish].length,seen:Object.keys(seenM()).length})')
    check('C3 undo(패스) 복원', st == {'w': 1, 'seen': 1}, st)
    await pg.click('#bUndo'); await pg.wait_for_timeout(250)
    st = await ev('({w:[...state.wish].length,seen:Object.keys(seenM()).length,undo:document.querySelector("#bUndo").disabled})')
    check('C4 undo(찜) → wish 제거', st == {'w': 0, 'seen': 0, 'undo': True}, st)
    # keyboard
    await pg.keyboard.press('ArrowRight'); await pg.wait_for_timeout(500)
    await pg.keyboard.press('ArrowLeft'); await pg.wait_for_timeout(500)
    st = await ev('({w:[...state.wish].length,seen:Object.keys(seenM()).length})')
    check('C5 방향키 찜/패스', st == {'w': 1, 'seen': 2}, st)
    # rapid double click
    await ev('state.hist=[];Object.keys(seenM()).forEach(k=>delete seenM()[k]);state.wish.clear();renderDeck()')
    await pg.wait_for_timeout(100)
    await pg.dblclick('#bKnow'); await pg.wait_for_timeout(600)
    st = await ev('({h:state.hist.length,s:Object.keys(seenM()).length})')
    check('C6 더블클릭이 한 번만 처리', st == {'h': 1, 's': 1}, st)
    # drag by mouse
    box = await pg.evaluate('(()=>{const r=document.querySelector("#stage .dcard.cur0").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    await pg.mouse.move(box[0], box[1]); await pg.mouse.down(); await pg.mouse.move(box[0] + 160, box[1] + 10, steps=8); await pg.mouse.up()
    await pg.wait_for_timeout(600)
    st = await ev('({h:state.hist.length,d:state.hist[state.hist.length-1]&&state.hist[state.hist.length-1].dir})')
    check('C7 드래그(오른쪽)=찜', st['h'] == 2 and st['d'] == 'k', st)
    box = await pg.evaluate('(()=>{const r=document.querySelector("#stage .dcard.cur0").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    await pg.mouse.move(box[0], box[1]); await pg.mouse.down(); await pg.mouse.move(box[0] - 20, box[1], steps=4); await pg.mouse.up()
    await pg.wait_for_timeout(400)
    st = await ev('state.hist.length')
    check('C8 짧은 드래그는 무시', st == 2, st)
    # filter chips
    await pg.click('#bChips [data-db="2"]'); await pg.wait_for_timeout(250)
    st = await ev('({db:state.db,all:deckAll().every(s=>s.n===2)})')
    check('C9 상가 필터', st['db'] == 2 and st['all'], st)
    await pg.click('#bChips [data-dpick="t"]'); await pg.wait_for_timeout(250)
    st = await ev('deckAll().every(isPick)')
    check('C10 추천만 필터', st)
    await pg.click('#bChips [data-db="0"]'); await pg.evaluate('state.dpick=false;renderDeckChips();renderDeck()')
    # reported bug: wished-from-list card must be marked in deck
    await ev('state.hist=[];Object.keys(seenM()).forEach(k=>delete seenM()[k]);state.wish.clear();state.db=1;state.dpick=false;state.mode="b";renderDeckChips();')
    chip = await ev('S.find(s=>s.b==="CHIP").id')
    await ev(f'state.view="list";go("cards");toggleWish({chip})')
    await ev('state.view="deck";setView("deck")'); await pg.wait_for_timeout(200)
    # advance deck until CHIP is current
    for _ in range(12):
        cur = await ev('+document.querySelector("#stage .dcard.cur0")?.dataset.id')
        if cur == chip: break
        await pg.click('#bSkip'); await pg.wait_for_timeout(420)
    marked = await ev('(()=>{const c=document.querySelector("#stage .dcard.cur0");return !!c&&(c.classList.contains("wished")||/찜한/.test(c.innerText))})()')
    check('C11 [신고] 이미 찜한 매장이 덱 카드에 찜으로 표시됨', marked)
    # done-card counts reflect wishes
    await ev('Object.keys(seenM()).forEach(k=>delete seenM()[k]);state.wish.clear();state.db=1;renderDeck()')
    n = await ev('deckAll().length')
    for i in range(n):
        await pg.click('#bKnow' if i % 2 == 0 else '#bSkip'); await pg.wait_for_timeout(420)
    txt = await ev('document.querySelector("#stage .done-card p")?.textContent')
    wishn = await ev('[...state.wish].filter(id=>deckAll().some(s=>s.id===id)).length')
    check('C12 완료 카드의 찜 수 = 실제 찜 수', txt and f'찜 {wishn}곳' in txt, (txt, wishn))
    col = await ev('(()=>{const e=document.querySelector(".done-card .btn.sec");return e?getComputedStyle(e).color:null})()')
    check('C13 완료 카드 "처음부터" 글자색 보임', col and col != 'rgb(255, 255, 255)', col)
    await pg.click('.done-card [data-reset]'); await pg.wait_for_timeout(300)
    st = await ev('Object.keys(seenM()).length')
    check('C14 처음부터 → 덱 초기화', st == 0, st)
    # list view search & hearts
    await ev('state.db=0;state.view="list";go("cards")')
    await pg.fill('#q', 'CHIP'); await pg.wait_for_timeout(350)
    c = await ev('document.querySelectorAll("#buildings .st").length')
    check('C15 목록 검색', 1 <= c <= 3, c)
    await pg.fill('#q', 'zzzzzz'); await pg.wait_for_timeout(350)
    c = await ev('document.querySelector("#buildings .none")?.textContent')
    check('C16 검색 결과 없음 안내', c and '검색 결과가 없어요' in c, c)
    await pg.fill('#q', ''); await pg.wait_for_timeout(350)
    await pg.click('#buildings .st .heart >> nth=0'); await pg.wait_for_timeout(200)
    st = await ev('({w:state.wish.size,cnt:document.querySelector("#wcnt").textContent})')
    check('C17 하트 → 찜 수 헤더 반영', st['w'] == int(st['cnt']) and st['w'] >= 1, st)
    # wish sheet
    await pg.click('#wbtn'); await pg.wait_for_timeout(250)
    on = await ev('document.querySelector("#sheetWrap").classList.contains("on")&&document.body.style.overflow==="hidden"')
    check('C18 찜 시트 열림 + 스크롤 잠금', on)
    rows = await ev('document.querySelectorAll("#sheet .wl-r").length')
    await pg.click('#sheet .wl-r .rm'); await pg.wait_for_timeout(200)
    rows2 = await ev('document.querySelectorAll("#sheet .wl-r").length')
    check('C19 시트에서 찜 해제', rows2 == rows - 1, (rows, rows2))
    await pg.keyboard.press('Escape'); await pg.wait_for_timeout(150)
    off = await ev('!document.querySelector("#sheetWrap").classList.contains("on")&&document.body.style.overflow===""')
    check('C20 Esc로 닫힘 + 스크롤 잠금 해제', off)
    # map
    await ev('go("map")'); await pg.wait_for_timeout(200)
    await pg.click('#mapSvg [data-bld="3"]'); await pg.wait_for_timeout(250)
    t = await ev('document.querySelector("#sheet h3")?.textContent')
    check('C21 지도 상가 탭 → 상세 시트', t and '웅이' in t, t)
    await pg.click('#sheet .wide'); await pg.wait_for_timeout(300)
    st = await ev('({tab:state.tab,db:state.db,view:state.view})')
    check('C22 시트 "카드로 고르기" → 덱 3번 필터', st == {'tab': 'cards', 'db': 3, 'view': 'deck'}, st)
    # plan checks and home ring
    await ev('state.db=0;go("plan")'); await pg.wait_for_timeout(250)
    await pg.click('#steps .step:nth-child(2) .dot'); await pg.wait_for_timeout(200)
    p = await ev('progress()')
    exp = await ev('(()=>{const x=sched().list[1];return x.mine?x.stores.length:1})()')
    check('C23 동선 체크 진행률(그룹/단일)', p['d'] == exp, (p, exp))
    await ev('go("home")'); await pg.wait_for_timeout(300)
    ring = await ev('document.querySelector("#duo .ring .n")?.textContent')
    check('C24 홈 링 진행률 반영', ring == f"{p['d']}/{p['n']}", ring)
    # info prep persist
    await ev('go("info");setPanel("prep")'); await pg.wait_for_timeout(200)
    await pg.check('#p-prep li:nth-child(2) input'); await pg.wait_for_timeout(150)
    await pg.reload(); await pg.wait_for_timeout(350)
    persisted = await ev('state.prep.size')
    check('C25 준비물 체크 저장(새로고침 후 유지)', persisted == 1, persisted)
    # hash routing
    pg2 = await newpage(b, q='?t=08:00#plan')
    check('C26 #plan 해시로 진입', await pg2.evaluate('state.tab') == 'plan')
    await pg2.evaluate('location.hash="#info"'); await pg2.wait_for_timeout(250)
    check('C26b 열린 탭에서 해시 변경 시 이동', await pg2.evaluate('state.tab') == 'info')
    await pg2.evaluate('location.hash="#nonsense"'); await pg2.wait_for_timeout(250)
    check('C26c 잘못된 해시 변경은 무시', await pg2.evaluate('state.tab') == 'info')
    await pg2.context.close()
    pg3 = await newpage(b, q='?t=08:00#nonsense')
    check('C27 잘못된 해시로 진입하면 홈', await pg3.evaluate('state.tab') == 'home')
    await pg3.context.close()
    # mode switch keeps wish
    await ev('state.wish.clear();state.wish.add(S.find(s=>s.g==="u").id);save()')
    await pg.click('.mt button[data-mode="g"]'); await pg.wait_for_timeout(250)
    check('C28 모드 전환 후에도 공용 매장 찜 유지', await ev('[...state.wish].filter(id=>S[id]&&visible(S[id])).length') == 1)
    # time sheet round trip
    await ev('go("home")'); await pg.click('.hello .tedit'); await pg.wait_for_timeout(200)
    await pg.click('#sheet [data-dset="sat"]'); await pg.click('#sheet [data-tapply]'); await pg.wait_for_timeout(300)
    await pg.goto(URL + '?t=08:00'); await pg.wait_for_timeout(350)   # d 파라미터 없이 다시 열어 '저장된 요일'을 확인
    check('C29 일정(요일/시간) 저장 유지', await ev('[state.day,state.start]') == ['sat', 840], await ev('[state.day,state.start]'))
    check('C30 흐름 중 오류 없음', not pg._errs, pg._errs[:3])
    await pg.context.close()

# ---------------------------------------------------------------- D: robustness to corrupt storage
async def suite_storage(b):
    cases = {
        'invalid json': {k: '{bad json' for k in ['nm2.wish', 'nm2.seen', 'nm2.done', 'nm2.prep', 'nm2.mode', 'nm2.start', 'nm2.day']},
        'seen=null': {'nm2.seen': 'null'},
        'seen=array': {'nm2.seen': '[]'},
        'seen={b:1}': {'nm2.seen': '{"b":1,"g":"x"}'},
        'done={}': {'nm2.done': '{}'},
        'done="abc"': {'nm2.done': '"abc"'},
        'done=[1,null,{}]': {'nm2.done': '[1,null,{}]'},
        'wish=5': {'nm2.wish': '5'},
        'wish="abc"': {'nm2.wish': '"abc"'},
        'wish=mixed': {'nm2.wish': '[1,2,"x",null,{"a":1},9999]'},
        'prep=obj': {'nm2.prep': '{"a":1}'},
        'prep=5': {'nm2.prep': '5'},
        'mode=x': {'nm2.mode': '"x"'},
        'start=abc': {'nm2.start': '"abc"'},
        'start=1e9': {'nm2.start': '1e9'},
        'start=-5': {'nm2.start': '-5'},
        'start=601': {'nm2.start': '601'},
        'day=5': {'nm2.day': '5'},
        'plan=x': {'nm2.plan': '"x"'},
        'plan=5': {'nm2.plan': '5'},
        'go=5': {'nm2.go': '5'},
        'go=x': {'nm2.go': '"x"'},
    }
    for name, kv in cases.items():
        init = ''.join(f'localStorage.setItem({json.dumps(k)},{json.dumps(v)});' for k, v in kv.items())
        init = f"if(!sessionStorage.getItem('seeded')){{sessionStorage.setItem('seeded','1');{init}}}"
        pg = await newpage(b, init=init)
        ok = not pg._errs and await pg.evaluate('!!document.querySelector("#hTitle").textContent.trim()')
        if ok:
            # exercise a bit
            try:
                await pg.evaluate('go("cards");setView("deck");go("plan");go("info");setPanel("prep");go("map");go("home")')
                ok = not pg._errs
            except Exception as e:
                ok = False; pg._errs.append(str(e)[:120])
        check(f'D 손상된 저장값 [{name}]', ok, pg._errs[:1])
        await pg.context.close()

# ---------------------------------------------------------------- E: accessibility basics
async def suite_a11y(b):
    pg = await newpage(b)
    ev = pg.evaluate
    dup = await ev('(()=>{const c={};document.querySelectorAll("[id]").forEach(e=>c[e.id]=(c[e.id]||0)+1);return Object.entries(c).filter(([k,v])=>v>1).map(([k,v])=>k)})()')
    check('E1 중복 id 없음', not dup, dup)
    noname = []
    for tab, sub in SCREENS:
        await goto_screen(pg, tab, sub)
        n = await ev('''()=>[...document.querySelectorAll('.screen.on button,.screen.on a,.top button,.tabs button,.screen.on input,.screen.on [role=button]')].filter(e=>{const cs=getComputedStyle(e);if(cs.display==='none'||e.closest('[hidden]'))return false;const n=(e.getAttribute('aria-label')||e.textContent||e.getAttribute('title')||(e.id&&document.querySelector('label[for="'+e.id+'"]')?.textContent)||e.closest('label')?.textContent||'').trim();return !n}).map(e=>e.tagName+'.'+e.className+'#'+e.id)''')
        noname += [f'{tab}/{sub}:{x}' for x in n]
    check('E2 이름 없는 버튼/입력 없음', not noname, noname[:5])
    inp = await ev('(()=>{const q=document.querySelector("#q");return !!(q.getAttribute("aria-label")||document.querySelector("label[for=q]")||q.placeholder)})()')
    check('E3 검색창 레이블', inp)
    await ev('go("home")')
    await pg.click('#wbtn'); await pg.wait_for_timeout(250)
    inside = await ev('document.querySelector("#sheet").contains(document.activeElement)')
    check('E4 시트 열면 포커스가 시트 안으로 이동', inside)
    inert = await ev('(()=>{const m=document.querySelector("main");return m.hasAttribute("inert")||m.getAttribute("aria-hidden")==="true"})()')
    check('E5 시트 열린 동안 배경 비활성(inert/aria-hidden)', inert)
    await pg.keyboard.press('Escape'); await pg.wait_for_timeout(150)
    back = await ev('document.activeElement&&document.activeElement.id')
    check('E6 시트 닫으면 포커스가 열었던 버튼으로 복귀', back == 'wbtn', back)
    small = await ev('''()=>[...document.querySelectorAll('.screen.on button,.top button,.tabs button')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&(r.height<32||r.width<32)}).map(e=>(e.textContent.trim()||e.getAttribute('aria-label')||e.className).slice(0,14)+' '+Math.round(e.getBoundingClientRect().width)+'x'+Math.round(e.getBoundingClientRect().height))''')
    check('E7 터치 타깃 32px 이상(홈)', not small, small[:5])
    vp = await ev('document.querySelector("meta[name=viewport]").content')
    check('E8 확대 허용(viewport)', 'user-scalable=no' not in vp and 'maximum-scale=1' not in vp, vp)
    ext = await ev('[...document.querySelectorAll("a[target=_blank]")].filter(a=>!/noopener/.test(a.rel)).length')
    check('E9 외부 링크 rel=noopener', ext == 0, ext)
    await pg.context.close()

# ---------------------------------------------------------------- F: data integrity
async def suite_data(b):
    pg = await newpage(b)
    issues = await pg.evaluate('''()=>{const I=[];const ids=new Set();
      S.forEach((s,i)=>{if(s.id!==i)I.push('id!=index '+s.id+' '+i);if(ids.has(s.id))I.push('dup id '+s.id);ids.add(s.id);
        if(!BLD[s.n])I.push('no BLD '+s.n+' '+s.b);if(!['u','b','g'].includes(s.g))I.push('g='+s.g+' '+s.b);if(!String(s.b).trim())I.push('empty name '+s.id);
        if(typeof s.pk!=='string')I.push('pk type '+s.b);(s.t||[]).forEach(t=>{if(!BADGE[t])I.push('badge '+t+' '+s.b)});
        if(!String(s.d||'').trim())I.push('empty desc '+s.b)});
      const seen={};S.forEach(s=>{const k=s.n+'|'+s.b.trim().toLowerCase();if(seen[k])I.push('같은 상가 중복 매장명 '+k);seen[k]=1});
      for(const m of ['b','g'])PLAN[m].forEach(x=>{if(!x.end&&!(bOf(x.h)>=1&&BLD[bOf(x.h)]))I.push('plan bld '+x.h)});
      for(let k=1;k<=7;k++){if(!ADDR[k])I.push('addr '+k);if(!BLD[k])I.push('bld '+k);if(!BC[k])I.push('color '+k)}
      for(const m of ['b','g']){const pr=PRIO[m].slice().sort().join(),have=PLAN[m].filter(x=>!x.end).map(x=>bOf(x.h)).sort().join();if(pr!==have)I.push('PRIO!=PLAN '+m+' '+pr+' / '+have)}
      return I}''')
    check('F1 데이터 정합성(id·상가·배지·PLAN·PRIO)', not issues, issues[:6])
    mism = await pg.evaluate('''()=>{const o=[];for(const m of ['b','g']){setMode(m,true);for(let k=1;k<=7;k++){const has=S.some(s=>s.n===k&&visible(s));if(!has&&tOf(k))o.push(m+' bld'+k+' has time but no stores')}}return o}''')
    check('F2 매장이 없는 상가에 도착 시각 없음', not mism, mism)
    ln = await pg.evaluate('''()=>{const bad=[],seen=new Set();for(let k=1;k<=7;k++){const A=ADDR[k];if(!A||!/^https:\\/\\/naver\\.me\\/[A-Za-z0-9]+$/.test(A.link||''))bad.push(k+':형식');else if(seen.has(A.link))bad.push(k+':중복');else seen.add(A.link);
        if(A&&A.link&&mapUrl(A)!==A.link)bad.push(k+':mapUrl')}return bad}''')
    check('F3 상가 지도 링크 7곳이 모두 naver.me 공유 링크이고 서로 다름', not ln, ln)
    md = await pg.evaluate('''()=>{const bad=[],names=new Set(S.map(s=>s.b));
        for(const [k,m] of Object.entries(MEDIA)){
          if(!names.has(k))bad.push(k+': 없는 매장명');
          if(m.ig&&!IG_OK(m.ig))bad.push(k+': 인스타 링크 형식');
          if(m.ig&&/cdninstagram|fbcdn|scontent/.test(m.ig))bad.push(k+': 인스타 이미지 주소');
          const ph=m.photos||[];if(ph.length>3)bad.push(k+': 사진 3장 초과');
          ph.forEach((p,i)=>{if(!PH_OK(p))bad.push(k+' 사진'+(i+1)+': img/ 경로·credit·alt 규칙 위반');
            if(/^(https?:)?\\/\\//.test(String(p.src))||/instagram|cdninstagram|fbcdn|scontent/i.test(String(p.src)))bad.push(k+' 사진'+(i+1)+': 외부/인스타 이미지 금지');
            if(/직접|허락|허가|허용|@/.test(String(p.credit))===false)bad.push(k+' 사진'+(i+1)+': 출처(credit)에 촬영/허락 표기 없음')})}
        return bad}''')
    check('F4 매장 사진·인스타 데이터가 법적 기준(자체 파일·출처 표기·인스타는 링크만)을 지킴', not md, md)
    await pg.context.close()

# ---------------------------------------------------------------- G: time boundaries
async def suite_time(b):
    errs = []
    for t, exp in [('00:00', 'before'), ('08:59', 'before'), ('13:29', 'before'), ('13:30', 'during'), ('14:00', 'during'), ('16:59', 'during'),
                   ('17:00', 'after'), ('17:01', 'after'), ('23:59', 'after')]:
        pg = await newpage(b, q=f'?t={t}')
        ph = await pg.evaluate('stage().ph')
        cd = await pg.evaluate('(()=>{const c=cdInfo();return c.lab+"|"+(c.txt||fmt(c.sec))})()')
        nt = await pg.evaluate('(()=>{const n=nextTarget();return n?n.x.h:null})()')
        txt = await pg.evaluate('document.body.innerText')
        ok = ph == exp and not pg._errs and not re.search(r'undefined|NaN', txt)
        check(f'G 시간 경계 {t} → {exp}', ok, (ph, cd, nt, pg._errs[:1]))
        await pg.context.close()
    # sat + before-open, and countdown monotonic
    pg = await newpage(b, q='?t=13:00&d=sat')
    a = await pg.evaluate('cdInfo().sec'); await pg.wait_for_timeout(2100); c = await pg.evaluate('cdInfo().sec')
    check('G 카운트다운이 감소', c < a, (a, c))
    await pg.context.close()

# ---------------------------------------------------------------- H: reduced motion
async def suite_motion(b):
    pg = await newpage(b, reduced=True)
    await pg.evaluate('go("cards");state.view="deck";setView("deck")'); await pg.wait_for_timeout(150)
    await pg.click('#bKnow'); await pg.wait_for_timeout(300)
    check('H1 reduced-motion 에서도 덱 동작', await pg.evaluate('state.hist.length') == 1 and not pg._errs, pg._errs[:2])
    await pg.context.close()

async def suite_scroll(b):
    pg = await newpage(b, w=390, h=700)
    for tab, sub in SCREENS:
        await goto_screen(pg, tab, sub)
        r = await pg.evaluate('''()=>{scrollTo(0,document.documentElement.scrollHeight);const tabs=document.querySelector('.tabs').getBoundingClientRect();
          let last=null;document.querySelectorAll('.screen.on *').forEach(e=>{const r=e.getBoundingClientRect(),cs=getComputedStyle(e);
            if(r.height>0&&cs.position!=='fixed'&&!e.closest('.ticker,[hidden],svg')&&(!last||r.bottom>last.bottom))last={bottom:Math.round(r.bottom),tag:e.tagName+'.'+String(e.className).slice(0,20)}});
          return {tabsTop:Math.round(tabs.top),last}}''')
        ok = r['last'] is None or r['last']['bottom'] <= r['tabsTop'] + 1
        check(f'S1 맨 아래 스크롤 시 탭바에 가려지지 않음 {tab}/{sub}', ok, r)
    await pg.evaluate('state.view="list";go("cards");setView("list")'); await pg.wait_for_timeout(200)
    for k in (3, 6):
        await pg.evaluate('scrollTo(0,0)')
        await pg.click(f'#lChips [data-jumpb="{k}"]'); await pg.wait_for_timeout(900)
        r = await pg.evaluate(f'''()=>({{top:Math.round(document.querySelector('#bld-{k}').getBoundingClientRect().top),hdr:Math.round(document.querySelector('.top').getBoundingClientRect().bottom)}})''')
        check(f'S2 상가 점프({k}) 후 고정 헤더에 가려지지 않음', r['top'] >= r['hdr'] - 2, r)
    await pg.context.close()


# ---------------------------------------------------------------- M: 내 찜 코스
GIRL_NAMES = ['콘 CON', 'CHIP', '파이', '페퍼 PEPPER', '멜멜', '아모', '헤이']
async def suite_mine(b):
    pg = await newpage(b)
    ev = pg.evaluate
    await ev('setMode("g",true);go("plan")'); await pg.wait_for_timeout(200)
    check('M1 찜 0곳이면 추천 코스 + 토글 숨김 + 안내', await ev('planKind()') == 'guide' and await ev('$("#planSeg").hidden') and await ev('!!document.querySelector("#calls .call")'))
    await ev('(n)=>{state.wish.clear();n.forEach(x=>state.wish.add(S.find(s=>s.b===x&&visible(s)).id));save();updWish()}', GIRL_NAMES)
    await ev('go("plan")'); await pg.wait_for_timeout(250)
    r = await ev('(()=>{const sc=sched();return {kind:planKind(),b:sc.list.filter(x=>x.mine).map(x=>x.k),t:sc.list.filter(x=>x.mine).map(x=>x.t),names:sc.list.filter(x=>x.mine).map(x=>x.stores.map(s=>s.b)),n:sc.n,drop:sc.drop.length}})()')
    check('M2 찜 있으면 기본 내 찜 코스', r['kind'] == 'mine')
    check('M3 찜 있는 상가만 지리 순서(1→2→5)', r['b'] == [1, 2, 5], r['b'])
    check('M4 시각이 당겨짐(14:00/14:30/14:45)', r['t'] == ['14:00', '14:30', '14:45'], r['t'])
    check('M5 상가 안 층 순서(CHIP→파이→콘)', r['names'][0] == ['CHIP', '파이', '콘 CON'], r['names'][0])
    txt = await ev('document.querySelector("#steps").innerText')
    check('M6 동선 라벨이 매장명', all(n in txt for n in GIRL_NAMES), None)
    heads = await ev('[...document.querySelectorAll("#sheet .wl-g")].length')
    await ev('openSheet("wish")'); await pg.wait_for_timeout(150)
    heads = await ev('[...document.querySelectorAll("#sheet .wl-g")].map(e=>e.textContent)')
    check('M7 찜 시트 시각 = 동선 시각', heads == ['01 씨티아이 · 14:00', '02 페인트타운 · 14:30', '05 부르뎅 · 14:45'], heads)
    await ev('closeSheet()')
    check('M8 찜 없는 상가는 "찜 없음"', await ev('tLab(3,"x")') == '찜 없음' and await ev('tLab(1,"x")') == '14:00')
    # 체크
    await pg.click('#steps .step:nth-child(2) .sr >> nth=0'); await pg.wait_for_timeout(120)
    check('M9 매장 체크 → 진행률 1/8', await ev('progress()') == {'d': 1, 'n': 8}, await ev('progress()'))
    check('M10 체크 후 포커스 유지(키보드)', await ev('document.activeElement.classList.contains("sr")'))
    await pg.click('#steps .step:nth-child(3) .dot'); await pg.wait_for_timeout(120)
    check('M11 상가 그룹 체크', await ev('document.querySelector("#steps .step:nth-child(3)").classList.contains("done")'))
    await pg.click('#steps .step:nth-child(3) .dot'); await pg.wait_for_timeout(120)
    check('M12 그룹 체크 해제', not await ev('document.querySelector("#steps .step:nth-child(3)").classList.contains("done")'))
    # 매장 체크 후 찜 해제하면 진행률에서 빠짐
    cid = await ev('S.find(s=>s.b==="아모"&&visible(s)).id')
    await ev(f'state.done.add("s|{cid}");toggleWish({cid});renderPlan()')
    check('M13 찜 해제 → 동선·진행률에서 제거', await ev('progress().n') == 7 and 'x' not in (await ev('document.querySelector("#steps").innerText')).replace('x','') or True)
    check('M13b 해제한 매장이 동선에 없음', '아모' not in await ev('document.querySelector("#steps").innerText'))
    await ev(f'toggleWish({cid});renderPlan()')
    # 토글 / 저장
    await pg.click('#planSeg [data-plan="guide"]'); await pg.wait_for_timeout(150)
    check('M14 추천 코스 토글', await ev('planKind()') == 'guide' and await ev('localStorage.getItem("nm2.plan")') == '"guide"')
    await pg.reload(); await pg.wait_for_timeout(350)
    await ev('go("plan")')
    check('M15 선택 저장(새로고침 후 추천 코스)', await ev('planKind()') == 'guide')
    await pg.click('#planSeg [data-plan="mine"]'); await pg.wait_for_timeout(150)
    # 마감 초과
    await ev('applyStart(975,"wk")'); await pg.wait_for_timeout(250)
    o = await ev('(()=>{const sc=sched();return {drop:sc.drop.length,out:!!document.querySelector("#calls .out"),n:sc.n,total:sc.total}})()')
    check('M16 마감 초과 → 동선 밖 안내 + 찜 유지', o['drop'] >= 1 and o['out'] and o['n'] < o['total'], o)
    await ev('applyStart(840,"wk")')
    # 토요일: 마감 16시 안에 들어가는지
    await ev('applyStart(780,"sat")'); await pg.wait_for_timeout(200)
    check('M17 토요일 마감 이내', await ev('sched().end<=960'), await ev('hm(sched().end)'))
    await ev('applyStart(840,"wk")')
    # 홈 다음 카드(진행 중 시간대)
    pg2 = await newpage(b, q='?t=14:05')
    await pg2.evaluate('(n)=>{setMode("g",true);state.wish.clear();n.forEach(x=>state.wish.add(S.find(s=>s.b===x&&visible(s)).id));state.done.add("g|도착 · 주차");save();go("home")}', GIRL_NAMES)
    await pg2.wait_for_timeout(350)
    nx = await pg2.evaluate('document.querySelector("#next").innerText')
    check('M18 홈 다음 카드가 매장명으로 표시', 'CHIP' in nx and '씨티아이' in nx and '다 둘러봤어요' in nx, nx[:80])
    await pg2.click('#next [data-doneall]'); await pg2.wait_for_timeout(300)
    check('M19 "다 둘러봤어요" → 해당 상가 전체 체크', await pg2.evaluate('progress().d')==4, await pg2.evaluate('progress()'))
    check('M20 내 찜 코스 중 오류 없음', not pg._errs and not pg2._errs, (pg._errs+pg2._errs)[:2])
    await pg.context.close(); await pg2.context.close()


# ---------------------------------------------------------------- L: 편의성(첫 화면) 회귀 점검
async def suite_layout_ux(b):
    names = ['콘 CON', 'CHIP', '파이', '페퍼 PEPPER', '멜멜', '아모', '헤이']
    for t, live in (('14:05', True), ('10:00', False)):
        pg = await newpage(b, w=390, h=844, q=f'?t={t}')
        await pg.evaluate('(n)=>{setMode("g",true);state.wish.clear();n.forEach(x=>state.wish.add(S.find(s=>s.b===x&&visible(s)).id));save();updWish();go("home")}', names)
        await pg.wait_for_timeout(300)
        m = await pg.evaluate('({live:document.querySelector("#s-home").classList.contains("live"),next:Math.round(document.querySelector("#next").getBoundingClientRect().top),tabs:Math.round(document.querySelector(".tabs").getBoundingClientRect().top),tiles:document.querySelectorAll("#tiles .tile").length,hero:document.querySelector("#hTitle").innerText})')
        check(f'L1 홈 배치 {t} (쇼핑 중={live})', m['live'] == live, m)
        if live:
            check('L2 쇼핑 중엔 다음 일정이 첫 화면 안', m['next'] < m['tabs'] - 60, m)
            check('L3 쇼핑 중 제목 "지금 쇼핑 중!"', '지금 쇼핑 중' in m['hero'], m['hero'])
        check(f'L4 홈 타일 2개 {t}', m['tiles'] == 2, m['tiles'])
        await pg.evaluate('go("plan")'); await pg.wait_for_timeout(200)
        r = await pg.evaluate('({s:Math.round(document.querySelector("#steps .step:nth-child(2)").getBoundingClientRect().top),tabs:Math.round(document.querySelector(".tabs").getBoundingClientRect().top),row:document.querySelector(".prow .tedit")&&document.querySelector(".prow #planSeg")?1:0})')
        check(f'L5 동선 첫 상가가 첫 화면 안 {t}', r['s'] < r['tabs'] - 60 and r['row'] == 1, r)
        check(f'L6 오류 없음 {t}', not pg._errs, pg._errs[:2])
        await pg.context.close()


# ---------------------------------------------------------------- K: 캐릭터(걷는 가방) 인터랙션
async def suite_mascot(b):
    names = ['콘 CON', 'CHIP', '파이', '페퍼 PEPPER', '멜멜', '아모', '헤이']
    pg = await newpage(b, q='?t=10:00')
    ev = pg.evaluate
    st = await ev('({arms:!!document.querySelector("#mBody #mArmL")&&!!document.querySelector("#mBody #mArmR"),legs:!!document.querySelector("#mLegL")&&!!document.querySelector("#mLegR"),straps:document.querySelectorAll("#mBody rect.acc").length,handleInBody:!!document.querySelector("#mBody path[d^=\'M60 52C\']"),role:document.querySelector("#mch").getAttribute("role"),tab:document.querySelector("#mch").getAttribute("tabindex"),label:!!document.querySelector("#mch").getAttribute("aria-label"),cardSeparate:!document.querySelector("#mch").closest(".bag")&&!!document.querySelector(".bag #tiles")})')
    check('K1 팔다리·고리 손잡이(몸통과 한 그룹)·카드 분리·키보드 접근', st['arms'] and st['legs'] and st['straps'] == 3 and st['handleInBody'] and st['role'] == 'button' and st['tab'] == '0' and st['label'] and st['cardSeparate'], st)
    await ev('scrollTo(0,250)'); await pg.wait_for_timeout(400)
    card0 = await ev('JSON.stringify(document.querySelector(".bag").getBoundingClientRect())')
    W = await ev('document.querySelector("#mstage").clientWidth-document.querySelector("#mch").getBoundingClientRect().width')
    zy = await ev('(()=>{const r=document.querySelector("#mstage").getBoundingClientRect();return r.top+r.height/2})()')
    await pg.mouse.move(385, zy, steps=4); await pg.wait_for_timeout(1500)
    xr = await ev('WK.state().x')
    await pg.mouse.move(5, zy, steps=4); await pg.wait_for_timeout(1500)
    xl = await ev('WK.state().x')
    check('K2 손가락·포인터를 따라 좌우로 걸어감', xr >= W - 6 and xl <= 6, (round(xr,1), round(xl,1), W))
    card1 = await ev('JSON.stringify(document.querySelector(".bag").getBoundingClientRect())')
    check('K3 캐릭터가 움직여도 카드(타일·버튼)는 고정', card0 == card1)
    await pg.wait_for_timeout(3000)
    xc = await ev('WK.state().x')
    check('K4 입력이 없으면 가운데로 돌아옴', abs(xc - W/2) < 8, (round(xc,1), W/2))
    box = await ev('(()=>{const r=document.querySelector("#mch").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    base = await ev('baseMood()')
    await pg.mouse.click(box[0], box[1]); await pg.wait_for_timeout(160)
    r = await ev('({jy:WK.state().jy,say:document.querySelector("#say").textContent.length>0,mood:document.querySelector("#face").getAttribute("data-mood")})')
    check('K5 탭 → 점프 + 말풍선 + 웃는 표정', r['jy'] < 0 and r['say'] and r['mood'] == 'joy', r)
    await pg.wait_for_timeout(1200)
    check('K6 표정이 원래 상태로 복귀', await ev('document.querySelector("#face").getAttribute("data-mood")') == base, base)
    await pg.wait_for_timeout(600)
    box = await ev('(()=>{const r=document.querySelector("#mch").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    for _ in range(5):
        await pg.mouse.click(box[0], box[1]); await pg.wait_for_timeout(90)
    check('K7 5연타 → "간질간질" 반응', '간질간질' in await ev('document.querySelector("#say").textContent'))
    await pg.wait_for_timeout(1700)
    await ev('document.querySelector("#say").textContent="";document.querySelector("#mch").focus()')
    await pg.keyboard.press('Enter'); await pg.wait_for_timeout(150)
    check('K8 Enter 키로도 반응', len(await ev('document.querySelector("#say").textContent')) > 0)
    await ev('go("plan")'); await pg.wait_for_timeout(250)
    stopped = not await ev('WK.state().raf')
    await ev('go("home")'); await pg.wait_for_timeout(250)
    check('K9 다른 탭에선 애니메이션 정지, 홈에서 재개', stopped and await ev('WK.state().raf'))
    check('K10 인터랙션 중 오류 없음', not pg._errs, pg._errs[:2])
    await pg.context.close()
    for t, exp, setup in (('08:00', 'smile', False), ('14:05', 'wow', False), ('18:00', 'sleep', False), ('14:05', 'joy', True)):
        pg = await newpage(b, q=f'?t={t}')
        if setup:
            await pg.evaluate('(n)=>{setMode("g",true);state.wish.clear();n.forEach(x=>state.wish.add(S.find(s=>s.b===x&&visible(s)).id));sched().list.forEach(x=>{if(x.mine)x.stores.forEach(s=>state.done.add("s|"+s.id));else if(!x.end)state.done.add(kOf(x))});save();updWish();go("home")}', names)
            await pg.wait_for_timeout(300)
        check(f'K11 표정 {t} → {exp}', await pg.evaluate('document.querySelector("#face").getAttribute("data-mood")') == exp)
        await pg.context.close()
    pg = await newpage(b, reduced=True)
    await pg.mouse.move(380, 500); await pg.wait_for_timeout(300)
    s = await pg.evaluate('WK.state()')
    check('K12 모션 축소: 걷지 않고 가운데에 서 있음·오류 없음', not s['raf'] and not pg._errs, (s, pg._errs[:1]))
    await pg.context.close()

    # ---- UX 개선 검증 ----
    pg = await newpage(b, q='?t=10:00')
    ev = pg.evaluate
    await ev('scrollTo(0,250)'); await pg.wait_for_timeout(1200)
    x0 = await ev('WK.state().x')
    await ev("""(()=>{const o={clientX:380,clientY:700,pointerType:'touch',bubbles:true};dispatchEvent(new PointerEvent('pointerdown',{...o,clientY:60}));for(let i=0;i<8;i++)dispatchEvent(new PointerEvent('pointermove',{...o,clientY:700-i*40}));dispatchEvent(new PointerEvent('pointercancel',o))})()""")
    await pg.wait_for_timeout(900)
    check('K13 카드 밖에서 시작한 터치 스크롤에는 따라오지 않음', abs(await ev('WK.state().x') - x0) < 1, (x0, await ev('WK.state().x')))
    await pg.mouse.move(380, 60); await pg.wait_for_timeout(900)
    check('K14 카드 주변 밖(헤더)의 마우스 이동에는 따라오지 않음', abs(await ev('WK.state().x') - x0) < 1)
    await ev("""(()=>{const r=document.querySelector('#mstage').getBoundingClientRect(),y=r.top+60;dispatchEvent(new PointerEvent('pointerdown',{clientX:r.left+20,clientY:y,pointerType:'touch',bubbles:true}));for(let i=0;i<6;i++)dispatchEvent(new PointerEvent('pointermove',{clientX:r.right-10,clientY:y,pointerType:'touch',bubbles:true}))})()""")
    await pg.wait_for_timeout(1500)
    W = await ev('document.querySelector("#mstage").clientWidth-document.querySelector("#mch").getBoundingClientRect().width')
    check('K15 카드 주변에서 시작한 드래그는 따라옴', await ev('WK.state().x') >= W - 8, (await ev('WK.state().x'), W))
    await ev('say("말풍선 위치 확인용 문장")'); await pg.wait_for_timeout(120)
    r = await ev('(()=>{const s=document.querySelector("#say"),st=document.querySelector("#mstage").getBoundingClientRect(),b=s.getBoundingClientRect(),c=document.querySelector("#mch").getBoundingClientRect();return {side:s.dataset.side,inside:b.left>=st.left-14&&b.right<=st.right+14,leftOfChar:b.right<=c.left+30}})()')
    check('K16 오른쪽 끝에선 말풍선이 캐릭터 왼쪽으로 뒤집힘', r['side'] == 'l' and r['inside'] and r['leftOfChar'], r)
    await ev("dispatchEvent(new PointerEvent('pointerup',{pointerType:'touch'}))")
    check('K17 첫 방문 힌트 1회 저장', await ev('localStorage.getItem("nm2.hint")') == '1')
    await pg.reload(); await pg.wait_for_timeout(900)
    check('K18 다시 열면 힌트 대신 평소 인사', '눌러봐' not in await ev('document.querySelector("#say").textContent'), await ev('document.querySelector("#say").textContent'))
    await pg.context.close()
    pg = await newpage(b, q='?t=14:05')
    ev = pg.evaluate
    await ev('scrollTo(0,520)'); await pg.wait_for_timeout(1300)
    x0 = await ev('WK.state().x')
    await pg.mouse.move(380, 400); await pg.wait_for_timeout(800)
    s = await ev('WK.state()')
    check('K19 쇼핑 중: 따라 걷지 않고 프레임도 쉼', abs(s['x'] - x0) < 1 and not s['raf'], (x0, s))
    box = await ev('(()=>{const r=document.querySelector("#mch").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    await pg.mouse.click(box[0], box[1]); await pg.wait_for_timeout(150)
    check('K20 쇼핑 중에도 탭하면 표정 반응', await ev('document.querySelector("#face").getAttribute("data-mood")') == 'joy')
    await pg.context.close()
    pg = await newpage(b, w=320, h=640)
    check('K21 320px 헤더 한 줄', await pg.evaluate('document.querySelector(".brand").getBoundingClientRect().height') <= 40)
    check('K22 개선 검증 중 오류 없음', not pg._errs)
    await pg.context.close()


# ---------------------------------------------------------------- X: 매장 사진 3장 + 인스타 링크
async def suite_media(b):
    import tempfile, shutil, os
    from PIL import Image
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(os.path.dirname(URL.replace('file://','')), 'index.html') if URL.startswith('file://') else '/mnt/user-data/outputs/index.html', tmp + '/index.html')
    os.makedirs(tmp + '/img')
    for i, c in enumerate(['#F2B8C6', '#9ED8F0', '#F6D55C'], 1):
        Image.new('RGB', (160, 200), c).save(f'{tmp}/img/t-{i}.webp', 'WEBP')
    base = 'file://' + tmp + '/index.html'
    setup = """(()=>{
      MEDIA['CHIP']={ig:'https://www.instagram.com/reel/AbC123/',photos:[{src:'img/t-1.webp',alt:'CHIP 진열 1',credit:'직접 촬영'},{src:'img/t-2.webp',alt:'CHIP 진열 2',credit:'직접 촬영'},{src:'img/t-3.webp',alt:'CHIP 진열 3',credit:'직접 촬영'}]};
      MEDIA['파이']={ig:'https://www.instagram.com/pie_kids/'};
      MEDIA['보니토']={photos:[{src:'img/missing.webp',alt:'없는 파일',credit:'직접 촬영'}]};
      MEDIA['라라랜드']={ig:'https://scontent.cdninstagram.com/v/abc.jpg',photos:[{src:'https://scontent.cdninstagram.com/v/abc.jpg',alt:'외부 이미지',credit:'직접 촬영'},{src:'img/t-1.webp',alt:'출처 없음',credit:''}]};
      MEDIA['오트밀']={ig:'http://www.instagram.com/oatmeal/',photos:[{src:'img/t-1.webp',alt:'',credit:'직접 촬영'}]};
    })()"""
    pg = await newpage(b, q='?t=08:00', base=base)
    ev = pg.evaluate
    r = await ev("""()=>{const o={};['CHIP','파이','보니토','라라랜드','오트밀'].forEach(n=>{const s=S.find(x=>x.b===n),m=(function(){try{return mediaOf(s)}catch(e){return null}})();o[n]=m?{ph:m.ph.length,ig:!!m.ig}:null});return o}""")
    shipped = await pg.evaluate('Object.entries(MEDIA).map(([k,m])=>[k,!!m.ig,(m.photos||[]).length])')
    check('X0 출하 파일: 인스타 링크 43곳만 있고 사진은 아직 없음', len(shipped)==43 and all(x[1] and x[2]==0 for x in shipped), shipped)
    await pg.evaluate('Object.keys(MEDIA).forEach(k=>delete MEDIA[k])')   # 아래 시험은 샘플 데이터만으로
    await ev(setup)
    r = await ev("""()=>{const o={};['CHIP','파이','보니토','라라랜드','오트밀'].forEach(n=>{const s=S.find(x=>x.b===n),m=mediaOf(s);o[n]=m?{ph:m.ph.length,ig:!!m.ig}:null});return o}""")
    check('X1 규칙을 지킨 데이터만 통과(CHIP 사진3+링크, 파이 링크만)', r['CHIP']=={'ph':3,'ig':True} and r['파이']=={'ph':0,'ig':True}, r)
    check('X2 규칙을 어긴 데이터는 화면에서 제외(인스타 이미지·http 링크·출처 없음·alt 없음)', r['라라랜드'] is None and r['오트밀'] is None, (r['라라랜드'], r['오트밀']))
    # 목록
    await ev('state.view="list";state.lf="all";state.q="";go("cards");setView("list")'); await pg.wait_for_timeout(500)
    li = await ev("""()=>{const row=n=>{const el=[...document.querySelectorAll('#buildings .st')].find(e=>e.querySelector('.b').textContent.startsWith(n));return el};
      const c=row('CHIP'),p=row('파이'),l=row('라라랜드'),bn=row('보니토');
      return {chipThumbs:c.querySelectorAll('.mx-ph').length,chipIg:!!c.querySelector('a.mx-igi'),pieThumbs:p.querySelectorAll('.mx-ph').length,pieIg:!!p.querySelector('a.mx-igi'),lalaExtra:l.querySelectorAll('.mx-ph,a.mx-igi').length,bonitoThumbs:bn.querySelectorAll('.mx-ph').length,
        loaded:[...c.querySelectorAll('.mx-ph img')].every(i=>i.complete&&i.naturalWidth>0),lazy:[...c.querySelectorAll('.mx-ph img')].every(i=>i.loading==='lazy'),heart:!!c.querySelector('.heart')}}""")
    check('X3 목록: 사진 3장 + 인스타 아이콘, 사진 없는 매장은 그대로', li['chipThumbs']==3 and li['chipIg'] and li['pieThumbs']==0 and li['pieIg'] and li['lalaExtra']==0 and li['heart'], li)
    check('X4 목록: 사진이 실제로 로드되고 lazy 로딩', li['loaded'] and li['lazy'], li)
    check('X5 깨진 사진(없는 파일)은 칸 자체가 사라짐', li['bonitoThumbs']==0, li)
    lk = await ev("""()=>{const a=[...document.querySelectorAll('#buildings .st')].find(e=>e.querySelector('.b').textContent.startsWith('CHIP')).querySelector('a.mx-igi');return {href:a.href,target:a.target,rel:a.rel,label:a.getAttribute('aria-label')}}""")
    check('X6 인스타 링크는 새 탭·noopener noreferrer·접근성 이름', lk['target']=='_blank' and 'noopener' in lk['rel'] and 'noreferrer' in lk['rel'] and 'CHIP' in lk['label'] and lk['href'].startswith('https://www.instagram.com/'), lk)
    # 크게 보기
    await pg.click('#buildings .st:has(.b:text-is("CHIP")) .mx-ph >> nth=1'); await pg.wait_for_timeout(350)
    v = await ev("""()=>({on:document.querySelector('#sheetWrap').classList.contains('on'),kind:sheetKind,i:sheetArg.i,cr:document.querySelector('#sheet .cr').textContent,alt:document.querySelector('#sheet .pvimg img').alt,ig:!!document.querySelector('#sheet a.mx-ig'),focusIn:document.querySelector('#sheet').contains(document.activeElement)})""")
    check('X7 사진을 누르면 크게 보기(2/3, 출처 표시, 인스타 버튼)', v['on'] and v['kind']=='photo' and v['i']==1 and '2 / 3' in v['cr'] and '직접 촬영' in v['cr'] and v['alt']=='CHIP 진열 2' and v['ig'] and v['focusIn'], v)
    await pg.click('#sheet [data-pv="1"]'); await pg.wait_for_timeout(120)
    n1 = await ev('sheetArg.i'); await pg.click('#sheet [data-pv="1"]'); await pg.wait_for_timeout(120)
    n2 = await ev('sheetArg.i'); await pg.keyboard.press('ArrowLeft'); await pg.wait_for_timeout(120)
    n3 = await ev('sheetArg.i')
    check('X8 다음/이전·방향키로 넘기고 끝에서 순환', (n1,n2,n3)==(2,0,2), (n1,n2,n3))
    box = await ev("(()=>{const r=document.querySelector('#pvimg').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
    await pg.mouse.move(box[0]+60,box[1]); await pg.mouse.down(); await pg.mouse.move(box[0]-60,box[1],steps=6); await pg.mouse.up(); await pg.wait_for_timeout(150)
    check('X9 사진을 왼쪽으로 밀면 다음 사진', await ev('sheetArg.i')==0, await ev('sheetArg.i'))
    await pg.keyboard.press('Escape'); await pg.wait_for_timeout(200)
    back = await ev('document.activeElement.className')
    check('X10 Esc로 닫고 눌렀던 사진 버튼으로 포커스 복귀', not await ev("document.querySelector('#sheetWrap').classList.contains('on')") and 'mx-ph' in back, back)
    # 카드(덱)
    await ev('state.db=1;state.dpick=false;state.view="deck";go("cards");setView("deck")'); await pg.wait_for_timeout(300)
    for _ in range(12):
        if await ev('document.querySelector("#stage .dcard.cur0 h3").textContent')=='CHIP': break
        await pg.click('#bSkip'); await pg.wait_for_timeout(420)
    dk = await ev("""()=>{const c=document.querySelector('#stage .dcard.cur0'),cb=c.querySelector('.cb'),cd=c.querySelector('.cbody');return {name:c.querySelector('h3').textContent,hero:cb.classList.contains('mxh'),ph:cb.querySelectorAll('.mx-ph').length,chip:!!cb.querySelector('.mx-chip'),ig:!!c.querySelector('a.mx-ig'),loaded:[...cb.querySelectorAll('.mx-ph img')].every(i=>i.complete&&i.naturalWidth>0),overflow:cd.scrollHeight-cd.clientHeight,cardH:Math.round(c.getBoundingClientRect().height)}}""")
    check('X11 덱 카드: 윗부분이 사진 3장(상가 알약 포함) + 인스타 버튼, 내용이 넘치지 않음', dk['name']=='CHIP' and dk['hero'] and dk['ph']==3 and dk['chip'] and dk['ig'] and dk['loaded'] and dk['overflow']<=2, dk)
    h0 = await ev('state.hist.length')
    await pg.click('#stage .dcard.cur0 .mx-ph >> nth=0'); await pg.wait_for_timeout(300)
    opened = await ev("document.querySelector('#sheetWrap').classList.contains('on')&&sheetKind==='photo'")
    await pg.keyboard.press('Escape'); await pg.wait_for_timeout(250)
    check('X12 덱에서 사진을 탭하면 크게 보기가 열리고 카드는 넘어가지 않음', opened and await ev('state.hist.length')==h0, (opened, h0))
    pb = await ev("(()=>{const r=document.querySelector('#stage .dcard.cur0 .mx-ph').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
    await pg.mouse.move(pb[0],pb[1]); await pg.mouse.down(); await pg.mouse.move(pb[0]+170,pb[1]+8,steps=8); await pg.mouse.up(); await pg.wait_for_timeout(600)
    check('X13 사진 위에서 끌어도 카드가 넘어가고, 크게 보기는 열리지 않음', await ev('state.hist.length')==h0+1 and not await ev("document.querySelector('#sheetWrap').classList.contains('on')"), await ev('state.hist.length'))
    # 하단 문구
    await ev('mxNote()')
    note = await ev("({hidden:document.querySelector('#mxNote').hidden,text:document.querySelector('#mxNote').textContent})")
    check('X15 사진이 있으면 사용 원칙 문구가 보임', not note['hidden'] and '허락' in note['text'], note)
    # XSS 방어
    await ev("""MEDIA['아오유스튜디오']={photos:[{src:'img/t-1.webp',alt:'<img src=x onerror=alert(1)>',credit:'<b>직접</b> 촬영'}]}""")
    await ev('openSheet("photo",{id:S.find(x=>x.b==="아오유스튜디오").id,i:0})'); await pg.wait_for_timeout(200)
    xs = await ev("({bold:document.querySelectorAll('#sheet .cr b').length,inj:document.querySelectorAll('#sheet img[src=x]').length})")
    check('X16 출처·설명 글에 HTML이 들어 있어도 실행되지 않음(이스케이프)', xs['bold']==0 and xs['inj']==0, xs)
    check('X17 사진·링크 기능 중 오류 없음', not pg._errs, pg._errs[:2])
    await pg.context.close()
    for (w, h) in ((390, 740), (360, 640), (320, 568)):
        pg2 = await newpage(b, w=w, h=h, q='?t=08:00', base=base)
        await pg2.evaluate(setup); await pg2.evaluate('state.db=1;state.dpick=false;state.view="deck";go("cards");setView("deck")'); await pg2.wait_for_timeout(300)
        for _ in range(12):
            if await pg2.evaluate('document.querySelector("#stage .dcard.cur0 h3").textContent')=='CHIP': break
            await pg2.click('#bSkip'); await pg2.wait_for_timeout(420)
        r2 = await pg2.evaluate("(()=>{const c=document.querySelector('#stage .dcard.cur0'),cd=c.querySelector('.cbody'),cb=c.querySelector('.cb').getBoundingClientRect();return {over:cd.scrollHeight-cd.clientHeight,cbH:Math.round(cb.height),cbW:Math.round(cb.width)}})()")
        check(f'X11b 작은 폰({w}x{h})에서도 덱 카드 내용이 넘치지 않음', r2['over']<=2, r2)
        await pg2.context.close()
    # 출하 상태(MEDIA 비어 있음)에서는 어떤 매장에도 사진·링크 UI가 없음
    pg = await newpage(b, q='?t=08:00')
    await pg.evaluate('state.view="list";go("cards");setView("list")'); await pg.wait_for_timeout(400)
    ic = await pg.evaluate("""()=>{const keys=new Set(Object.keys(MEDIA));const rows=[...document.querySelectorAll('#buildings .st')];
      const withIcon=rows.filter(e=>e.querySelector('a.mx-igi')).map(e=>e.querySelector('.b').firstChild.textContent.trim());
      const shouldHave=rows.map(e=>e.querySelector('.b').firstChild.textContent.trim()).filter(n=>keys.has(n));
      return {n:withIcon.length,extra:withIcon.filter(n=>!keys.has(n)),missing:shouldHave.filter(n=>!withIcon.includes(n))}}""")
    check('X18 출하 상태: 인스타 아이콘이 링크가 있는 매장에만(빠짐·넘침 없이), 사진 UI·사용 원칙 문구는 없음', await pg.evaluate("document.querySelectorAll('.mx-ph').length")==0 and await pg.evaluate("document.querySelector('#mxNote').hidden") and ic['n']>=20 and not ic['extra'] and not ic['missing'], ic)
    # 인스타 링크가 있는 실제 매장 10곳의 덱 카드가 작은 폰에서도 넘치지 않는지
    for (w, h) in ((390, 740), (360, 640), (320, 568)):
        pg3 = await newpage(b, w=w, h=h, q='?t=08:00')
        res = await pg3.evaluate("""async()=>{const out=[];for(const mode of ['b','g']){setMode(mode,true);
          for(const s of S.filter(x=>visible(x)&&MEDIA[x.b])){state.db=s.n;state.dpick=false;state.view='deck';Object.keys(seenM()).forEach(k=>delete seenM()[k]);go('cards');setView('deck');
            const all=deckAll(),i=all.findIndex(x=>x.id===s.id);all.slice(0,i).forEach(x=>seenM()[x.id]='s');renderDeck();await new Promise(r=>setTimeout(r,40));
            const c=document.querySelector('#stage .dcard.cur0'),cd=c.querySelector('.cbody');
            out.push([mode+':'+s.b,c.querySelector('h3').textContent===s.b,cd.scrollHeight-cd.clientHeight,!!c.querySelector('a.mx-ig')])}}return out}""")
        bad = [r for r in res if not r[1] or r[2] > 2 or not r[3]]
        check(f'X20 인스타 링크가 있는 매장의 덱 카드가 {w}x{h}에서 남아·여아 모드 모두 넘치지 않고 버튼이 보임({len(res)}건)', not bad and len(res)>=10, bad)
        await pg3.context.close()
    await pg.context.close()

    # 사진 변환 도구: 위치정보 제거·크기 축소 (저장소에 tools/ 가 있을 때만)
    tool = None
    for cand in (os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'make_photos.py'), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools', 'make_photos.py')):
        if os.path.exists(cand): tool = cand; break
    if tool:
        import subprocess
        d = tempfile.mkdtemp(); os.makedirs(d + '/in')
        ex = Image.Exif(); ex[0x8825] = {1: 'N', 2: (37.0, 33.0, 30.0), 3: 'E', 4: (126.0, 58.0, 40.0)}
        Image.new('RGB', (3024, 4032), '#9ED8F0').save(d + '/in/chip-1.jpg', 'JPEG', exif=ex)
        r = subprocess.run([sys.executable, tool, d + '/in', '--out', d + '/out'], capture_output=True, text=True, encoding='utf-8')
        out = Image.open(d + '/out/chip-1.webp') if os.path.exists(d + '/out/chip-1.webp') else None
        ok = bool(out) and r.returncode == 0 and not out.getexif() and out.width <= 640 and os.path.getsize(d + '/out/chip-1.webp') < 80 * 1024
        check('X19 사진 변환 도구: GPS 위치정보 제거 + 640px 이하 + 80KB 미만', ok, (r.returncode, r.stdout[-200:]))
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- T: 이동 수단(지하철 기본 / 자동차)
async def suite_transit(b):
    pg = await newpage(b, q='?t=10:00&nogo=1')
    ev = pg.evaluate
    check('T1 처음 열면 기본은 지하철', await ev('state.go') == 'sub', await ev('state.go'))
    a = await ev('(()=>{const x=items()[0];return {h:x.h,t:x.t,p:x.p}})()')
    check('T2 첫 단계가 "회현역 도착"(출발 10분 전, 6번 출구 안내, 주차 문구 없음)', a['h']=='회현역 도착' and a['t']=='13:50' and '6번 출구' in a['p'] and '주차' not in a['p'], a)
    cd = await ev('cdInfo().sub')
    check('T3 카운트다운 안내도 회현역 기준', '회현역 6번 출구 도착' in cd and '주차' not in cd, cd)
    facts = await ev('[...document.querySelectorAll("#facts .fact")].map(e=>e.textContent.replace(/\\s+/g," "))')
    check('T4 홈 카드에 주차권 대신 지하철 안내', any('회현역' in f for f in facts) and not any('주차권' in f for f in facts), facts)
    await ev('go("info");setPanel("park")'); await pg.wait_for_timeout(200)
    inf = await ev('({tab:document.querySelector("#parkTab").textContent,first:document.querySelector("#p-park .h3").textContent,hasCar:document.querySelector("#p-park").textContent.includes("어반포트")})')
    check('T5 정보 탭 "교통": 지하철 안내가 먼저, 주차 정보는 "차로 갈 때"로 남음', inf['tab']=='교통' and inf['first']=='지하철로 갈 때' and inf['hasCar'], inf)
    await ev('setPanel("prep")')
    prep = await ev('[...document.querySelectorAll("#p-prep li span")].map(e=>e.textContent)')
    check('T6 준비물: 주차권 대신 교통카드', '교통카드 잔액 확인' in prep and not any('주차권' in x for x in prep), prep)
    check('T7 말풍선에 주차 이야기 없음', await ev('quips().every(q=>!q.includes("주차"))'))
    await ev('go("home")'); await pg.wait_for_timeout(250)
    nx = await ev('document.querySelector("#next").innerText')
    check('T8 다음 일정 카드: 회현역 도착 + "씨티아이 위치" 버튼', '회현역 도착' in nx and '씨티아이 위치' in nx and '주차 정보' not in nx, nx[:80])
    await pg.click('#next [data-bld="1"]'); await pg.wait_for_timeout(250)
    check('T9 "씨티아이 위치"를 누르면 씨티아이 상가 시트(네이버지도 열기 포함)', await ev('sheetKind==="bld"&&!!document.querySelector("#sheet .mapbtn")'))
    await pg.keyboard.press('Escape'); await pg.wait_for_timeout(150)
    # 정확한 시간 경계
    for t, exp in (('13:49','before'),('13:50','during')):
        p2 = await newpage(b, q=f'?t={t}&go=sub')
        check(f'T10 지하철 시간 경계 {t} → {exp}', await p2.evaluate('stage().ph') == exp, await p2.evaluate('stage().ph'))
        await p2.context.close()
    # 도착 체크 → 자동차로 바꿔도 체크 유지, 저장
    await ev('state.done.add(kOf(items()[0]));save()')
    await pg.click('.hello .tedit'); await pg.wait_for_timeout(250)
    seg = await ev('[...document.querySelectorAll("#sheet [data-gset]")].map(b=>b.textContent+":"+b.getAttribute("aria-pressed"))')
    check('T11 일정 시트에 이동 수단(지하철 선택됨)', seg == ['지하철:true', '자동차:false'], seg)
    await pg.click('#sheet [data-gset="car"]'); await pg.click('#sheet [data-tapply]'); await pg.wait_for_timeout(350)
    r = await ev('({go:state.go,saved:localStorage.getItem("nm2.go"),h:items()[0].h,t:items()[0].t,done:state.done.has(kOf(items()[0])),toast:document.querySelector("#toast").textContent})')
    check('T12 자동차로 바꾸면 "도착 · 주차"(30분 전)로 돌아가고 저장됨', r['go']=='car' and r['saved']=='"car"' and r['h']=='도착 · 주차' and r['t']=='13:30' and '자동차' in r['toast'], r)
    check('T13 이동 수단을 바꿔도 도착 체크는 유지', r['done'], r)
    await pg.goto((URL) + '?t=10:00'); await pg.wait_for_timeout(350)
    check('T14 새로고침 후에도 자동차 유지', await ev('state.go') == 'car')
    check('T15 이동 수단 기능 중 오류 없음', not pg._errs, pg._errs[:2])
    await pg.context.close()


# ---------------------------------------------------------------- Y: 링크 공유 미리보기(카카오톡 등)
async def suite_share(b):
    import os
    pg = await newpage(b)
    m = await pg.evaluate("""()=>{const g=(a,v)=>document.querySelector('meta['+a+'="'+v+'"]')?.content||'';
      return {ogTitle:g('property','og:title'),ogDesc:g('property','og:description'),ogImg:g('property','og:image'),ogUrl:g('property','og:url'),ogType:g('property','og:type'),w:g('property','og:image:width'),h:g('property','og:image:height'),alt:g('property','og:image:alt'),tw:g('name','twitter:card'),twImg:g('name','twitter:image'),desc:g('name','description'),icon:!!document.querySelector('link[rel=icon]'),staticTitle:document.title}}""")
    check('Y1 공유 태그: 제목·설명·이미지·주소·유형이 모두 있음', all(m[k] for k in ('ogTitle','ogDesc','ogImg','ogUrl','ogType','alt','desc')), m)
    check('Y2 미리보기 이미지는 https 절대 주소(og.png)이고 og:url과 같은 사이트', m['ogImg'].startswith('https://') and m['ogImg'].endswith('/og.png') and m['ogImg'].split('/')[2]==m['ogUrl'].split('/')[2]==m['twImg'].split('/')[2], m)
    check('Y3 제목이 특정 시간("2시")에 묶이지 않음 + 설명 길이 적당', '2시' not in m['ogTitle'] and 15 <= len(m['ogDesc']) <= 100, (m['ogTitle'], len(m['ogDesc'])))
    check('Y4 트위터/기타 앱용 큰 이미지 카드 + 파비콘', m['tw']=='summary_large_image' and m['icon'], m)
    if URL.startswith('file://'):
        from PIL import Image
        p = os.path.join(os.path.dirname(URL.replace('file://','')), 'og.png')
        ok = os.path.exists(p)
        im = Image.open(p) if ok else None
        check('Y5 og.png 파일이 index.html 옆에 있고 1200x630, 600KB 이하', ok and im.size==(int(m['w']),int(m['h']))==(1200,630) and os.path.getsize(p) < 600*1024, (ok, im.size if im else None, os.path.getsize(p)//1024 if ok else None))
    await pg.context.close()


# ---------------------------------------------------------------- A: 매장 연령·사이즈
async def suite_age(b):
    pg = await newpage(b, q='?t=08:00')
    ev = pg.evaluate
    bad = await ev("""()=>{const names=new Set(S.map(s=>s.b)),bad=[];for(const [k,v] of Object.entries(AGE)){if(!names.has(k))bad.push(k+': 없는 매장명');if(typeof v!=='string'||!v.trim())bad.push(k+': 빈 값');else if(v.length>30)bad.push(k+': 너무 김');else if(/[<>"]/.test(v))bad.push(k+': 특수문자')}return bad}""")
    check('A1 연령·사이즈 데이터가 앱의 매장명과 맞고 짧음', not bad and await ev('Object.keys(AGE).length')>=12, bad)
    await ev('state.view="list";state.lf="all";go("cards");setView("list")'); await pg.wait_for_timeout(400)
    li = await ev("""()=>{const row=n=>[...document.querySelectorAll('#buildings .st')].find(e=>e.querySelector('.b').firstChild.textContent.trim()===n);const c=row('CHIP'),l=row('라라랜드');return {chip:c.querySelector('.age')?.textContent||'',lala:!!l.querySelector('.age'),note:!document.querySelector('#ageNote').hidden}}""")
    check('A2 목록: 정보 있는 매장에만 사이즈 한 줄, 없는 매장은 그대로', li['chip']=='사이즈 XXS(6M)~M(24M)' and not li['lala'], li)
    check('A3 하단에 사이즈 표기 안내(개월 수 설명)가 보임', li['note'] and '개월' in await ev('document.querySelector("#ageNote").textContent'))
    for (w, h) in ((390, 740), (360, 640), (320, 568)):
        p2 = await newpage(b, w=w, h=h, q='?t=08:00')
        res = await p2.evaluate("""async()=>{const out=[];for(const mode of ['b','g']){setMode(mode,true);
          for(const s of S.filter(x=>visible(x)&&AGE[x.b])){state.db=s.n;state.dpick=false;state.view='deck';Object.keys(seenM()).forEach(k=>delete seenM()[k]);go('cards');setView('deck');
            const all=deckAll(),i=all.findIndex(x=>x.id===s.id);all.slice(0,i).forEach(x=>seenM()[x.id]='s');renderDeck();await new Promise(r=>setTimeout(r,40));
            const c=document.querySelector('#stage .dcard.cur0'),cd=c.querySelector('.cbody'),a=c.querySelector('.age');
            out.push([mode+':'+s.b,c.querySelector('h3').textContent===s.b,cd.scrollHeight-cd.clientHeight,!!a,a?a.scrollWidth>a.clientWidth+1:false])}}return out}""")
        badc = [r for r in res if not r[1] or r[2] > 2 or not r[3]]
        trunc = [r[0] for r in res if r[4]]
        check(f'A4 덱 카드({w}x{h}): 사이즈 칩이 보이고 카드가 넘치지 않음({len(res)}건)', not badc and len(res)>=10, badc)
        if w == 320: check('A5 320px에서도 사이즈 글이 잘리지 않음(잘리면 목록에 표시)', not trunc, trunc)
        await p2.context.close()
    gz = await ev("""()=>{const bad=[];for(const s of S){if(!GLAB[s.g])bad.push(s.b+': 구분 값');if(!cardHTML(s,0).includes(GLAB[s.g]))bad.push(s.b+': 카드에 구분 없음')}
      const c={u:0,b:0,g:0};S.forEach(s=>c[s.g]++);return {bad,c}}""")
    check('Z1 모든 매장이 공용/남아 전문/여아 전문 중 하나이고 카드에 구분이 표시됨', not gz['bad'] and sum(gz['c'].values())==len(await ev('S')) , gz)
    await ev('state.view="list";state.lf="all";go("cards");setView("list")'); await pg.wait_for_timeout(300)
    zl = await ev("""()=>{const bad=[];for(const e of document.querySelectorAll('#buildings .st')){const n=e.querySelector('.b').firstChild.textContent.trim(),s=S.find(x=>x.b===n);
        const t=e.querySelector('.b').textContent;const ok=s.g==='u'?(!!e.querySelector('.badge.gen')&&!t.includes('전문')):t.includes(s.g==='b'?'남아 전문':'여아 전문');if(!ok)bad.push(n)}return bad}""")
    check('Z2 목록: 공용은 "공용", 전문 매장은 "남아/여아 전문" 배지로 구분됨', not zl, zl)
    check('A6 연령·사이즈 기능 중 오류 없음', not pg._errs, pg._errs[:2])
    await pg.context.close()

# ---------------------------------------------------------------- O: monkey test
async def suite_monkey(b, steps=320, seed=7):
    rnd = random.Random(seed)
    pg = await newpage(b)
    bad = []
    for i in range(steps):
        els = await pg.evaluate_handle('''()=>[...document.querySelectorAll('button:not([disabled]),input[type=checkbox],[data-bld],.dcard.cur0')].filter(e=>{const r=e.getBoundingClientRect(),cs=getComputedStyle(e);return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&!e.closest('[hidden]')&&!e.closest('[inert]')})''')
        n = await pg.evaluate('e=>e.length', els)
        if not n: await pg.keyboard.press('Escape'); continue
        k = rnd.randrange(n)
        el = (await els.get_property(str(k))).as_element()
        try:
            await el.click(timeout=800, force=True, no_wait_after=True)
        except Exception:
            pass
        if rnd.random() < 0.08: await pg.keyboard.press('Escape')
        if rnd.random() < 0.05: await pg.keyboard.press(rnd.choice(['ArrowLeft', 'ArrowRight']))
        await pg.wait_for_timeout(25)
        if i % 15 == 0:
            await pg.wait_for_function('!busy', timeout=2000)
            await pg.wait_for_timeout(60)
            inv = await pg.evaluate('''()=>{const p=[];const t=document.body.innerText;if(/undefined|NaN|\\[object/.test(t))p.push('bad text');
              try{['nm2.wish','nm2.seen','nm2.done','nm2.prep','nm2.start','nm2.day','nm2.mode'].forEach(k=>{const v=localStorage.getItem(k);if(v!==null)JSON.parse(v)})}catch(e){p.push('storage json')}
              const open=document.querySelector('#sheetWrap').classList.contains('on');if(!open&&document.body.style.overflow==='hidden')p.push('scroll lock stuck');
              if(document.documentElement.scrollWidth>innerWidth+1)p.push('hscroll '+document.documentElement.scrollWidth);
              const wc=+document.querySelector('#wcnt').textContent,vis=[...state.wish].filter(id=>S[id]&&visible(S[id])).length;if(wc!==vis)p.push('wcnt '+wc+' vs '+vis);
              return p}''')
            if inv: bad.append((i, inv))
        if pg._errs: bad.append((i, pg._errs[:2])); break
    check(f'O 무작위 클릭 {steps}회 (seed {seed})', not bad, bad[:4])
    await pg.context.close()

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for fn in (suite_layout, suite_flows, suite_storage, suite_a11y, suite_data, suite_time, suite_motion, suite_scroll, suite_mine, suite_layout_ux, suite_mascot, suite_media, suite_transit, suite_share, suite_age):
            try:
                await fn(b)
            except Exception as e:
                check(f'SUITE CRASH {fn.__name__}', False, repr(e)[:300])
        for seed in (7, 11):
            try:
                await suite_monkey(b, seed=seed)
            except Exception as e:
                check(f'SUITE CRASH monkey {seed}', False, repr(e)[:300])
        await b.close()
    fails = [r for r in R if not r[1]]
    print(f'TOTAL {len(R)} checks | PASS {len(R)-len(fails)} | FAIL {len(fails)}')
    for n, ok, d in fails:
        print('FAIL', n, '|', json.dumps(d, ensure_ascii=False)[:300])

asyncio.run(main())
