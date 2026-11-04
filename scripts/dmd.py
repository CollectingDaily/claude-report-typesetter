#!/usr/bin/env python3
"""Parse the working markdown of a Dan document into typeset blocks.

    from dmd import parse
    meta, blocks = parse(pathlib.Path('The 2027 report.md'))

The working markdown is Dan's article, word for word, with layout added and
nothing else: where each image goes, which lines are headings, where a page
must break. build.py turns the blocks into sheets. textcheck.py proves the
words that come out are the words that went in.

THE DIALECT (ordinary markdown, plus three layout marks)
-----------
    ---                     frontmatter: see SKILL.md for the fields
    # / ## / ###            headings. Ranked, not fixed: the highest level the
                            article uses becomes the section heading (h2), the
                            next the sub-heading (h3), the next h4. The title
                            itself lives in the frontmatter, never in the body.
    blank-line chunks       paragraphs. Lines holding only spaces count as blank,
                            which is how a Google Docs export writes them.
    - item / 1. item        lists. Blank lines between items are allowed.
    > quote                 the cream pull-out band
    | a | b |               tables; ---: right-aligns a column of figures
    **bold** *italic* _italic_ [text](url) [^1]
    [^1]: note text         footnotes, collected at the end of the document
    ![caption](path "credit"){w=150}
                            an image on a line of its own. Caption and credit
                            are optional and come from Dan, never from us.
                            {w=mm} or {h=mm} overrides the default size.
    >> exact words       a pull quote: the article's own words repeated in a band.
                            The build refuses it unless they are word for word
                            in the source.
    ::: cards ... :::       each bold lead-in paragraph and what follows becomes a
                            card, two to a row (a list of sales)
    ::: panels ... :::      each heading and what follows becomes a panel; a
                            number the heading starts with is set large
    ::: box ... :::         a cream box around what it holds
    ::: contact ... :::     the navy panel, for the article's own contact passage
    ::: beside ... :::      an image and its paragraphs side by side
    ::: keyfigures ... :::  "- figure | label" lines, set in the page-one sidebar;
                            both parts must be word for word from the article
    \\+ 44 (0)...           a backslash makes the next character literal, so a
                            line can start with + - * # > | or "1." as text
    <!-- pagebreak -->      the next block starts a new page
    <!-- anything else -->  ignored

A paragraph that is bold from end to end (the lot headlines in a list of
sales) and a paragraph ending in a colon before a list or table are kept on
the same page as the block that follows them. So is every heading.
"""
import html
import pathlib
import re
import shutil
import struct
import subprocess

# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------

def parse_frontmatter(text):
    """A small YAML subset: `Key: value` and `Key:` followed by `  - item` lines.
    Returns (dict, body). Keys are kept as written."""
    if not text.startswith('---\n'):
        return {}, text
    end = text.find('\n---', 4)
    if end < 0:
        return {}, text
    block, body = text[4:end], text[end + 4:]
    body = body[1:] if body.startswith('\n') else body
    meta, key = {}, None
    for line in block.split('\n'):
        if not line.strip():
            continue
        m = re.match(r'^\s+-\s*(.*)$', line)
        if m and key:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(unquote(m.group(1)))
            continue
        m = re.match(r'^([^:#][^:]*):\s*(.*)$', line)
        if m:
            key = m.group(1).strip()
            meta[key] = unquote(m.group(2)) if m.group(2).strip() else ''
    return meta, body


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        v = v[1:-1]
    return v


def truthy(v, default=True):
    if v is None or v == '':
        return default
    return str(v).strip().lower() not in ('false', 'no', 'off', '0', 'none')


# --------------------------------------------------------------------------
# inline markup
# --------------------------------------------------------------------------

