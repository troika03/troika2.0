"""Exercise representative user flows, narrow layouts, and design exports."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]

async def main():
    findings=[];checks=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto((ROOT/'app.html').as_uri())
        await page.evaluate("troikaDesign.platform('android')")
        await page.get_by_role('button',name='Открыть меню',exact=True).click()
        assert await page.locator('.sidebar.mobile-open').is_visible()
        await page.locator('.sidebar').get_by_role('button',name='Дела',exact=True).click()
        assert await page.locator('#app').get_attribute('data-page')=='tasks'
        await page.get_by_role('button',name='Новое дело',exact=True).click()
        await page.get_by_label('Что нужно сделать',exact=True).fill('Проверить прототип')
        await page.get_by_role('button',name='Добавить дело',exact=True).click()
        assert await page.locator('#app').get_attribute('data-page')=='tasks'
        checks.append('Mobile menu, task form, return')
        await page.evaluate("troikaDesign.go('home')")
        await page.locator('.composer textarea').fill('План на неделю')
        assert await page.get_by_role('button',name='Отправить',exact=True).is_visible()
        assert not await page.get_by_role('button',name='Начать голосовой разговор',exact=True).is_visible()
        await page.locator('.composer textarea').press('Enter')
        assert await page.locator('#app').get_attribute('data-page')=='text'
        await page.locator('.composer textarea').fill('Добавь сроки')
        await page.locator('.composer textarea').press('Enter')
        assert await page.locator('.chat-log .message.user').last.inner_text()=='Добавь сроки'
        checks.append('Composer switches voice/send, Enter, local message')
        await page.evaluate("troikaDesign.go('home')")
        await page.get_by_role('button',name='Попробовать анимацию голоса',exact=True).click()
        assert await page.locator('#app').get_attribute('data-page')=='voice-chat'
        await page.get_by_role('button',name='Завершить разговор',exact=True).click()
        checks.append('Voice screen and end conversation')
        await page.evaluate("troikaDesign.go('appearance')")
        await page.locator('[data-theme-choice=light]').click()
        assert await page.locator('#app').get_attribute('data-theme')=='light'
        toggle=page.locator('.toggle').first
        before=await toggle.get_attribute('aria-checked');await toggle.click()
        assert await toggle.get_attribute('aria-checked')!=before
        checks.append('Theme and accessible switches')
        await page.evaluate("troikaDesign.go('development')")
        await page.locator('.composer textarea').fill('Личный сайт')
        await page.locator('[data-send=project]').click()
        await page.get_by_role('button',name='Начать · до 50 000',exact=True).click()
        await page.get_by_role('button',name='Пауза',exact=True).click()
        await page.get_by_role('button',name='Продолжить',exact=True).click()
        await page.get_by_role('button',name='Продолжить работу',exact=True).click()
        assert await page.locator('#app').get_attribute('data-page')=='development-detail'
        checks.append('Project estimate, start, pause, resume')
        await page.evaluate("troikaDesign.platform('desktop')")
        await page.set_viewport_size({'width':1280,'height':840})
        assert await page.locator('.workbench-sidebar').is_visible()
        assert await page.locator('.diff-lines').is_visible()
        await page.locator('.inspector-tabs [data-inspector=preview]').click()
        assert await page.locator('.workbench-preview').is_visible()
        await page.locator('.inspector-tabs [data-inspector=files]').click()
        assert await page.locator('.workbench-tree').is_visible()
        await page.locator('.inspector-tabs [data-inspector=changes]').click()
        assert await page.locator('.diff-lines').is_visible()
        checks.append('Codex-style workspace, changes, preview and file inspector')
        await page.evaluate("troikaDesign.platform('android')")
        registry=await page.evaluate('TROIKA_PAGES')
        # All mobile routes at a smaller width; overflowing lists are real defects.
        for width in [360,430]:
            await page.set_viewport_size({'width':width,'height':844})
            for item in registry:
                if item.get('only')=='desktop':continue
                await page.evaluate('(id)=>troikaDesign.go(id)',item['id'])
                metrics=await page.locator('#app').evaluate('el=>({width:el.clientWidth,height:el.clientHeight,scroll:el.scrollWidth,placeholder:el.innerText.includes("Этот макет появится")})')
                if metrics['scroll']>metrics['width']+1 or metrics['placeholder'] or metrics['height']!=844:findings.append(dict(page=item['id'],viewport=width,**metrics))
        checks.append('All mobile routes at 360 and 430 pixels')
        for width in [1024,1440]:
            await page.set_viewport_size({'width':width,'height':900})
            await page.evaluate("troikaDesign.platform('desktop')")
            for item in ['home','text','tasks','files','development','development-detail','project-checks','profile']:
                await page.evaluate('(id)=>troikaDesign.go(id)',item)
                metrics=await page.locator('#app').evaluate('el=>({width:el.clientWidth,scroll:el.scrollWidth})')
                if metrics['scroll']>metrics['width']+1:findings.append(dict(page=item,width=width,**metrics))
        checks.append('Desktop primary routes at 1024 and 1440 pixels')
        await browser.close()
    report={'checks':checks,'issues':findings,'script_errors':errors,'limitations':['Local prototype only; no account, microphone, payments, provider, or native app verification.','Figma importer must still be run in a real Figma editor.']}
    (ROOT/'review'/'prototype-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'issues':len(findings),'script_errors':len(errors)}))
    if findings or errors:raise SystemExit(1)

if __name__=='__main__':asyncio.run(main())
