#!/usr/bin/env python3
"""Typeset a Dan document: working markdown + images -> self-contained HTML and
an A4 PDF, in the PFC report layout.

    python3 build.py "<folder>/<Title>.md"

    1. parse the working markdown                          (dmd.py)
    2. measure every block in headless Chrome, at the real column width,
       including where each paragraph's lines break
    3. flow the blocks into sheets. A paragraph may run on to the next page,
       keeping at least two lines on each side; a heading or bold lead-in never
       ends a page, it keeps two lines of what it introduces; an image that
       misses by a little is reduced (by 20% at most) to fit; nothing else moves
    4. render, measure the real sheets, reflow any page that overflows
    5. gates: Dan's words and figures unchanged           (textcheck.py)
              every supplied image placed, once
              no markdown left showing in the output
              no page clipped
    6. print to PDF through Chrome, then render every page to PNG so the pages
       can be looked at before anything is delivered

Nothing is written to HTML/ or PDFs/ unless every gate passes. The draft HTML
stays in the workings folder either way, so a failure can be inspected.

Where things go, relative to the working markdown:
    <Title>.md                       the working file (this script's input)
    PDFs/<Title>.pdf                 deliverable
    HTML/<Title>.html                deliverable, self-contained
    <Workings>/                      from the frontmatter; images, source, previews
"""
import base64
import datetime
import html
import json
import mimetypes
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ASSETS = HERE.parent / 'assets'
sys.path.insert(0, str(HERE))
import dmd          # noqa: E402
import system       # noqa: E402
import textcheck    # noqa: E402

DISCLAIMER = ('This document is non-independent investment research and a marketing '
              'communication.')
# The PFC contact box, word for word.
CONTACT = '''<div class="contactbox" data-skip>
  <div class="cbt">Contact</div>
  <div class="cbl">
    <div>+44 (0) 1534 639998</div>
    <div class="w">paulfrasercollectibles.com</div>
    <div>info@paulfrasercollectibles.com</div>
  </div>
</div>'''

SAFETY = 3.0          # px held back on every page against sub-pixel rounding
SHRINK = 0.20         # the most an image is reduced to fit the end of a page
PX_PER_MM = 96 / 25.4
STARTERS = {'h2', 'h3', 'h4', 'quote', 'figure',      # typesetter.css: these take the collapsed gap
            'cards', 'panels', 'box', 'contactpanel', 'beside'}
TOPZERO = {'h2', 'h3', 'figure'}                    # typesetter.css: no top margin at a page top

PLACEHOLDER = re.compile(r'\b(text to go here|to go here|lorem ipsum|placeholder|tbc|tbd|xxx+|'
                         r'insert (?:text|copy|image|chart|photo|picture|graph|here))\b', re.I)
POINTS_AT_IMAGE = re.compile(r'\((?:above|below|left|right|pictured|see (?:image|chart|photo|picture))\)'
                             r'|\bpictured (?:above|below|here)\b'
                             r'|\bthe (?:image|chart|photo|picture|graph|photograph) (?:above|below)\b', re.I)
MARKDOWN_LEFT = re.compile(r'\*\*|(?<![\w])__|\]\(|\[\^|(?:^|\s)#{1,6}\s|\|\s*:?-{3}|(?:^|\s):::')


# ------------------------------------------------------------------ Chrome

CHROME = None


def chrome(*args, timeout=180):
    # Do not add --user-data-dir: a fresh profile made headless Chrome hang on
    # the machine this was built on (tested 28 Sep 2026: the plain flags returned
    # in 0.6s, a temp profile never returned).
    global CHROME
    CHROME = CHROME or system.find_chrome()
    return system.run([CHROME, '--headless=new', '--disable-gpu', *args], timeout=timeout)


file_url = system.file_url