def inline(s, notes=None):
    """Markdown inline to HTML. Escapes first, so the article's own & and <
    can never become markup."""
    # Google Docs exports close one bold run and open the next with nothing
    # between them: **coin****, sold**. Four stars there mean "no break".
    s = s.replace('****', '')
    # backslash escapes: \+ \* \# and friends are the character itself
    escaped = []

    def keep_escape(m):
        escaped.append(m.group(1))
        return '\x02%d\x02' % (len(escaped) - 1)
    s = re.sub(r'\\([\\`*_{}\[\]()#+\-.!|>~])', keep_escape, s)
    s = html.escape(s, quote=False)
    s = re.sub(r'&lt;br\s*/?&gt;', '<br>', s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)

    def emphasis(t):
        t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
        t = re.sub(r'(?<![\w])__(.+?)__(?![\w])', r'<strong>\1</strong>', t)
        t = re.sub(r'(?<![*\w])\*(?![\s*])(.+?)(?<![\s*])\*(?![*\w])', r'<em>\1</em>', t)
        t = re.sub(r'(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])', r'<em>\1</em>', t)
        return t
    # links before emphasis, so an underscore in a URL is left alone; the link
    # text gets its own emphasis, because Word bolds links as often as not
    links = []

    def keep_link(m):
        links.append('<a href="%s">%s</a>' % (html.escape(m.group(2), quote=True), emphasis(m.group(1))))
        return '\x00%d\x00' % (len(links) - 1)
    s = re.sub(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)', keep_link, s)
    s = emphasis(s)

    def fnref(m):
        if notes is None:
            return m.group(0)
        n = notes.ref(m.group(1))
        return '<sup class="fnref">%d</sup>' % n
    s = re.sub(r'\[\^([^\]]+)\]', fnref, s)
    s = re.sub(r'\x00(\d+)\x00', lambda m: links[int(m.group(1))], s)
    s = re.sub(r'\x02(\d+)\x02', lambda m: html.escape(escaped[int(m.group(1))], quote=False), s)
    return s


def only_emphasis(raw):
    """True when a paragraph is bold from end to end: a lot headline, a lead-in."""
    s = raw.replace('****', '')
    if '**' not in s and '__' not in s:
        return False
    rest = re.sub(r'\*\*(.+?)\*\*|__(.+?)__', '', s)
    rest = re.sub(r'(?<![\w])_(.+?)_(?![\w])|\*(.+?)\*', '', rest)
    return not re.sub(r'[\s.,;:!?\-–—]', '', rest)


class Notes:
    def __init__(self):
        self.defs, self.order = {}, []

    def ref(self, key):
        if key not in self.order:
            self.order.append(key)
        return self.order.index(key) + 1


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

def image_size(path):
    """(width, height) in pixels, read from the file header. sips as a fallback."""
    data = pathlib.Path(path).read_bytes()[:65536]
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return struct.unpack('>II', data[16:24])
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack('>HH', data[i + 5:i + 9])
                return w, h
            seg = struct.unpack('>H', data[i + 2:i + 4])[0]
            i += 2 + seg
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return struct.unpack('<HH', data[6:10])
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        kind = data[12:16]
        if kind == b'VP8X':
            return (int.from_bytes(data[24:27], 'little') + 1, int.from_bytes(data[27:30], 'little') + 1)
        if kind == b'VP8 ':
            w, h = struct.unpack('<HH', data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if kind == b'VP8L':
            b = int.from_bytes(data[21:25], 'little')
            return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    # last resort, macOS only
    if not shutil.which('sips'):
        raise ValueError('cannot read the size of %s: use PNG, JPEG, GIF or WebP' % path)
    out = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(path)],
                         capture_output=True, text=True).stdout
    w = re.search(r'pixelWidth:\s*(\d+)', out)
    h = re.search(r'pixelHeight:\s*(\d+)', out)
    if w and h:
        return int(w.group(1)), int(h.group(1))
    raise ValueError('cannot read the size of %s' % path)


COLUMN_MM = 188.0     # 210mm sheet less 11mm padding each side
MAX_H_MM = 120.0      # default ceiling, so no image swallows a page
MIN_DPI = 110.0       # below this a supplied image is not enlarged further


def image_box(px_w, px_h, opts):
    """Display size in mm. Never wider than the column, never stretched out of
    proportion, and by default never enlarged past MIN_DPI."""
    ratio = px_h / px_w
    if 'w' in opts:
        w = min(float(opts['w']), COLUMN_MM)
    elif 'h' in opts:
        w = min(float(opts['h']) / ratio, COLUMN_MM)
    else:
        w = min(COLUMN_MM, px_w / MIN_DPI * 25.4, MAX_H_MM / ratio)
    return round(w, 1), round(w * ratio, 1)


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------

class Block:
    def __init__(self, kind, html_, glue=False, **kw):
        self.kind = kind          # h2 h3 h4 p ul ol table quote figure notes contact
        self.html = html_
        self.glue = glue          # keep on the same page as the next block
        self.break_before = False
        self.extra = kw           # table/list pieces for splitting, image data

    def __repr__(self):
        return '<%s%s %r>' % (self.kind, ' +' if self.glue else '', re.sub('<[^>]+>', '', self.html)[:40])


