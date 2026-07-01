#!/usr/bin/env python3
"""
km-browser-backup: static-friendly 学城 backup via CDP + offscreen Edge.

Usage:
  backup.py --content-id 2572374431 --out ~/Downloads/km-backup
  backup.py --content-ids 111,222,333 --out ~/Downloads/km-backup \
            --min-interval 30 --max-interval 90
"""
import argparse, base64, json, os, random, re, socket, struct, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path

# ---- Minimal WebSocket + CDP client (stdlib only) ----
def ws_connect(url, timeout=30):
    proto, rest = url.split('://',1)
    hp, path = rest.split('/',1)
    host, port = hp.split(':')
    s = socket.create_connection((host,int(port)), timeout=timeout)
    s.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET /{path} HTTP/1.1\r\nHost: {hp}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    buf=b''
    while b'\r\n\r\n' not in buf: buf+=s.recv(4096)
    return s

def ws_send(s, data):
    payload = data.encode() if isinstance(data,str) else data
    mask = os.urandom(4)
    n = len(payload)
    if n<126: header=bytes([0x81, 0x80|n])
    elif n<65536: header=bytes([0x81, 0x80|126])+struct.pack('>H',n)
    else: header=bytes([0x81, 0x80|127])+struct.pack('>Q',n)
    header+=mask
    masked = bytes(b^mask[i%4] for i,b in enumerate(payload))
    s.sendall(header+masked)

def ws_recv(s):
    def rn(n):
        buf=b''
        while len(buf)<n:
            c=s.recv(n-len(buf))
            if not c: raise EOFError()
            buf+=c
        return buf
    while True:
        h1,h2 = rn(2)
        opcode = h1&0x0F
        n = h2&0x7F
        if n==126: n = struct.unpack('>H',rn(2))[0]
        elif n==127: n = struct.unpack('>Q',rn(8))[0]
        p = rn(n)
        if opcode==0x9:
            mask=os.urandom(4)
            hdr=bytes([0x8A, 0x80|len(p)])+mask
            s.sendall(hdr + bytes(b^mask[i%4] for i,b in enumerate(p)))
            continue
        if opcode==0xA: continue
        if opcode==0x8: raise EOFError('close')
        return p.decode('utf-8', errors='replace')

class CDP:
    def __init__(self, ws_url):
        self.s = ws_connect(ws_url)
        self.id = 0
    def call(self, method, params=None, timeout=30):
        self.id+=1; mid=self.id
        msg={'id':mid,'method':method}
        if params: msg['params']=params
        ws_send(self.s, json.dumps(msg))
        deadline = time.time()+timeout
        while time.time()<deadline:
            self.s.settimeout(max(0.1, deadline-time.time()))
            try: raw = ws_recv(self.s)
            except (socket.timeout, TimeoutError): continue
            try: d = json.loads(raw)
            except: continue
            if d.get('id')==mid:
                if 'error' in d: raise RuntimeError(f"{method}: {d['error']}")
                return d.get('result')
        raise TimeoutError(method)
    def eval(self, expr, await_promise=False, timeout=30):
        r = self.call('Runtime.evaluate',
            {'expression':expr,'returnByValue':True,'awaitPromise':await_promise}, timeout=timeout)
        rr = r.get('result',{})
        if 'value' in rr: return rr['value']
        return rr
    def close(self):
        try: self.s.close()
        except: pass