def dom_json(doc, marker):
    """Load a document in Chrome, let its script write JSON into #marker, return it."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='dan-probe-')) / 'probe.html'
    tmp.write_text(doc, encoding='utf-8')
    out = chrome('--virtual-time-budget=15000', '--dump-dom', file_url(tmp)).stdout
    m = re.search(r'<div id="%s">(.*?)</div>' % marker, out, re.S)
    if not m:
        sys.exit('Chrome did not return measurements. Is the document valid?')
    return json.loads(html.unescape(m.group(1)))


# ------------------------------------------------------------------ document

def css():
    return ((ASSETS / 'report.css').read_text(encoding='utf-8') + '\n'
            + (ASSETS / 'typesetter.css').read_text(encoding='utf-8'))


def data_uri(path):
    mime = mimetypes.guess_type(str(path))[0] or 'image/png'
    return 'data:%s;base64,%s' % (mime, base64.b64encode(pathlib.Path(path).read_bytes()).decode())


LOGO = None


def logo():
    global LOGO
    LOGO = LOGO or data_uri(ASSETS / 'pfc-logo-navy.png')
    return LOGO


def head(title, extra_css=''):
    return ('<!DOCTYPE html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
            '<title>%s</title>\n<style>\n%s\n%s\n</style>\n</head>\n<body>\n'
            % (html.escape(title), css(), extra_css))


def sheet(doc, units_html, first, last, blank=False):
    """One A4 sheet. first: full header and title band. last: the disclaimer."""
    out = ['<section class="sheet"%s>' % (' id="%s"' % blank if blank else '')]
    out.append('  <header class="band%s" data-skip>' % ('' if first else ' compact'))
    out.append('    <img src="%s" alt="Paul Fraser Collectibles">' % logo())
    out.append('    <div class="tag">%s</div>' % html.escape(doc['tag']))
    out.append('  </header>')
    if first:
        out.append('  <div class="titleband">')
        out.append('    <h1>%s</h1>' % html.escape(doc['title']))
        out.append('    <div class="meta">')
        out.append('      <div data-skip><b>DATE</b>&nbsp; %s</div>' % html.escape(doc['date']))
        if doc['focus']:
            out.append('      <div><b data-skip>FOCUS</b>&nbsp; %s</div>' % html.escape(doc['focus']))
        out.append('    </div>')
        out.append('  </div>')
    out.append('  <div class="content">')
    blks = ['    <div class="blk">\n%s\n    </div>' % u for u in units_html]
    if first and doc.get('side'):
        # page one in two columns: the text, and the key-figures sidebar
        out.append('    <div class="cols"><div class="maincol">')
        out += blks
        out.append('    </div><aside class="side">%s</aside></div>' % doc['side'])
    else:
        out += blks
    out.append('  </div>')
    if last and doc['disclaimer']:
        out.append('  <div class="pagefoot" data-skip><div class="disc">%s</div></div>'
                   % html.escape(doc['disclaimer']))
    else:
        out.append('  <div class="pagefoot"></div>')
    out.append('</section>')
    return '\n'.join(out)


def figure_html(b, scale=1.0):
    e = b.extra
    if not e['path'].exists():
        sys.exit('image not found: %s\n  (referenced as %s)' % (e['path'], e['src']))
    if 'px' not in e:
        px_w, px_h = dmd.image_size(e['path'])
        w, h = dmd.image_box(px_w, px_h, e['opts'])
        e.update(px=(px_w, px_h), mm=(w, h), uri=data_uri(e['path']))
    w, h = round(e['mm'][0] * scale, 1), round(e['mm'][1] * scale, 1)
    cap =dmd.inline(e['caption']) if e['caption'] else ''
    cr = ' <span class="cr">%s</span>' % dmd.inline(e['credit']) if e['credit'] else ''
    fc = '\n  <figcaption>%s%s</figcaption>' % (cap, cr) if (cap or cr) else ''
    return ('<figure class="photo supplied">\n  <img src="%s" alt="" style="width:%smm;height:%smm">%s\n</figure>'
            % (e['uri'], w, h, fc))


# ------------------------------------------------------------------ units

def make_units(blocks):
    """Glue each heading and lead-in to the block after it. A unit is what a page
    break may never fall between."""
    units, cur = [], []
    for b in blocks:
        cur.append(b)
        if not b.glue:
            units.append(cur)
            cur = []
    if cur:
        units.append(cur)
    return units


def unit_html(u):
    return '\n'.join(b.html for b in u)


def can_split(u):
    return u[-1].kind == 'p' and not u[-1].glue


PROBE_CSS = '''
#measure,#measure-narrow{height:auto!important;overflow:visible!important;}
#measure .content,#measure-narrow .content{overflow:visible!important;flex:none!important;}
#measure-narrow .cols{height:auto!important;}
.m-zb > .blk > :last-child{margin-bottom:0!important;}
.m-zt > .blk > :is(h2,h3,.photo.supplied):first-child{margin-top:0!important;}
'''

# For a paragraph that may run over a page break, the probe finds the word that
# starts each line and hands back the paragraph cut at every line from the second
# to the second-last, as two pieces of HTML. Range.cloneContents closes and
# reopens any bold, italic or link the cut falls inside, so the words and their
# markup survive intact; textcheck.py proves it afterwards.
PROBE_JS = '''<script>
function lineStarts(p){
  var w = document.createTreeWalker(p, NodeFilter.SHOW_TEXT), node, out = [], last = null;
  var r = document.createRange();
  while ((node = w.nextNode())) {
    var re = /\\S+/g, m;
    while ((m = re.exec(node.data))) {
      r.setStart(node, m.index); r.setEnd(node, m.index + 1);
      var rs = r.getClientRects(); if (!rs.length) continue;
      if (last === null || rs[0].top > last + 2) { out.push({node: node, off: m.index, top: rs[0].top}); last = rs[0].top; }
    }
  }
  return out;
}
function cut(p, st){
  var a = document.createRange(); a.setStart(p, 0); a.setEnd(st.node, st.off);
  var b = document.createRange(); b.setStart(st.node, st.off); b.setEnd(p, p.childNodes.length);
  var da = document.createElement('div'); da.appendChild(a.cloneContents());
  var db = document.createElement('div'); db.appendChild(b.cloneContents());
  return [da.innerHTML, db.innerHTML];
}
window.addEventListener('load', function(){
  var o = {boxes:{}, units:{}};
  ['first','firstlast','mid','last'].forEach(function(k){
    var c = document.querySelector('#sk-' + k + ' .content');
    o.boxes[k] = c.getBoundingClientRect().height - parseFloat(getComputedStyle(c).paddingTop);
  });
  var sd = document.querySelector('#sk-first .side');
  if (sd) {
    var st = sd.getBoundingClientRect().top, sb = 0;
    Array.prototype.forEach.call(sd.children, function(e){ sb = Math.max(sb, e.getBoundingClientRect().bottom - st); });
    o.side = sb + parseFloat(getComputedStyle(sd).paddingBottom);
  }
  document.querySelectorAll('#measure .m, #measure-narrow .m').forEach(function(m){
    var narrow = !!m.closest('#measure-narrow');
    var u = m.getAttribute('data-u'), v = m.getAttribute('data-v') + (narrow ? '1' : ''), blk = m.firstElementChild;
    var r = o.units[u] || (o.units[u] = {});
    var br = blk.getBoundingClientRect();
    r[v] = br.height;
    if (v !== 'n') return;
    // tables and lists: where each row or item starts, so the page flow can cut
    // between any two of them
    var t = blk.querySelector(':scope > table:last-child');
    if (t) {
      var tr = t.getBoundingClientRect();
      r.tail = {top: tr.top - br.top, h: tr.height, mb: parseFloat(getComputedStyle(t).marginBottom),
                head: t.tHead ? t.tHead.getBoundingClientRect().height : 0,
                tops: Array.prototype.map.call(t.tBodies[0].rows, function(x){ return x.getBoundingClientRect().top - tr.top; })};
    }
    var l = blk.querySelector(':scope > ul:last-child, :scope > ol:last-child');
    if (l) {
      var lr = l.getBoundingClientRect();
      r.tail = {top: lr.top - br.top, h: lr.height, mb: parseFloat(getComputedStyle(l).marginBottom), head: 0,
                tops: Array.prototype.map.call(l.children, function(x){ return x.getBoundingClientRect().top - lr.top; })};
    }
    var p = blk.querySelector(':scope > p[data-sp]');
    if (p) {
      var pr = p.getBoundingClientRect(), st = lineStarts(p);
      r.ptop = pr.top - br.top; r.ph = pr.height; r.pmb = parseFloat(getComputedStyle(p).marginBottom);
      r.lines = st.length; r.splits = [];
      for (var L = 2; L <= st.length - 2; L++) {
        var h = cut(p, st[L]);
        r.splits.push({L: L, a: st[L].top - st[0].top, ha: h[0], hb: h[1]});
      }
    }
  });
  document.querySelectorAll('section').forEach(function(s){ s.remove(); });
  var d = document.createElement('div'); d.id = 'probe-out';
  d.textContent = JSON.stringify(o); document.body.appendChild(d);
});
</script>'''


def measure(doc, units):
    parts = [head(doc['title'], PROBE_CSS)]
    parts.append(sheet(doc, [], True, False, blank='sk-first'))
    parts.append(sheet(doc, [], True, True, blank='sk-firstlast'))
    parts.append(sheet(doc, [], False, False, blank='sk-mid'))
    parts.append(sheet(doc, [], False, True, blank='sk-last'))
    parts.append('<section class="sheet" id="measure"><div class="content">')
    for i, u in enumerate(units):
        h = unit_html(u)
        hn = h
        if can_split(u):
            lead = unit_html(u[:-1])
            hn = (lead + '\n' if lead else '') + u[-1].html.replace('<p>', '<p data-sp>', 1)
        for v, cls, body in (('n', '', hn), ('zb', ' m-zb', h), ('zt', ' m-zt', h)):
            parts.append('<div class="m%s" data-u="%d" data-v="%s"><div class="blk">%s</div></div>'
                         % (cls, i, v, body))
    parts.append('</div></section>')
    if doc.get('side'):
        # page one's text column is narrower, so every block is measured there too
        parts.append('<section class="sheet" id="measure-narrow"><div class="content"><div class="cols">'
                     '<div class="maincol">')
        for i, u in enumerate(units):
            h = unit_html(u)
            for v, cls in (('n', ''), ('zb', ' m-zb'), ('zt', ' m-zt')):
                parts.append('<div class="m%s" data-u="%d" data-v="%s"><div class="blk">%s</div></div>'
                             % (cls, i, v, h))
        parts.append('</div><aside class="side"></aside></div></div></section>')
    parts.append(PROBE_JS + '\n</body></html>')
    return dom_json('\n'.join(parts), 'probe-out')


MIN_KEEP = 2      # lines, rows or items left on each side of a page break


def records(units, m):
    """What the paginator needs about each unit, straight from the measurements."""
    recs = []
    for i, u in enumerate(units):
        r = m['units'][str(i)]
        last, tail = u[-1], None
        t = r.get('tail')
        if t and last.kind == 'table' and len(last.extra.get('rows', [])) == len(t['tops']):
            tail = dict(t, kind='table', head_html=last.extra['head'], items=list(last.extra['rows']), cont=False)
        elif t and last.kind in ('ul', 'ol') and len(last.extra.get('items', [])) == len(t['tops']):
            tail = dict(t, kind=last.kind, items=list(last.extra['items']), start=1)
        elif can_split(u) and r.get('splits'):
            tail = dict(kind='p', top=r['ptop'], h=r['ph'], mb=r['pmb'], splits=r['splits'])
        recs.append(dict(
            html=unit_html(u), H=r['n'], ZB=r['zb'], ZT=r['zt'],
            H1=r.get('n1'), ZB1=r.get('zb1'), ZT1=r.get('zt1'),
            starter=u[0].kind in STARTERS, topz=u[0].kind in TOPZERO,
            brk=any(b.break_before for b in u), lead=unit_html(u[:-1]), tail=tail,
            fig=u[0] if len(u) == 1 and u[0].kind == 'figure' else None,
            text=plain(unit_html(u))))
    return recs


def plain(h):
    return ' '.join(re.sub(r'<[^>]+>', ' ', h).split())[:50]


def cuts(u):
    """Every place a page break may fall inside this unit, as (label, before,
    after), shortest `before` first. A paragraph is cut at a line, a table
    between rows (the header row repeats, marked as layout), a list between
    items. The heading or lead-in the unit starts with always stays with the
    first part, and each side keeps at least MIN_KEEP lines, rows or items."""
    t = u['tail']
    if not t:
        return []
    lead = u['lead'] + '\n' if u['lead'] else ''
    keep_top = u['H'] - u['ZT']
    out = []
    if t['kind'] == 'p':
        n = len(t['splits']) + 3
        for s in t['splits']:
            ah = t['top'] + s['a']
            bh = t['h'] - s['a'] + t['mb']
            a = dict(u, html=lead + '<p class="split-a">%s</p>' % s['ha'], H=ah, ZB=ah, ZT=ah - keep_top,
                     tail=None, brk=False)
            b = dict(u, html='<p class="split-b">%s</p>' % s['hb'], H=bh, ZB=bh - t['mb'], ZT=bh,
                     starter=False, topz=False, brk=False, lead='', tail=None, fig=None, text=plain(s['hb']))
            out.append(('%d of %d lines' % (s['L'], n), a, b))
        return out
    items, tops, n = t['items'], t['tops'], len(t['items'])
    for r in range(MIN_KEEP, n - MIN_KEEP + 1):
        ah = t['top'] + tops[r]
        rest = t['h'] - tops[r]
        if t['kind'] == 'table':
            skip = lambda hh: hh.replace('<thead>', '<thead data-skip>', 1)
            head_a = skip(t['head_html']) if t['cont'] else t['head_html']
            a_html = dmd.table_html(head_a, items[:r]).replace('<table>', '<table class="split-a">', 1)
            b_html = dmd.table_html(skip(t['head_html']), items[r:])
            bh = t['head'] + rest + t['mb']
            btail = dict(t, top=0.0, h=t['head'] + rest, tops=[t['head'] + x - tops[r] for x in tops[r:]],
                         items=items[r:], cont=True)
            what = 'rows'
        else:
            tag = t['kind']
            sa = ' start="%d"' % t['start'] if tag == 'ol' and t['start'] > 1 else ''
            sb = ' start="%d"' % (t['start'] + r) if tag == 'ol' else ''
            a_html = '<%s class="split-a"%s>%s</%s>' % (tag, sa, ''.join(items[:r]), tag)
            b_html = '<%s%s>%s</%s>' % (tag, sb, ''.join(items[r:]), tag)
            bh = rest + t['mb']
            btail = dict(t, top=0.0, h=rest, tops=[x - tops[r] for x in tops[r:]], items=items[r:],
                         start=t['start'] + r)
            what = 'items'
        a = dict(u, html=lead + a_html, H=ah, ZB=ah, ZT=ah - keep_top, tail=None, brk=False)
        b = dict(u, html=b_html, H=bh, ZB=bh, ZT=bh, starter=False, topz=False, brk=False, lead='',
                 tail=btail, fig=None, text=plain(b_html))
        out.append(('%d of %d %s' % (r, n, what), a, b))
    return out


# ------------------------------------------------------------------ pagination

def paginate(recs, boxes, adjust, narrow=False):
    """Fill each page in reading order. Returns [[rec, ...], ...] and notes on
    what was cut or reduced."""
    queue = list(recs)
    pages, cur, used, k, notes = [], [], 0.0, 0, []

    def box(k):
        return (boxes['first'] if k == 0 else boxes['mid']) - SAFETY - adjust.get(k, 0)

    def new_page():
        nonlocal cur, used, k
        pages.append(cur)
        cur, used, k = [], 0.0, k + 1

    def on_page(u, k):
        # page one beside the sidebar: the narrow measurements, and no cutting or
        # shrinking there, because those were worked out at full width
        if k == 0 and narrow and u.get('H1') is not None:
            return dict(u, H=u['H1'], ZB=u['ZB1'], ZT=u['ZT1'], tail=None, fig=None)
        return u

    while queue:
        orig = queue.pop(0)
        if orig['brk'] and cur:
            new_page()
        u = on_page(orig, k)
        first = not cur
        top = (u['H'] - u['ZT']) if first and u['topz'] else 0.0
        save = (cur[-1]['H'] - cur[-1]['ZB']) if cur and u['starter'] else 0.0
        room = box(k) - used + save
        h = u['H'] - top
        if h <= room:
            cur.append(u)
            used += h - save
            continue
        # run on to the next page: as much as fits here, never less than
        # MIN_KEEP on either side
        fit = [c for c in cuts(u) if c[1]['H'] - top <= room]
        if fit:
            label, a, b = fit[-1]
            cur.append(a)
            used += a['H'] - top - save
            notes.append('page %d runs on to page %d (%s on page %d)' % (k + 1, k + 2, label, k + 1))
            new_page()
            queue.insert(0, b)
            continue
        # an image that misses by a little is reduced to fit, never by more than SHRINK
        if u['fig'] is not None and not first:
            e = u['fig'].extra
            img_px = e['mm'][1] * PX_PER_MM          # the unit was measured at the full size
            need = h - room + 1
            if need <= img_px * SHRINK:
                scale = (img_px - need) / img_px
                shrunk = dict(u, html=figure_html(u['fig'], scale), H=u['H'] - need, ZB=u['ZB'] - need,
                              ZT=u['ZT'] - need, scale=scale)
                cur.append(shrunk)
                used += shrunk['H'] - save
                notes.append('page %d: %s reduced by %.0f%% to fit' % (k + 1, e['path'].name, 100 * need / img_px))
                continue
        if first:                      # taller than a page and nowhere to cut: main() refuses these
            cur.append(u)
            used += h
            continue
        new_page()
        queue.insert(0, orig)
    if cur:
        pages.append(cur)
    return pages, notes


def page_fill(pages, boxes, adjust):
    """(used, box) per page, the way paginate counted them."""
    out = []
    for k, p in enumerate(pages):
        used = 0.0
        for n, u in enumerate(p):
            top = (u['H'] - u['ZT']) if n == 0 and u['topz'] else 0.0
            save = (p[n - 1]['H'] - p[n - 1]['ZB']) if n and u['starter'] else 0.0
            used += u['H'] - top - save
        key = ('firstlast' if len(pages) == 1 else 'first' if k == 0 else
               'last' if k == len(pages) - 1 else 'mid')
        out.append((used, boxes[key] - SAFETY - adjust.get(k, 0)))
    return out


def layout(recs, boxes, adjust, narrow=False):
    """Paginate, then make room for the disclaimer on the last page. The last
    page's footer is taller, and which page is last is only known at the end."""
    while True:
        pages, notes = paginate(recs, boxes, adjust, narrow)
        used, box = page_fill(pages, boxes, adjust)[-1]
        if used <= box:
            return pages, notes
        k = len(pages) - 1
        adjust[k] = adjust.get(k, 0) + (used - box) + 1