HEADING = re.compile(r'^(#{1,6})\s*(.*?)\s*#*\s*$')
IMAGE = re.compile(r'^!\[(.*?)\]\((\S+?|<[^>]+>)(?:\s+"(.*?)")?\)\s*(\{[^}]*\})?\s*$')
ITEM = re.compile(r'^(\s*)([-*+•]|\d+[.)])\s+(.*)$')
FNDEF = re.compile(r'^\[\^([^\]]+)\]:\s*(.*)$')
HR = re.compile(r'^\s*([-*_])(\s*\1){2,}\s*$')
ALIGN = re.compile(r'^\s*:?-{2,}:?\s*$')


def is_blank(line):
    return not line.strip()


def table_rows(lines):
    return [[c.strip() for c in ln.strip().strip('|').split('|')] for ln in lines]


def build_table(lines, notes):
    rows = table_rows(lines)
    num = [c.strip().endswith(':') and not c.strip().startswith(':') for c in rows[1]]
    head = '<thead><tr>%s</tr></thead>' % ''.join(
        '<th%s>%s</th>' % (' class="num"' if n else '', inline(c, notes)) for c, n in zip(rows[0], num + [False] * len(rows[0])))
    body = []
    for r in rows[2:]:
        body.append('<tr>%s</tr>' % ''.join(
            '<td%s>%s</td>' % (' class="num"' if n else '', inline(c, notes))
            for c, n in zip(r, num + [False] * len(r))))
    return head, body


def table_html(head, body):
    return '<table>\n  %s\n  <tbody>\n    %s\n  </tbody>\n</table>' % (head, '\n    '.join(body))


def build_list(items, notes):
    """items: [(indent, ordered, text)]. Returns (html, [top-level li html], ordered)."""
    def render(i, indent):
        ordered = items[i][1]
        lis = []
        while i < len(items) and items[i][0] >= indent:
            if items[i][0] > indent:
                sub, i = render(i, items[i][0])
                lis[-1] = lis[-1][:-5] + sub + '</li>'
                continue
            lis.append('<li>%s</li>' % inline(items[i][2], notes))
            i += 1
        tag = 'ol' if ordered else 'ul'
        return '<%s>%s</%s>' % (tag, ''.join(lis), tag), i, lis
    out, _, lis = render(0, items[0][0]) if items else ('', 0, [])
    return out, lis, bool(items and items[0][1])


FENCE = re.compile(r'^:::\s*([a-z]+)\s*(.*)$')
CONTAINERS = {'cards', 'panels', 'box', 'contact', 'beside', 'keyfigures'}
# a sum of money inside a card's headline, set larger: the words and their order
# do not change, only the size of the figure
MONEY = re.compile(r'((?:US)?[$£€]\s?\d[\d,.]*(?:\s?(?:million|billion|bn|m|k)\b)?)')


def money(h):
    parts = re.split(r'(<[^>]+>)', h)
    return ''.join(x if x.startswith('<') else MONEY.sub(r'<span class="fig">\1</span>', x) for x in parts)


def compose(b, fig):
    """HTML for a container block. fig(block, beside) builds a figure; it is
    passed in because images are sized and embedded by build.py."""
    k = b.kind

    def inner(blocks, beside=False):
        return '\n'.join(fig(x, beside) if x.kind == 'figure' else
                         (compose(x, fig) if x.extra.get('container') else x.html) for x in blocks)

    if k == 'cards':
        cards = []
        for g in b.extra['children']:
            parts = []
            for n, x in enumerate(g):
                if x.kind == 'figure':
                    parts.append(fig(x, True))
                elif n == 0 and x.kind == 'p':
                    parts.append(money(x.html.replace('<p>', '<p class="card-head">', 1)))
                else:
                    parts.append(x.html)
            cards.append('<div class="card">%s</div>' % '\n'.join(parts))
        return '<div class="cards">%s</div>' % '\n'.join(cards)
    if k == 'panels':
        panels = []
        for g in b.extra['children']:
            head, rest = g[0], g[1:]
            m = re.match(r'^<h\d>(\d+)([.)]?)\s+(.*)</h\d>$', head.html, re.S)
            if m:
                num, title = m.group(1) + m.group(2), m.group(3)
            else:
                num, title = '', re.sub(r'^<h\d>|</h\d>$', '', head.html)
            panels.append('<div class="panel">%s<div class="pbody"><h4 class="phead">%s</h4>%s</div></div>'
                          % ('<div class="num">%s</div>' % num if num else '', title, inner(rest)))
        return '<div class="panels">%s</div>' % '\n'.join(panels)
    if k == 'box':
        return '<div class="box">%s</div>' % inner(b.extra['children'])
    if k == 'contactpanel':
        return '<div class="contactpanel">%s</div>' % inner(b.extra['children'])
    if k == 'beside':
        cells = []
        for x in b.extra['children']:
            if x.kind == 'figure':
                cells.append('<div class="bimg">%s</div>' % fig(x, True))
            elif cells and cells[-1].startswith('<div class="btext">'):
                cells[-1] = cells[-1][:-6] + '\n' + x.html + '</div>'
            else:
                cells.append('<div class="btext">%s</div>' % x.html)
        return '<div class="beside">%s</div>' % ''.join(cells)
    return b.html