# ---- DOM → Markdown converter (injected as JS) ----
DOM_TO_MD_JS = r'''
(() => {
  function esc(s){ return (s||'').replace(/\|/g,'\\|'); }
  function clean(s){ return (s||'').replace(/[​-‍﻿]/g,''); }
  function clsOf(node){ const c = node && node.className; return (typeof c === 'string') ? c : ((c && c.baseVal) || ''); }
  const root = document.querySelector('.ProseMirror');
  if (!root) return JSON.stringify({error: 'no ProseMirror'});
  const md = [];
  const imgs = [];

  // Pre-collect all pk-image nodes in DOM order with fixed idx
  const pmImgs = [...root.querySelectorAll('.pk-image')];
  const imgNodeToIdx = new Map();
  pmImgs.forEach((span, i) => {
    const inner = span.querySelector('img');
    if (!inner) return;
    const url = inner.getAttribute('data-origin') || inner.getAttribute('data-small') || inner.src;
    if (!url || url.startsWith('data:')) return;
    const idx = imgs.length + 1;
    imgs.push({idx, url, alt: inner.getAttribute('alt') || `图片${idx}`});
    imgNodeToIdx.set(span, idx);
  });

  function inline(node){
    if (!node) return '';
    if (node.nodeType === 3) return clean(node.textContent);
    if (node.nodeType !== 1) return '';
    const cls = clsOf(node);
    const t = node.tagName;
    if (t === 'BR') return '\n';
    if (cls.includes('pk-image')) {
      const idx = imgNodeToIdx.get(node);
      if (!idx) return '';
      const alt = imgs[idx-1].alt;
      return `![${alt}](__ASSETS__/图片${idx}__EXT__)`;
    }
    if (t === 'IMG') {
      // Standalone img not wrapped in pk-image; skip PM separators
      if (cls.includes('ProseMirror-separator')) return '';
      const parent = node.closest('.pk-image');
      if (parent && imgNodeToIdx.has(parent)) return '';
      return '';
    }
    if (t === 'A') {
      const href = node.getAttribute('href') || '';
      const text = [...node.childNodes].map(inline).join('').trim();
      if (!text) return '';
      return `[${text}](${href})`;
    }
    if (t === 'STRONG' || t === 'B') {
      const c = [...node.childNodes].map(inline).join('').trim();
      return c ? `**${c}**` : '';
    }
    if (t === 'EM' || t === 'I') {
      const c = [...node.childNodes].map(inline).join('').trim();
      return c ? `*${c}*` : '';
    }
    if (t === 'CODE') return '`' + clean(node.textContent) + '`';
    if (t === 'DEL' || t === 'S' || t === 'STRIKE') {
      const c = [...node.childNodes].map(inline).join('').trim();
      return c ? `~~${c}~~` : '';
    }
    return [...node.childNodes].map(inline).join('');
  }

  function block(node){
    if (!node || node.nodeType !== 1) return;
    const cls = clsOf(node);
    const t = node.tagName;

    // Skip UI chrome from km wrapper
    if (cls.includes('ai-abstract') || cls.includes('doc-toolbar') || cls.includes('doc-header-info')
        || cls.includes('subtitle-widget') || cls.includes('ProseMirror-widget')) return;

    if (cls.includes('pk-title')) {
      const text = clean(node.innerText).trim();
      if (text) md.push('# ' + text);
      return;
    }
    if (cls.includes('ct-heading')) {
      const lvl = parseInt(node.getAttribute('data-level') || node.getAttribute('level') || '2', 10);
      const text = inline(node).trim();
      if (text) md.push('#'.repeat(Math.min(6, Math.max(1,lvl))) + ' ' + text);
      return;
    }
    if (t.match(/^H[1-6]$/)) {
      const lvl = parseInt(t[1]);
      const text = inline(node).trim();
      if (text) md.push('#'.repeat(lvl) + ' ' + text);
      return;
    }
    if (cls.includes('ct-code') || cls.includes('pk-code')) {
      // Learn-city ct-code layout: first child is language pill + line-numbers, second is .code__content
      let lang = node.getAttribute('data-lang') || node.getAttribute('lang') || '';
      const content = node.querySelector('.code__content') || node.querySelector('pre') || node;
      let code = clean(content.innerText).replace(/\n+$/,'');
      // If lang not on attribute, first line of node.innerText is often language name
      if (!lang) {
        const firstLine = clean(node.innerText).split('\n')[0].trim();
        if (firstLine && firstLine.length < 20 && !firstLine.includes(' ')) {
          lang = firstLine.toLowerCase();
          // strip language line from code if it starts with it
          const codeLines = code.split('\n');
          if (codeLines[0].trim().toLowerCase() === lang) code = codeLines.slice(1).join('\n');
        }
      }
      md.push('```' + lang);
      md.push(code);
      md.push('```');
      return;
    }
    if (cls.includes('pk-note') || cls.includes('ct-note')) {
      const type = (node.getAttribute('data-type') || node.getAttribute('data-note-type') || 'note').toUpperCase();
      // Extract children as blocks joined by newline
      const buf = [];
      [...node.children].forEach(ch => {
        const s = inline(ch).trim();
        if (s) buf.push(s);
      });
      md.push(`> [!${type}]`);
      buf.forEach(line => line.split('\n').forEach(l => md.push('> ' + l)));
      return;
    }
    if (t === 'BLOCKQUOTE' || cls.includes('ct-blockquote')) {
      const buf = [];
      [...node.children].forEach(ch => { const s = inline(ch).trim(); if (s) buf.push(s); });
      if (!buf.length) {
        const s = inline(node).trim();
        if (s) s.split('\n').forEach(l => md.push('> ' + l));
      } else {
        buf.forEach(line => line.split('\n').forEach(l => md.push('> ' + l)));
      }
      return;
    }
    if (t === 'UL' || t === 'OL') {
      const items = [...node.children];
      items.forEach((li, i) => {
        const prefix = t === 'UL' ? '- ' : `${i+1}. `;
        const text = inline(li).trim();
        if (text) md.push(prefix + text);
      });
      return;
    }
    if (t === 'TABLE') {
      const rows = [...node.querySelectorAll('tr')];
      if (!rows.length) return;
      const header = [...rows[0].children].map(c => esc(clean(c.innerText).trim()));
      md.push('| ' + header.join(' | ') + ' |');
      md.push('| ' + header.map(_=>'---').join(' | ') + ' |');
      rows.slice(1).forEach(r => {
        const cells = [...r.children].map(c => esc(clean(c.innerText).trim().replace(/\n/g,' ')));
        md.push('| ' + cells.join(' | ') + ' |');
      });
      return;
    }
    if (cls.includes('pk-image')) {
      const line = inline(node);
      if (line) md.push(line);
      return;
    }
    if (t === 'P' || t === 'DIV' || cls.includes('ct-paragraph')) {
      // Emit block per paragraph, but if this p contains an image, still keep it
      const text = inline(node).trim();
      if (text) md.push(text);
      return;
    }
    if (t === 'HR') { md.push('---'); return; }
    // Fallback: iterate children
    [...node.children].forEach(block);
  }

  [...root.children].forEach(block);

  // Deduplicate consecutive blank lines and clean zero-width
  const out = [];
  for (let line of md) {
    line = clean(line);
    if (line === '' && out.length && out[out.length-1] === '') continue;
    out.push(line);
  }
  return JSON.stringify({md: out.join('\n\n'), images: imgs, title: document.title});
})()
'''

