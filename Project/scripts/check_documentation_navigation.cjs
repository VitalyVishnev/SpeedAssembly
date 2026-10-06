// Optional browser gate/benchmark: node scripts/check_documentation_navigation.cjs site check
// Requires Playwright and an installed browser; DOCS_BROWSER_CHANNEL can select msedge.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const root = path.resolve(process.argv[2] || 'site');
const mode = process.argv[3] || 'check';
const delay = Number(process.argv[4] || 120);
const requests = [];
let failOnce;
const server = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const relative = pathname.replace(/^\/SpeedAssembly\//, '');
  const file = path.join(root, !relative || relative.endsWith('/') ? relative + 'index.html' : relative);
  requests.push({ path: pathname, time: Date.now() });
  if (pathname === failOnce) { failOnce = undefined; res.writeHead(503); res.end(); return; }
  try {
    let body = await fs.readFile(file);
    if (file.endsWith('.xml')) body = Buffer.from(body.toString().replaceAll('https://vitalyvishnev.github.io', `http://127.0.0.1:${server.address().port}`));
    const type = {'.html':'text/html', '.xml':'application/xml', '.css':'text/css', '.js':'application/javascript', '.json':'application/json', '.png':'image/png'}[path.extname(file)] || 'application/octet-stream';
    setTimeout(() => { res.writeHead(200, {'Content-Type':type, 'Cache-Control':'public, max-age=600'}); res.end(body); }, delay);
  } catch { res.writeHead(404); res.end(); }
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}/SpeedAssembly/`;
  const browser = await chromium.launch({headless:true, channel:process.env.DOCS_BROWSER_CHANNEL});
  const results = [];
  try {
    if (mode === 'check') {
      const context = await browser.newContext({viewport:{width:1440,height:1000}});
      const page = await context.newPage();
      const errors = [];
      const aborted = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('requestfailed', request => aborted.push(new URL(request.url()).pathname));
      const nav = route => page.locator(`.md-nav--primary a[href="${base}${route}"]`).first();
      const heading = () => page.locator('article h1').textContent();
      const visit = async route => {
        const old = await heading();
        await nav(route).evaluate(link => link.click());
        await page.waitForFunction(old => document.querySelector('article h1')?.textContent !== old, old);
      };
      await page.goto(base, {waitUntil:'networkidle'});
      const origin = await page.evaluate(() => performance.timeOrigin);
      const homeHeading = await heading();
      // A fast sweep must request only the last target.
      let start = requests.length;
      for (const route of ['workflows/udim/', 'workflows/proxy-mesh/', 'wiki/xml-usd-usda-json/']) {
        await nav(route).hover();
      }
      await page.waitForTimeout(delay + 200);
      assert.deepEqual(requests.slice(start).filter(r=>r.path.endsWith('/')).map(r=>r.path), ['/SpeedAssembly/wiki/xml-usd-usda-json/']);
      start = requests.length;
      await visit('wiki/xml-usd-usda-json/');
      assert.equal(await page.evaluate(() => performance.timeOrigin), origin);
      assert(!requests.slice(start).some(r=>r.path === '/SpeedAssembly/wiki/xml-usd-usda-json/'), 'Warm article fetched again');
      const articleHeading = await heading();
      assert.equal(await page.locator('.sa-language [hreflang="ru"]').getAttribute('href'), base + 'ru/wiki/xml-usd-usda-json/');
      await page.goBack();
      await page.waitForFunction(text => document.querySelector('article h1')?.textContent === text, homeHeading);
      await page.goForward();
      await page.waitForFunction(text => document.querySelector('article h1')?.textContent === text, articleHeading);
      // Replace an in-flight speculative request; the last hovered page must win.
      await nav('workflows/udim/').hover();
      await page.waitForTimeout(110);
      await nav('workflows/proxy-mesh/').hover();
      await page.waitForTimeout(delay + 200);
      assert(aborted.includes('/SpeedAssembly/workflows/udim/'), 'Old hover request was not aborted');
      start = requests.length;
      await visit('workflows/proxy-mesh/');
      assert(!requests.slice(start).some(r=>r.path === '/SpeedAssembly/workflows/proxy-mesh/'), 'Last hovered article was not cached');
      // Same-page anchors and theme state survive article navigation.
      const anchor = page.locator('.md-nav--secondary a[href*="#"]').first();
      const hash = await anchor.evaluate(link => new URL(link.href).hash);
      await anchor.evaluate(link => link.click());
      await page.waitForFunction(hash => location.hash === hash, hash);
      assert.equal(await page.evaluate(() => performance.timeOrigin), origin);
      await page.locator('label[for="__palette_1"]').click();
      const scheme = await page.locator('body').getAttribute('data-md-color-scheme');
      await visit('workflows/prepare-speedtree/');
      assert.equal(await page.locator('body').getAttribute('data-md-color-scheme'), scheme);
      // Clicking before prefetch completes must reuse the in-flight HTTP cache fill.
      start = requests.length;
      await nav('workflows/prepare-unreal/').hover();
      await page.waitForTimeout(110);
      await visit('workflows/prepare-unreal/');
      assert.equal(requests.slice(start).filter(r=>r.path === '/SpeedAssembly/workflows/prepare-unreal/').length, 1);
      // Switching languages preserves the article and reloads translated UI.
      await page.locator('.sa-language [hreflang="ru"]').click();
      await page.waitForFunction(() => document.documentElement.lang === 'ru');
      assert(new URL(page.url()).pathname.endsWith('/ru/workflows/prepare-unreal/'));
      await visit('ru/workflows/udim/');
      assert.equal(await page.locator('.sa-language [hreflang="en"]').getAttribute('href'), base + 'workflows/udim/');
      // Bilingual search can cross locale without leaving stale Russian controls.
      await page.locator('[data-md-component="search-query"]').pressSequentially('UDIM');
      const englishResult = page.locator(`.md-search-result a[href^="${base}workflows/udim/?"]`).first();
      await englishResult.waitFor({state:'visible'});
      await englishResult.click();
      await page.waitForFunction(() => document.documentElement.lang === 'en');
      assert(new URL(page.url()).pathname.endsWith('/workflows/udim/'));
      // A failed prefetch must not prevent the subsequent real navigation.
      failOnce = '/SpeedAssembly/wiki/how-dynamic-wind-works/';
      await nav('wiki/how-dynamic-wind-works/').hover();
      await page.waitForTimeout(delay + 200);
      await visit('wiki/how-dynamic-wind-works/');
      assert.equal(failOnce, undefined);
      // Keyboard focus gets the same preloading benefit as mouse hover.
      await nav('wiki/choosing-assembly-parts/').focus();
      await page.waitForTimeout(delay + 200);
      start = requests.length;
      await visit('wiki/choosing-assembly-parts/');
      assert(!requests.slice(start).some(r=>r.path === '/SpeedAssembly/wiki/choosing-assembly-parts/'));
      assert.deepEqual(errors, []);
      await context.close();
      // Touch and data-saving users must not trigger speculative traffic.
      for (const saveData of [false, true]) {
        const mobile = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
        if (saveData) await mobile.addInitScript(() => Object.defineProperty(navigator, 'connection', {value:{saveData:true}}));
        const tab = await mobile.newPage();
        await tab.goto(base, {waitUntil:'networkidle'});
        start = requests.length;
        await tab.locator('.md-nav--primary a[href$="overview/what-is-speedassembly/"]').first().dispatchEvent('pointerover', {pointerType:saveData ? 'mouse' : 'touch'});
        await tab.waitForTimeout(delay + 200);
        assert.equal(requests.length, start, 'Unwanted speculative traffic');
        await mobile.close();
      }
      console.log('Navigation contract passed: latest hover, cancellation/cache, history, anchors, theme, ENG/RU, search, failure recovery, touch and Save-Data.');
      return;
    }
    for (let run=0; run<7; run++) {
      const context = await browser.newContext({viewport:{width:1440,height:1000}});
      await context.addInitScript(() => {
        const check = () => {
          const pending = JSON.parse(sessionStorage.getItem('measure-pending') || 'null');
          const heading = document.querySelector('article h1');
          if (!pending || !heading || heading.textContent === pending.old || location.pathname !== pending.path) return;
          sessionStorage.removeItem('measure-pending');
          requestAnimationFrame(() => requestAnimationFrame(() => sessionStorage.setItem('measure-result', JSON.stringify({ms: performance.timeOrigin + performance.now() - pending.start, sameDocument:performance.timeOrigin === pending.origin}))));
        };
        document.addEventListener('click', event => {
          const link = event.target.closest('a');
          if (!link) return;
          sessionStorage.removeItem('measure-result');
          sessionStorage.setItem('measure-pending', JSON.stringify({start:performance.timeOrigin+performance.now(), origin:performance.timeOrigin, old:document.querySelector('article h1')?.textContent, path:new URL(link.href).pathname}));
        }, true);
        new MutationObserver(check).observe(document, {childList:true,subtree:true});
        document.addEventListener('DOMContentLoaded', check);
      });
      const page = await context.newPage();
      await page.goto(base, {waitUntil:'networkidle'});
      const selector = '.md-nav--primary a[href$="wiki/xml-usd-usda-json/"]';
      if (mode === 'hover') {
        await page.locator(selector).hover();
        await page.waitForTimeout(500);
      }
      const start = requests.length;
      await page.locator(selector).evaluate(link => link.click());
      await page.waitForFunction(() => sessionStorage.getItem('measure-result'));
      results.push({...await page.evaluate(() => JSON.parse(sessionStorage.getItem('measure-result'))), requests: requests.slice(start).map(r=>r.path)});
      await context.close();
    }
    const sorted=results.map(r=>r.ms).sort((a,b)=>a-b);
    console.log(JSON.stringify({mode,delay,median_ms:sorted[3],min_ms:sorted[0],max_ms:sorted[6],results},null,2));
  } finally { await browser.close(); server.close(); }
})().catch(error => {console.error(error); process.exitCode=1; server.close();});