def parse(md_path):
    md_path = pathlib.Path(md_path)
    meta, body = parse_frontmatter(md_path.read_text(encoding='utf-8'))
    body = re.sub(r'<!--\s*pagebreak\s*-->', '\n\n\x01PAGEBREAK\x01\n\n', body, flags=re.I)
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    lines = body.split('\n')

    notes = Notes()
    # footnote definitions first, so references can be numbered in order of use
    kept = []
    i = 0
    while i < len(lines):
        m = FNDEF.match(lines[i])
        if m:
            text = [m.group(2)]
            i += 1
            while i < len(lines) and lines[i].startswith(('    ', '\t')) and lines[i].strip():
                text.append(lines[i].strip())
                i += 1
            notes.defs[m.group(1)] = ' '.join(text)
            continue
        kept.append(lines[i])
        i += 1
    lines = kept

    levels = sorted({len(HEADING.match(l).group(1)) for l in lines
                     if HEADING.match(l) and HEADING.match(l).group(2).strip()})
    rank = {lv: min(2 + n, 4) for n, lv in enumerate(levels)}

    def container(name, inner, arg):
        if name == 'keyfigures':
            items = []
            for l in inner:
                m = re.match(r'^\s*[-*]\s+(.*?)\s*\|\s*(.*?)\s*$', l)
                if m:
                    items.append((m.group(1), m.group(2)))
                elif l.strip():
                    raise ValueError('a key figure is "- figure | label": %r' % l)
            html_ = ('<div class="lbl" data-skip>Key figures</div>'
                     + ''.join('<div class="kc"><div class="v" data-repeat>%s</div><div class="d" data-repeat>%s</div></div>'
                               % (inline(v), inline(d)) for v, d in items))
            return [Block('keyfigures', html_, items=items)]
        children = parse_lines(inner)
        if name in ('cards', 'panels'):
            groups = []
            for b in children:
                start = (b.kind in ('h2', 'h3', 'h4') or (name == 'cards' and b.kind == 'p' and b.glue))
                if start or not groups:
                    groups.append([b])
                else:
                    groups[-1].append(b)
            return [Block(name, '', children=groups[k:k + 2], container=name)
                    for k in range(0, len(groups), 2)]
        kind = 'contactpanel' if name == 'contact' else name
        return [Block(kind, '', children=children, container=kind, arg=arg)]

    def parse_lines(lines):
        blocks, i, pending_break = [], 0, False

        def add(b):
            nonlocal pending_break
            b.break_before = pending_break
            pending_break = False
            blocks.append(b)

        while i < len(lines):
            line = lines[i]
            if is_blank(line) or HR.match(line):
                i += 1
                continue
            if line.strip() == '\x01PAGEBREAK\x01':
                pending_break = True
                i += 1
                continue
            m = FENCE.match(line.strip())
            if m:
                name = m.group(1)
                if name not in CONTAINERS:
                    raise ValueError('unknown box "::: %s"; use one of %s' % (name, ', '.join(sorted(CONTAINERS))))
                j = i + 1
                while j < len(lines) and lines[j].strip() != ':::':
                    j += 1
                if j >= len(lines):
                    raise ValueError('"::: %s" has no closing ":::"' % name)
                for b in container(name, lines[i + 1:j], m.group(2)):
                    add(b)
                i = j + 1
                continue
            if line.lstrip().startswith('>>'):
                # a pull quote: the article's own words, repeated. textcheck.py
                # refuses the build unless they appear word for word in the source.
                parts = []
                while i < len(lines) and lines[i].lstrip().startswith('>>'):
                    parts.append(re.sub(r'^\s*>>\s?', '', lines[i]).strip())
                    i += 1
                raw = ' '.join(x for x in parts if x)
                add(Block('quote', '<div class="pullquote" data-repeat>%s</div>' % inline(raw), repeat=raw))
                continue
            m = HEADING.match(line)
            if m:
                text = m.group(2).strip()
                i += 1
                if text:
                    h = 'h%d' % rank[len(m.group(1))]
                    add(Block(h, '<%s>%s</%s>' % (h, inline(text, notes), h), glue=True))
                continue
            m = IMAGE.match(line.strip())
            if m:
                cap, src, credit, opt = m.groups()
                src = src.strip('<>')
                opts = dict(re.findall(r'(\w+)\s*=\s*([\d.]+)', opt or ''))
                path = (md_path.parent / src).resolve()
                add(Block('figure', '', src=src, path=path, caption=cap.strip(),
                          credit=(credit or '').strip(), opts=opts))
                i += 1
                continue
            if line.lstrip().startswith('|') and i + 1 < len(lines) and all(
                    ALIGN.match(c) for c in table_rows([lines[i + 1]])[0]):
                j = i
                while j < len(lines) and lines[j].lstrip().startswith('|'):
                    j += 1
                head, body_rows = build_table(lines[i:j], notes)
                add(Block('table', table_html(head, body_rows), head=head, rows=body_rows))
                i = j
                continue
            if line.lstrip().startswith('>'):
                paras, cur = [], []
                while i < len(lines) and lines[i].lstrip().startswith('>') and not lines[i].lstrip().startswith('>>'):
                    t = re.sub(r'^\s*>\s?', '', lines[i])
                    if t.strip():
                        cur.append(t.strip())
                    elif cur:
                        paras.append(cur)
                        cur = []
                    i += 1
                if cur:
                    paras.append(cur)
                inner = ''.join('<p>%s</p>' % inline(' '.join(p), notes) for p in paras)
                add(Block('quote', '<div class="pullout">%s</div>' % inner))
                continue
            if ITEM.match(line):
                items = []
                while i < len(lines):
                    m = ITEM.match(lines[i])
                    if m:
                        items.append([len(m.group(1).expandtabs(4)), m.group(2)[0].isdigit(), m.group(3).strip()])
                        i += 1
                        continue
                    if is_blank(lines[i]):
                        # a blank line ends the list unless another item follows it
                        j = i
                        while j < len(lines) and is_blank(lines[j]):
                            j += 1
                        if j < len(lines) and ITEM.match(lines[j]):
                            i = j
                            continue
                        break
                    if lines[i].startswith(('  ', '\t')) and items:
                        items[-1][2] += ' ' + lines[i].strip()      # continuation
                        i += 1
                        continue
                    break
                out, lis, ordered = build_list(items, notes)
                add(Block('ol' if ordered else 'ul', out, items=lis, ordered=ordered))
                continue
            # paragraph
            para = []
            while i < len(lines) and not is_blank(lines[i]) and not (
                    HEADING.match(lines[i]) or IMAGE.match(lines[i].strip()) or ITEM.match(lines[i])
                    or lines[i].lstrip().startswith(('>', '|', ':::')) or lines[i].strip() == '\x01PAGEBREAK\x01'):
                para.append(lines[i])
                i += 1
            if not para:          # a line nothing else claimed; never drop text silently
                para, i = [lines[i]], i + 1
            raw = ' '.join(l.strip() for l in para)
            # two trailing spaces or a backslash is a hard line break in markdown
            parts = []
            for l in para:
                parts.append(inline(l.strip().rstrip('\\'), notes))
                if l.endswith('  ') or l.rstrip().endswith('\\'):
                    parts.append('<br>')
                else:
                    parts.append(' ')
            text = ''.join(parts).strip()
            text = re.sub(r'(<br>\s*)+$', '', text)
            lead = only_emphasis(raw) and len(raw.split()) <= 60
            add(Block('p', '<p>%s</p>' % text, glue=lead, raw=raw))

        # a paragraph ending in a colon stays with the list or table it introduces
        for a, b in zip(blocks, blocks[1:]):
            if a.kind == 'p' and a.extra.get('raw', '').rstrip().endswith(':') and b.kind in ('ul', 'ol', 'table'):
                a.glue = True
        return blocks

    blocks = parse_lines(lines)
    if notes.order:
        lis = ''.join('<li>%s</li>' % inline(notes.defs.get(k, ''), None) for k in notes.order)
        blocks.append(Block('notes', '<div class="notes"><ol>%s</ol></div>' % lis))
    missing = [k for k in notes.order if k not in notes.defs]
    meta['_missing_notes'] = missing
    meta['_unused_notes'] = [k for k in notes.defs if k not in notes.order]
    return meta, blocks


def walk(blocks):
    """Every block, containers opened, in reading order."""
    for b in blocks:
        yield b
        ch = b.extra.get('children')
        if ch:
            flat = [x for g in ch for x in g] if b.kind in ('cards', 'panels') else ch
            yield from walk(flat)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        sys.exit('usage: dmd.py <working.md>   # lists the blocks it parses')
    meta, blocks = parse(sys.argv[1])
    for k, v in meta.items():
        if not k.startswith('_'):
            print('%-14s %s' % (k, v))
    print()
    for b in blocks:
        print(repr(b))
