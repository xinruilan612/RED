"""Computed layout of the archived card editor, retained for export compatibility."""
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright
from backend.html_cards import browser_arguments

ROOT = Path(__file__).resolve().parents[1]


class StudioBrowserLayoutTests(unittest.TestCase):
    def test_canvas_has_no_application_main_margin_and_scroll_clears_sticky_bar(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, **browser_arguments())
            try:
                page = browser.new_page(viewport={'width': 1512, 'height': 1100})
                styles = '\n'.join((ROOT / 'frontend' / name).read_text() for name in ('style.css', 'media_exports.css'))
                page.set_content('<style>' + styles + '</style><main><div class="account-bar" style="height:90px">运营账号</div><div style="height:700px"></div><div id="host"></div><div style="height:1400px"></div></main>')
                page.evaluate("""() => {
                    window.fetch = async url => ({ok:true, json:async()=>url.includes('/api/media/templates')?{templates:[]}:{
                        state:{revision:0,current:{template:'xhs-e',options:{}},accepted:{template:'xhs-e',options:{}},has_pending:false,assets:[],messages:[]},
                        preview:{draft_ref:'v1',content_hash:'hash',pages:[{data_url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jH54AAAAASUVORK5CYII=',elements:[{id:'title',bounds:{x:100,y:100,width:800,height:200}},{id:'image',bounds:{x:0,y:0,width:1080,height:1440}},{id:'body',bounds:{x:100,y:700,width:800,height:400}}]}]}
                    }});
                }""")
                page.add_script_tag(path=str(ROOT / 'frontend/media_exports.js'))
                page.evaluate("""() => mountArchivedStudio({workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v1',run_id:'layout-fixture',drafts:[{ref:'v1',content_hash:'hash'}]},document.querySelector('#host'))""")
                for width in (1512, 390):
                    with self.subTest(width=width):
                        page.set_viewport_size({'width': width, 'height': 1100})
                        page.locator('.studio').evaluate("el => el.scrollIntoView({block:'start',behavior:'instant'})")
                        geometry = page.evaluate("""() => {
                            const center=document.querySelector('.studio-center'),style=getComputedStyle(center);
                            const rect=center.getBoundingClientRect(),library=document.querySelector('.studio-library').getBoundingClientRect();
                            return {tag:center.tagName,left:style.marginLeft,right:style.marginRight,max:style.maxWidth,gap:rect.left-library.right,
                                top:document.querySelector('.studio').getBoundingClientRect().top,sticky:document.querySelector('.account-bar').getBoundingClientRect().bottom,
                                width:document.documentElement.scrollWidth,viewport:innerWidth};
                        }""")
                        self.assertEqual(geometry['tag'], 'DIV')
                        self.assertEqual(geometry['left'], '0px')
                        self.assertEqual(geometry['right'], '0px')
                        self.assertEqual(geometry['max'], 'none')
                        self.assertLessEqual(abs(geometry['gap']), 1)
                        self.assertGreaterEqual(geometry['top'], geometry['sticky'])
                        self.assertLessEqual(geometry['width'], geometry['viewport'])
                        # Actual hit testing: image follows title in DOM and covers the
                        # whole page, but text must remain independently selectable.
                        for element_id, label in (('title', '标题'), ('body', '正文'), ('image', '产品图')):
                            target = page.locator('[data-studio-element="' + element_id + '"]')
                            if element_id == 'image':
                                target.click(position={'x': 5, 'y': 5})
                            else:
                                target.click()
                            self.assertEqual(target.get_attribute('aria-pressed'), 'true')
                            self.assertIn(label, page.locator('[data-studio="selection"]').inner_text())
                        page.locator('.studio').evaluate("el => el.scrollIntoView({block:'start',behavior:'instant'})")
                        page.evaluate("window.scrollBy(0,240)")
                        undo = page.locator('[data-studio="undo"]').bounding_box()
                        account = page.locator('.account-bar').bounding_box()
                        self.assertGreaterEqual(undo['y'], account['y'] + account['height'])
                        self.assertLess(undo['y'] + undo['height'], 1100)
                        self.assertEqual(page.locator('.studio-canvas-toolbar').evaluate("el => getComputedStyle(el).position"), 'sticky')

            finally:
                browser.close()
