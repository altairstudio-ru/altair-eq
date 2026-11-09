from pathlib import Path
import json, re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

root=Path(r'K:\AltaiR Studio\Projects\AltaiR EQ')
out=root/'outputs'
data=json.loads((out/'eq-market-catalogue.json').read_text(encoding='utf-8'))
doc=out/'AltaiR-EQ-market-research.html'
soup=BeautifulSoup(doc.read_text(encoding='utf-8'),'html.parser')
assert len(data['products'])==57
assert len(soup.select('#rows tr'))==57
assert len(set(p['name'] for p in data['products']))==57
assert not soup.select('script[src],link[rel="stylesheet"],iframe')
assert '<!-- CATALOGUE -->' not in doc.read_text(encoding='utf-8')
assert '<!-- COUNT -->' not in doc.read_text(encoding='utf-8')
for link in soup.select('a[href]'):
    assert link['href'].startswith(('https://','#'))

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True,timeout=20000)
    page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(doc.as_uri())
    assert page.locator('#count').inner_text()=='Показано 57 из 57'
    page.screenshot(path=str(root/'work'/'research-desktop.png'))
    page.locator('#search').fill('SurferEQ')
    assert page.locator('#rows tr:visible').count()==1
    assert 'SurferEQ' in page.locator('#rows tr:visible').inner_text()
    page.locator('#search').fill('')
    page.locator('#group').select_option(label='Мастеринг и окраска')
    expected=sum(x['group']=='Мастеринг и окраска' for x in data['products'])
    assert page.locator('#rows tr:visible').count()==expected
    page.locator('#group').select_option('')
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(root/'work'/'research-mobile.png'))
    overflow=page.evaluate('''() => [...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth && !e.closest('.scroll')).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.slice(0,80),right:e.getBoundingClientRect().right})).slice(0,12)''')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),overflow
    assert not errors, errors
    browser.close()
print('PASS: 57 entries; unique names; self-contained page; filters; mobile overflow; zero browser JS errors.')