# ------------------------------------------------------------------ real sheets

CHECK_JS = '''<script>
window.addEventListener('load', function(){
  var out = Array.prototype.map.call(document.querySelectorAll('.sheet'), function(s, i){
    var c = s.querySelector('.content'), cr = c.getBoundingClientRect();
    var pad = parseFloat(getComputedStyle(c).paddingTop), bottom = pad;
    var host = s.querySelector('.maincol') || c;
    Array.prototype.forEach.call(host.children, function(b){
      bottom = Math.max(bottom, b.getBoundingClientRect().bottom - cr.top);
    });
    var sd = s.querySelector('.side'), sover = -1e9;
    if (sd) {
      var sb = 0;
      Array.prototype.forEach.call(sd.children, function(e){ sb = Math.max(sb, e.getBoundingClientRect().bottom - cr.top); });
      sover = sb + parseFloat(getComputedStyle(sd).paddingBottom) - cr.height;
    }
    var last = host.lastElementChild;
    var txt = last ? (last.textContent || '').replace(/\\s+/g, ' ').trim() : '';
    if (!txt && last && last.querySelector('img')) txt = '[image]';
    return {page: i + 1, box: cr.height - pad, used: bottom - pad, over: Math.max(bottom - cr.height, sover),
            last: txt.slice(-50)};
  });
  document.querySelectorAll('section').forEach(function(s){ s.remove(); });
  var d = document.createElement('div'); d.id = 'check-out';
  d.textContent = JSON.stringify(out); document.body.appendChild(d);
});
</script>'''