def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)[:80].strip('._')
    return name or 'untitled'

def wait_dom(cdp, timeout=30):
    for _ in range(int(timeout*2)):
        rs = cdp.eval('document.readyState')
        pm = cdp.eval("!!document.querySelector('.ProseMirror')")
        if rs=='complete' and pm: return True
        time.sleep(0.5)
    return False

def trigger_lazy_images(cdp, per_img_wait=1.2, max_retries=2):
    """Force learn-city ProseMirror to inject <img data-origin> into each .pk-image span.
    Learn-city uses lazy load that only fires when the pk-image span is scrolled into viewport."""
    # Step 0: expand all collapse panels (pk-collapse) — images inside collapsed sections
    # have display:none and can't be triggered by scrollIntoView until expanded.
    cdp.eval('''(() => {
      // Click every collapsed pk-collapse header. Also force ct-collapse-content to display:block.
      [...document.querySelectorAll('.pk-collapse')].forEach(c => {
        const header = c.querySelector('.pk-collapse-header, .collapse-header, [class*="header"]');
        if (header && !c.classList.contains('open') && !c.classList.contains('expanded')) {
          try { header.click(); } catch(e){}
        }
      });
      // Directly show any hidden collapse content
      [...document.querySelectorAll('.ct-collapse-content, .collapse-content')].forEach(el => {
        el.style.display = 'block';
      });
    })()''')
    time.sleep(0.8)

    n = cdp.eval("document.querySelectorAll('.ProseMirror .pk-image').length") or 0
    if not n:
        return 0
    filled = 0
    for retry in range(max_retries):
        for i in range(n):
            has = cdp.eval(f'''(()=>{{
              const pks=[...document.querySelectorAll('.ProseMirror .pk-image')];
              if (!pks[{i}]) return true;
              if (pks[{i}].querySelector('img[data-origin]')) return true;
              pks[{i}].scrollIntoView({{block:'center', behavior:'instant'}});
              return false;
            }})()''')
            if not has:
                time.sleep(per_img_wait)
        filled = cdp.eval('''(()=>{
          return [...document.querySelectorAll('.ProseMirror .pk-image')].filter(p => p.querySelector('img[data-origin]')).length;
        })()''')
        if filled == n:
            break
    # scroll back
    cdp.eval('window.scrollTo(0,0)')
    time.sleep(0.5)
    return filled

