import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const output = path.resolve('../../runtime/qa');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
const messages = [];
page.on('pageerror', e => messages.push({type:'pageerror',text:e.message}));
page.on('console', m => { if (['error','warning'].includes(m.type())) messages.push({type:m.type(),text:m.text()}); });
page.on('response', r => { if (r.status() >= 400) messages.push({type:'http',status:r.status(),url:r.url()}); });
await page.goto('http://127.0.0.1:8765', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(15000);
const initial = await page.evaluate(() => { const v=document.querySelector('video'); return {title:document.title,video:{readyState:v.readyState,width:v.videoWidth,height:v.videoHeight,time:v.currentTime,frames:v.getVideoPlaybackQuality().totalVideoFrames},text:document.body.innerText}; });
await page.screenshot({path:path.join(output,'01-overview.png')});
await writeFile(path.join(output,'initial.json'),JSON.stringify({initial,messages},null,2));
console.log(JSON.stringify({video:initial.video,title:initial.title,messages},null,2));
await browser.close();