def render(doc, pages):
    parts = [head(doc['title'])]
    for k, p in enumerate(pages):
        parts.append(sheet(doc, [u['html'] for u in p], k == 0, k == len(pages) - 1))
    parts.append('</body>\n</html>\n')
    return '\n'.join(parts)


def check_sheets(doc_html):
    return dom_json(doc_html.replace('</body>', CHECK_JS + '\n</body>'), 'check-out')


# ------------------------------------------------------------------ main

def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:60] or 'document'


def main():
    system.utf8_output()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit('usage: build.py "<folder>/<Title>.md"')
    md = pathlib.Path(args[0]).expanduser().resolve()
    if not md.exists():
        sys.exit('not found: %s' % md)
    meta, blocks = dmd.parse(md)

    title = meta.get('Title', '').strip()
    if not title:
        sys.exit('The frontmatter has no Title. The title band needs one, taken from the article.')
    disclaimer = meta.get('Disclaimer', None)
    doc = dict(
        title=title,
        tag=meta.get('Tag', '').strip() or 'MARKET REPORT',
        date=meta.get('Date', '').strip() or datetime.date.today().isoformat(),
        focus=meta.get('Focus', '').strip(),
        disclaimer=DISCLAIMER if disclaimer is None or disclaimer == '' else
        ('' if disclaimer.strip().lower() in ('none', 'false', 'no') else disclaimer.strip()),
    )
    contact = dmd.truthy(meta.get('Contact box'), default=True)
    removed = meta.get('Removed') or []
    removed = removed if isinstance(removed, list) else [removed]
    work = (md.parent / meta['Workings']).resolve() if meta.get('Workings') else md.parent / 'WORKINGS' / slug(md.stem)
    src = meta.get('Source', '').strip()
    source = (md.parent / src).resolve() if src and not os.path.isabs(src) else pathlib.Path(src) if src else None
    if not source or not source.exists():
        sys.exit('The frontmatter Source must point at Dan\'s original file (found: %r). '
                 'The text check compares against it.' % src)

    def fig(b, beside=False):
        # an image beside text, or in a card, defaults to half the column
        if beside and 'w' not in b.extra['opts'] and 'h' not in b.extra['opts']:
            b.extra['opts']['w'] = '84'
        b.html = figure_html(b)
        return b.html

    side = [b for b in blocks if b.kind == 'keyfigures']
    if len(side) > 1:
        sys.exit('Only one ::: keyfigures box: it is the page-one sidebar.')
    blocks = [b for b in blocks if b.kind != 'keyfigures']
    doc['side'] = side[0].html if side else ''
    for b in blocks:
        if b.extra.get('container'):
            b.html = dmd.compose(b, fig)
        elif b.kind == 'figure':
            fig(b)
    figures = [b for b in dmd.walk(blocks) if b.kind == 'figure']

    units = make_units(blocks)
    if contact:
        units[-1] = units[-1] + [dmd.Block('contact', CONTACT)]

    print('building  %s' % md.name)
    print('  %d blocks in %d units a page break may not fall inside, %d image(s)'
          % (len(blocks), len(units), len(figures)))

    m = measure(doc, units)
    recs = records(units, m)
    if doc['side'] and m.get('side', 0) > m['boxes']['first'] - SAFETY:
        sys.exit('The key-figures sidebar is taller than page one (%.0fpx, room %.0fpx): give it fewer figures.'
                 % (m['side'], m['boxes']['first']))
    room = m['boxes']['mid'] - SAFETY
    for r in recs:
        if r['H'] > room and not cuts(r):
            sys.exit('A block is taller than a page (%.0fpx, room %.0fpx) and has nowhere to break:\n  %s\n'
                     'Give an image a smaller {h=...}, or break the passage with a heading.'
                     % (r['H'], room, r['text']))

    adjust = {}
    for attempt in range(8):
        pages, notes = layout(recs, m['boxes'], adjust, bool(doc['side']))
        doc_html = render(doc, pages)
        real = check_sheets(doc_html)
        over = [r for r in real if r['over'] > 0.5]
        if not over:
            break
        for r in over:
            adjust[r['page'] - 1] = adjust.get(r['page'] - 1, 0) + r['over'] + 2
    work.mkdir(parents=True, exist_ok=True)
    draft = work / (md.stem + '.draft.html')
    draft.write_text(doc_html, encoding='utf-8')

    # ----------------------------------------------------------- gates
    failed = []
    print('\npages     %d sheets' % len(real))
    for r in real:
        state = 'CLIPPED by %.0fpx' % r['over'] if r['over'] > 0.5 else '%3.0f%% full, %3.0fmm spare' % (
            100 * r['used'] / r['box'], (r['box'] - r['used']) / PX_PER_MM)
        print('  %2d  %-26s ends: ...%s' % (r['page'], state, r['last']))
        k = r['page'] - 1
        spare_mm = (r['box'] - r['used']) / PX_PER_MM
        if k + 1 < len(pages) and spare_mm > 30 and pages[k + 1][0]['fig'] is not None:
            f = pages[k + 1][0]['fig'].extra
            print('      ^ short because %s (%.0fmm tall) did not fit here. Move its line a paragraph or two '
                  'earlier within its section, or give it {h=%d}.' % (f['path'].name, f['mm'][1], max(40, spare_mm - 12)))
    for n in notes:
        print('      %s' % n)
    if any(r['over'] > 0.5 for r in real):
        failed.append('a page is clipped')

    print()
    s_tok, o_tok, furniture, diffs, accepted = textcheck.compare(source, draft, doc['tag'], removed)
    textcheck.report(s_tok, o_tok, furniture, diffs, accepted)
    if diffs:
        failed.append('the text differs from Dan\'s original')

    print('\nimages    %d placed' % len(figures))
    img_dir = work / 'images'
    supplied = sorted(p.resolve() for p in img_dir.iterdir() if p.is_file() and not p.name.startswith('.')) \
        if img_dir.exists() else []
    placed = [b.extra['path'] for b in figures]
    scale = {id(u['fig']): u.get('scale', 1.0) for p in pages for u in p if u['fig'] is not None}
    for b in figures:
        e = b.extra
        s = scale.get(id(b), 1.0)
        w, h = e['mm'][0] * s, e['mm'][1] * s
        dpi = e['px'][0] / (w / 25.4)
        warn = '   LOW RESOLUTION, soft in print' if dpi < 100 else ''
        print('  %-40s %4dx%-4d px  ->  %5.1f x %5.1f mm, %3.0f dpi%s%s'
              % (e['path'].name[:40], e['px'][0], e['px'][1], w, h, dpi,
                 ', reduced %.0f%% to fit' % (100 - 100 * s) if s < 1 else '', warn))
        print('      caption: %s' % (e['caption'] or '(none)') + ('   credit: %s' % e['credit'] if e['credit'] else ''))
    for p in supplied:
        if p not in placed:
            print('  FAIL  supplied but not placed: %s' % p.name)
            failed.append('an image was supplied and not placed')
    for p in set(placed):
        if placed.count(p) > 1:
            print('  FAIL  placed %d times: %s' % (placed.count(p), p.name))
            failed.append('an image is placed twice')

    text, _ = textcheck.output_text(draft)
    left = sorted(set(MARKDOWN_LEFT.findall(text)))
    print('\nmarkup    %s' % ('PASS: no markdown left showing' if not left else
                              'FAIL: markdown left in the output: %s' % ', '.join(repr(x) for x in left)))
    if left:
        failed.append('markdown is showing in the output')
    if meta.get('_missing_notes'):
        print('  FAIL  footnote reference with no note: %s' % ', '.join(meta['_missing_notes']))
        failed.append('a footnote has no note')

    # Warnings: Dan's own text, reported and never touched.
    warns = []
    for mt in PLACEHOLDER.finditer(text):
        ctx = ' '.join(text[max(0, mt.start() - 60):mt.end() + 20].split())
        warns.append('placeholder in the article: "...%s..."' % ctx)
    for mt in POINTS_AT_IMAGE.finditer(text):
        ctx = ' '.join(text[max(0, mt.start() - 70):mt.end() + 10].split())
        warns.append('text points at an image; check one is there: "...%s..."' % ctx)
    for k in meta.get('_unused_notes', []):
        warns.append('footnote defined but never referenced: [^%s]' % k)
    if warns:
        print('\nwarnings  (Dan\'s text, left exactly as written; say so in the handover)')
        for w in warns:
            print('  warn  %s' % w)

    print('\nfurniture (layout, not Dan\'s text): header tag "%s", date %s%s%s'
          % (doc['tag'], doc['date'], ', contact box' if contact else '',
             ', disclaimer' if doc['disclaimer'] else ''))

    if failed:
        print('\nNOT BUILT. Failed: %s.' % '; '.join(dict.fromkeys(failed)))
        print('Draft kept for inspection: %s' % draft)
        sys.exit(1)

    # ----------------------------------------------------------- deliverables
    # named after the Title, which is what the document is called, not after
    # the working file, which may carry ingest's first guess
    # (Windows also refuses a name ending in a dot or a space)
    name = re.sub(r'[\\/:*?"<>|#^\[\]]+', '', doc['title']).strip()[:120].rstrip('. ') or md.stem
    out_html = md.parent / 'HTML' / (name + '.html')
    out_pdf = md.parent / 'PDFs' / (name + '.pdf')
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(doc_html, encoding='utf-8')
    draft.unlink()
    if out_pdf.exists():
        out_pdf.unlink()
    chrome('--no-pdf-header-footer', '--run-all-compositor-stages-before-draw',
           '--virtual-time-budget=15000', '--print-to-pdf=' + str(out_pdf), file_url(out_html))
    if not out_pdf.exists():
        sys.exit('Chrome produced no PDF.')
    data = out_pdf.read_bytes()
    n_pdf = len(re.findall(rb'/Type\s*/Page[^s]', data))
    print('\nwrote     %s' % out_html)
    print('wrote     %s  (%d pages, %d KB)' % (out_pdf, n_pdf, len(data) // 1024))
    if n_pdf != len(pages):
        print('  FAIL  the PDF has %d pages for %d sheets: a sheet spilled onto a second page.'
              % (n_pdf, len(pages)))
        sys.exit(1)

    prev = work / 'previews'
    prev.mkdir(parents=True, exist_ok=True)
    for old in prev.glob('page-*.png'):
        old.unlink()
    if system.tool('pdftoppm'):
        subprocess.run([system.tool('pdftoppm'), '-r', '70', '-png', str(out_pdf), str(prev / 'page')], check=True)
        how = 'rendered from the PDF itself'
    else:
        how = screenshot_previews(doc, pages, prev)
    shots = sorted(prev.glob('page-*.png'))
    print('previews  %d page images in %s (%s)' % (len(shots), prev, how))
    print('\nNow look at every page image before delivering: header on each page, nothing cut,\n'
          'images sharp and in proportion, no heading alone at the foot of a page, captions\n'
          'with their images, the last page not a stub.')


def screenshot_previews(doc, pages, prev):
    """Without poppler: Chrome screenshots of each sheet. Same engine, but the
    screen render, not the PDF, and the handover must say so."""
    for k, p in enumerate(pages):
        one = [head(doc['title'], '.sheet{margin:0!important;box-shadow:none!important}html{background:#fff}')]
        one.append(sheet(doc, [u['html'] for u in p], k == 0, k == len(pages) - 1))
        one.append('</body></html>')
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='dan-shot-')) / 'p.html'
        tmp.write_text('\n'.join(one), encoding='utf-8')
        chrome('--hide-scrollbars', '--window-size=794,1123',
               '--screenshot=%s' % (prev / ('page-%02d.png' % (k + 1))),
               '--virtual-time-budget=8000', file_url(tmp))
    return 'Chrome screenshots of each sheet, not the PDF: install poppler for real PDF renders'


if __name__ == '__main__':
    main()
