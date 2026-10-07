from pathlib import Path
import json
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/screenshots'
OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:7860', wait_until='domcontentloaded')
    page.get_by_role('heading', name='Your course. In focus.').wait_for()
    for mode in ['Light', 'Dark']:
        page.locator('#theme-mode').get_by_label(mode, exact=True).check()
        page.wait_for_function('(mode) => document.documentElement.dataset.courseTheme === mode', arg=mode.lower())
        for tab, name in [('Q&A', 'qa'), ('Practice Quiz', 'quiz'), ('Course Materials', 'library')]:
            page.get_by_role('tab', name=tab, exact=True).click()
            page.screenshot(path=str(OUT / f'mountain-master-{name}-{mode.lower()}.png'), full_page=True)
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function('(mode) => document.documentElement.dataset.courseTheme === mode', arg=mode.lower())
        assert page.locator('#theme-mode').get_by_label(mode, exact=True).is_checked()
    page.get_by_role('tab', name='Q&A', exact=True).click()
    layout = page.locator('#qa-filters, #qa-workspace, #qa-evidence').evaluate_all('(els) => els.map(e => ({id:e.id,x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width}))')
    assert layout[0]['x'] < layout[1]['x'] < layout[2]['x']
    page.set_viewport_size({'width':390, 'height':844})
    page.screenshot(path=str(OUT/'mountain-master-mobile-dark.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.set_viewport_size({'width':1440, 'height':1000})
    page.get_by_role('button', name='Ask question', exact=True).click()
    page.get_by_text('Ask a question first.', exact=True).wait_for()
    assert not errors, errors
    print(json.dumps({'url':page.url, 'layout':layout, 'theme_reload':'both passed', 'mobile_overflow':False, 'browser_errors':errors, 'screenshots':sorted(f.name for f in OUT.glob('mountain-master-*.png'))}, indent=2))
    browser.close()