def get_cookies(cdp, domain='.sankuai.com'):
    r = cdp.call('Network.getCookies', {'urls':['https://km.sankuai.com/']}, timeout=15)
    cookies = r.get('cookies', [])
    return '; '.join(f"{c['name']}={c['value']}" for c in cookies)

def guess_ext(url, ctype=None):
    if ctype:
        m = {'image/png':'.png','image/jpeg':'.jpg','image/jpg':'.jpg',
             'image/gif':'.gif','image/webp':'.webp','image/svg+xml':'.svg'}
        for k,v in m.items():
            if k in ctype.lower(): return v
    # fallback from url
    path = urllib.parse.urlparse(url).path.lower()
    for e in ('.png','.jpg','.jpeg','.gif','.webp','.svg'):
        if e in path: return e
    return '.png'

def download_image(url, cookies, referer, out_path):
    req = urllib.request.Request(url, headers={
        'Cookie': cookies,
        'Referer': referer,
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0',
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        ctype = r.headers.get('Content-Type','')
    ext = guess_ext(url, ctype)
    if not str(out_path).endswith(ext):
        out_path = out_path.with_suffix(ext)
    out_path.write_bytes(data)
    return out_path, len(data), ext

def get_target_ws(port, url):
    # Open new tab, get ws
    api = f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe=':/?&=%')}"
    r = urllib.request.urlopen(urllib.request.Request(api, method='PUT'), timeout=10)
    d = json.loads(r.read())
    return d['id'], d['webSocketDebuggerUrl']

def close_tab(port, tab_id):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tab_id}", timeout=5)
    except: pass

