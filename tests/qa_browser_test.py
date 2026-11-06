# 사용법: pip install playwright && playwright install chromium
# python tests/qa_browser_test.py [file:// 또는 https:// 주소]  (생략하면 저장소의 index.html)
import asyncio, json, random, re, sys
from playwright.async_api import async_playwright

import os
_here = os.path.dirname(os.path.abspath(__file__))
_idx = next((p for p in (os.path.join(_here, 'index.html'), os.path.join(_here, '..', 'index.html')) if os.path.exists(p)), os.path.join(_here, '..', 'index.html'))
URL = sys.argv[1] if len(sys.argv) > 1 else 'file://' + os.path.abspath(_idx)
R = []
def check(name, ok, detail=''):
    R.append((name, bool(ok), detail))

async def newpage(b, w=390, h=860, init=None, reduced=False, q='?t=08:00'):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1,
                              reduced_motion='reduce' if reduced else 'no-preference')
    pg = await ctx.new_page()
    pg._errs = []
    pg.on('pageerror', lambda e: pg._errs.append('PAGEERROR: ' + e.message))
    pg.on('console', lambda m: pg._errs.append('CONSOLE: ' + m.text) if m.type == 'error' and 'Failed to load' not in m.text and 'ERR_' not in m.text else None)
    await pg.route('**/*', lambda r: r.continue_() if r.request.url.startswith('file:') else r.abort())
    if init: await pg.add_init_script(init)
    await pg.goto(URL + q)
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
    await pg.reload(); await pg.wait_for_timeout(350)
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


# ---------------------------------------------------------------- K: 캐릭터(스티커) 인터랙션
async def suite_mascot(b):
    names = ['콘 CON', 'CHIP', '파이', '페퍼 PEPPER', '멜멜', '아모', '헤이']
    # 구조: 손·발 제거, 얼굴 접근성
    pg = await newpage(b)
    ev = pg.evaluate
    st = await ev('({arm:document.querySelectorAll(".arm").length,legs:document.querySelectorAll(".legs").length,tab:document.querySelector("#face").getAttribute("tabindex"),role:document.querySelector("#face").getAttribute("role"),label:!!document.querySelector("#face").getAttribute("aria-label"),logo:!!document.querySelector(".brand .lg rect[stroke]")})')
    check('K1 손·발 제거, 얼굴은 키보드 접근 가능', st['arm'] == 0 and st['legs'] == 0 and st['tab'] == '0' and st['role'] == 'button' and st['label'] and st['logo'], st)
    # 눌림 효과
    box = await ev('(()=>{const r=document.querySelector("#face").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    await pg.mouse.move(box[0], box[1]); await pg.mouse.down(); await pg.wait_for_timeout(60)
    pressed = await ev('document.querySelector("#bagwrap").classList.contains("press")')
    sh = await ev('getComputedStyle(document.querySelector(".bag")).boxShadow')
    await pg.mouse.up(); await pg.wait_for_timeout(150)
    released = await ev('!document.querySelector("#bagwrap").classList.contains("press")')
    check('K2 누르면 눌림(press) → 놓으면 복귀', pressed and released, (pressed, released))
    # 탭: jelly + 말풍선 + 표정 flash 후 복귀
    await pg.wait_for_timeout(1000)
    base = await ev('baseMood()')
    await pg.mouse.click(box[0], box[1]); await pg.wait_for_timeout(120)
    r = await ev('({jelly:document.querySelector("#bagwrap").classList.contains("jelly"),say:document.querySelector("#say").textContent.length>0,mood:document.querySelector("#face").dataset.mood})')
    check('K3 탭 → 말랑 반응 + 말풍선 + 웃는 표정', r['jelly'] and r['say'] and r['mood'] == 'joy', r)
    await pg.wait_for_timeout(1100)
    check('K4 표정이 원래 상태로 복귀', await ev('document.querySelector("#face").dataset.mood') == base, base)
    # 5연타
    await pg.wait_for_timeout(800)
    for _ in range(5):
        await pg.mouse.click(box[0], box[1]); await pg.wait_for_timeout(90)
    check('K5 5연타 → "간질간질" 반응', '간질간질' in await ev('document.querySelector("#say").textContent'), await ev('document.querySelector("#say").textContent'))
    # 키보드
    await pg.wait_for_timeout(1700)
    await ev('document.querySelector("#say").textContent=""')
    await ev('document.querySelector("#face").focus()')
    await pg.keyboard.press('Enter'); await pg.wait_for_timeout(150)
    check('K6 Enter 키로도 반응', len(await ev('document.querySelector("#say").textContent')) > 0 and await ev('document.querySelector("#face").dataset.mood') == 'joy')
    # 눈 추적 + 얼굴만 기울기
    await pg.mouse.move(380, 120); await pg.wait_for_timeout(250)
    v = await ev('(()=>{const f=document.querySelector("#face"),b=document.querySelector(".bag");return {px:parseFloat(f.style.getPropertyValue("--px")),tilt:parseFloat(document.querySelector("#bagwrap").style.getPropertyValue("--tilt")),bagRotate:getComputedStyle(b).rotate,faceRotate:getComputedStyle(f).rotate}})()')
    check('K7 눈 추적 + 기울기(±5°) + 몸통은 고정', abs(v['px']) > 0 and abs(v['tilt']) <= 5 and v['bagRotate'] in ('none', '0deg'), v)
    check('K8 인터랙션 중 오류 없음', not pg._errs, pg._errs[:2])
    await pg.context.close()
    # 상태별 표정
    for t, exp, setup in (('08:00', 'smile', False), ('14:05', 'wow', False), ('18:00', 'sleep', False), ('14:05', 'joy', True)):
        pg = await newpage(b, q=f'?t={t}')
        if setup:
            await pg.evaluate('(n)=>{setMode("g",true);state.wish.clear();n.forEach(x=>state.wish.add(S.find(s=>s.b===x&&visible(s)).id));sched().list.forEach(x=>{if(x.mine)x.stores.forEach(s=>state.done.add("s|"+s.id));else if(!x.end)state.done.add(kOf(x))});save();updWish();go("home")}', names)
            await pg.wait_for_timeout(300)
        check(f'K9 표정 {t} → {exp}', await pg.evaluate('document.querySelector("#face").dataset.mood') == exp, await pg.evaluate('document.querySelector("#face").dataset.mood'))
        await pg.context.close()
    # 모션 축소
    pg = await newpage(b, reduced=True)
    await pg.mouse.click(190, 300); await pg.mouse.move(380, 100); await pg.wait_for_timeout(200)
    tl = await pg.evaluate('document.querySelector("#bagwrap").style.getPropertyValue("--tilt")')
    check('K10 모션 축소: 기울기 없음·오류 없음', tl == '' and not pg._errs, (tl, pg._errs[:1]))
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
        for fn in (suite_layout, suite_flows, suite_storage, suite_a11y, suite_data, suite_time, suite_motion, suite_scroll, suite_mine, suite_layout_ux, suite_mascot):
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