def backup_one(port, content_id, out_dir, prefix=''):
    url = f"https://km.sankuai.com/collabpage/{content_id}"
    print(f"{prefix}[{content_id}] opening {url}")
    tab_id, ws_url = get_target_ws(port, url)
    try:
        cdp = CDP(ws_url)
        cdp.call('Page.enable'); cdp.call('Runtime.enable'); cdp.call('Network.enable')
        if not wait_dom(cdp, timeout=30):
            print(f"{prefix}[{content_id}] DOM not ready (may be SSO redirect or permission denied)")
            page_title = cdp.eval('document.title')
            print(f"{prefix}[{content_id}] title={page_title!r}")
            return None
        title = cdp.eval('document.title') or f'doc_{content_id}'
        title = re.sub(r'\s*-\s*学城$', '', title).strip()
        print(f"{prefix}[{content_id}] title={title!r}")

        # small render settle
        time.sleep(2)

        # Trigger lazy image loading via per-image scrollIntoView
        n_pks = cdp.eval("document.querySelectorAll('.ProseMirror .pk-image').length") or 0
        if n_pks:
            filled = trigger_lazy_images(cdp)
            print(f"{prefix}[{content_id}] lazy imgs: {filled}/{n_pks} triggered")

        r = cdp.eval(DOM_TO_MD_JS, timeout=60)
        try:
            data = json.loads(r) if isinstance(r,str) else r
            if not isinstance(data, dict) or 'md' not in data:
                raise ValueError('bad shape')
        except Exception as e:
            print(f"{prefix}[{content_id}] parse failed ({e}): {str(r)[:400]}")
            return None
        if 'error' in data:
            print(f"{prefix}[{content_id}] {data['error']}")
            return None
        md = data['md']
        images = data.get('images', [])

        # Get cookies (once per doc)
        cookies = get_cookies(cdp)

        # Assets dir
        base_name = f"{content_id}_{sanitize(title)}"
        assets_dir = out_dir / f"{content_id}_assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Download images
        ext_map = {}
        for img in images:
            fname = f"图片{img['idx']}"
            out_path = assets_dir / fname
            try:
                saved, size, ext = download_image(img['url'], cookies, url, out_path)
                ext_map[img['idx']] = ext
                print(f"{prefix}[{content_id}]   img{img['idx']} → {saved.name} ({size} bytes)")
                # small jitter between image requests
                time.sleep(random.uniform(0.3, 1.2))
            except Exception as e:
                print(f"{prefix}[{content_id}]   img{img['idx']} FAILED: {e}")
                ext_map[img['idx']] = '.png'

        # Substitute placeholders
        md = md.replace('__ASSETS__', f"{content_id}_assets")
        # replace __EXT__ per idx
        def sub_ext(m):
            idx = int(m.group(1))
            return f"图片{idx}{ext_map.get(idx,'.png')}"
        md = re.sub(r'图片(\d+)__EXT__', sub_ext, md)

        md_path = out_dir / f"{base_name}.md"
        md_path.write_text(md, encoding='utf-8')
        print(f"{prefix}[{content_id}] → {md_path.name} ({len(md)} chars, {len(images)} imgs)")
        return md_path
    finally:
        try: cdp.close()
        except: pass
        close_tab(port, tab_id)

def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--content-id', help='single content id')
    g.add_argument('--content-ids', help='comma separated list')
    g.add_argument('--content-ids-file', help='newline separated file')
    p.add_argument('--out', required=True, help='output directory')
    p.add_argument('--port', type=int, default=int(os.environ.get('KM_EDGE_PORT','9333')))
    p.add_argument('--min-interval', type=float, default=15.0)
    p.add_argument('--max-interval', type=float, default=45.0)
    args = p.parse_args()

    ids = []
    if args.content_id:
        ids = [args.content_id.strip()]
    elif args.content_ids:
        ids = [x.strip() for x in args.content_ids.split(',') if x.strip()]
    elif args.content_ids_file:
        ids = [x.strip() for x in Path(args.content_ids_file).read_text().splitlines() if x.strip()]

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # sanity check Edge up
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{args.port}/json/version', timeout=3).read()
    except:
        print(f'Edge debug not on 127.0.0.1:{args.port}. Run scripts/start-edge.sh first.')
        sys.exit(2)

    results = []
    for i, cid in enumerate(ids):
        if i > 0:
            sleep_s = random.uniform(args.min_interval, args.max_interval)
            print(f"...sleep {sleep_s:.1f}s to avoid detection")
            time.sleep(sleep_s)
        r = None
        for attempt in range(2):
            try:
                r = backup_one(args.port, cid, out_dir, prefix=f"({i+1}/{len(ids)}) ")
                if r: break
            except Exception as e:
                print(f"({i+1}/{len(ids)}) [{cid}] attempt {attempt+1} FAILED: {e}")
            if attempt == 0:
                # jitter before retry
                time.sleep(random.uniform(5, 12))
                print(f"({i+1}/{len(ids)}) [{cid}] retrying...")
        results.append((cid, r))

    ok = sum(1 for _,r in results if r)
    print(f"\ndone: {ok}/{len(ids)} ok")
    for cid, r in results:
        print(f"  {cid} → {r.name if r else 'FAILED'}")

if __name__ == '__main__':
    main()
