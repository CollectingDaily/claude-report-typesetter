"""Read a LibreOffice document (.odt) straight from its XML, on any system.

    md, images, candidates, notes = to_markdown(path, img_dir, first_index)
    text = plain_text(path)          # for textcheck.py: the words, nothing else

It used to go through macOS's textutil, which kept every word but dropped the
headings, the lists and the links, and does not exist on Windows. An .odt is a
zip of XML, so this reads it directly and keeps them:

    Title                  -> # line (ingest lifts it into the frontmatter)
    Heading N              -> #...# line, one more # per level
    bold / italic          -> **x** / *x*, from character styles and direct formatting
    links                  -> [text](url)
    bulleted and numbered  -> - item / 1. item, nested by indent
    tables                 -> markdown tables; a table used to lay out a page is read as text
    footnotes              -> [^n] and [^n]: note, at the end
    embedded images        -> extracted, and listed in a comment for the agent to place
    comments, tracked deletions, tables of contents  -> left out, as a reader never sees them

plain_text() walks the same XML independently, so the text check does not trust
the conversion it is checking.
"""
import pathlib
import re
import xml.etree.ElementTree as ET
import zipfile

NS = {
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    'style': 'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
    'fo': 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0',
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
    'xlink': 'http://www.w3.org/1999/xlink',
}


def q(prefix, name):
    return '{%s}%s' % (NS[prefix], name)


# elements whose content a reader never sees
SKIP = {q('office', 'annotation'), q('office', 'annotation-end'), q('text', 'tracked-changes'),
        q('text', 'table-of-content'), q('text', 'alphabetical-index'), q('text', 'illustration-index'),
        q('text', 'table-index'), q('text', 'object-index'), q('text', 'user-index'),
        q('text', 'bibliography'), q('text', 'sequence-decls'), q('text', 'variable-decls'),
        q('text', 'user-field-decls'), q('office', 'forms'), q('text', 'note-citation'),
        q('text', 'soft-page-break')}
TOC = {q('text', 'table-of-content'), q('text', 'alphabetical-index'), q('text', 'illustration-index'),
       q('text', 'table-index'), q('text', 'object-index'), q('text', 'user-index'), q('text', 'bibliography')}


class Styles:
    """Bold, italic and list type, resolved through each style's parents."""

    def __init__(self, z):
        self.s, self.lists = {}, {}
        for part in ('styles.xml', 'content.xml'):          # content wins for the body
            if part not in z.namelist():
                continue
            root = ET.fromstring(z.read(part))
            for s in root.iter(q('style', 'style')):
                tp = s.find(q('style', 'text-properties'))
                bold = italic = None
                if tp is not None:
                    w = tp.get(q('fo', 'font-weight'))
                    if w:
                        bold = w in ('bold', '600', '700', '800', '900')
                    st = tp.get(q('fo', 'font-style'))
                    if st:
                        italic = st in ('italic', 'oblique')
                self.s[(s.get(q('style', 'family')), s.get(q('style', 'name')))] = dict(
                    parent=s.get(q('style', 'parent-style-name')), bold=bold, italic=italic,
                    lst=s.get(q('style', 'list-style-name')))
            for ls in root.iter(q('text', 'list-style')):
                levels = {}
                for el in ls:
                    lvl = int(el.get(q('text', 'level'), '1'))
                    numbered = el.tag == q('text', 'list-level-style-number') and bool(el.get(q('style', 'num-format')))
                    levels[lvl] = 'number' if numbered else 'bullet'
                self.lists[ls.get(q('style', 'name'))] = levels

    def get(self, family, name, key):
        seen = set()
        while name and (family, name) not in seen:
            seen.add((family, name))
            st = self.s.get((family, name))
            if st is None:
                return None
            if st[key] is not None:
                return st[key]
            name = st['parent']
        return None

    def is_para(self, name, target):
        seen = set()
        while name and name not in seen:
            if name == target:
                return True
            seen.add(name)
            name = (self.s.get(('paragraph', name)) or {}).get('parent')
        return False


def _ws(el):
    return ' ' * int(el.get(q('text', 'c'), '1'))


# ------------------------------------------------------------------ markdown

class Reader:
    def __init__(self, z, img_dir, first_index):
        self.z, self.img_dir, self.next_img = z, img_dir, first_index
        self.st = Styles(z)
        self.lines, self.images, self.candidates, self.notes, self.skipped = [], [], [], [], []

    # inline content -> [(text, bold, italic, link)]
    def segs(self, el, bold, italic, link, out, frames):
        if el.text:
            out.append([el.text, bold, italic, link])
        for c in el:
            t = c.tag
            if t in SKIP:
                pass
            elif t == q('text', 'span'):
                name = c.get(q('text', 'style-name'))
                b = self.st.get('text', name, 'bold')
                i = self.st.get('text', name, 'italic')
                self.segs(c, bold if b is None else b, italic if i is None else i, link, out, frames)
            elif t == q('text', 'a'):
                self.segs(c, bold, italic, c.get(q('xlink', 'href')) or link, out, frames)
            elif t == q('text', 's'):
                out.append([_ws(c), bold, italic, link])
            elif t == q('text', 'tab'):
                out.append([' ', bold, italic, link])
            elif t == q('text', 'line-break'):
                out.append(['\n', False, False, None])
            elif t == q('text', 'note'):
                body = c.find(q('text', 'note-body'))
                n = len(self.notes) + 1
                parts = [self.inline(p)[0] for p in (body if body is not None else [])]
                text = ' '.join(x for x in parts if x)
                self.notes.append((n, text))
                out.append(['[^%d]' % n, False, False, None])
            elif t == q('draw', 'frame'):
                frames.append(c)
            else:                                  # fields, bookmarks, sequences: their text only
                self.segs(c, bold, italic, link, out, frames)
            if c.tail:
                out.append([c.tail, bold, italic, link])
        return out

    def inline(self, p):
        name = p.get(q('text', 'style-name'))
        bold = bool(self.st.get('paragraph', name, 'bold'))
        italic = bool(self.st.get('paragraph', name, 'italic'))
        frames = []
        segs = self.segs(p, bold, italic, None, [], frames)
        return md_inline(segs), segs, frames

    def frame(self, f):
        img = f.find(q('draw', 'image'))
        if img is not None:
            href = img.get(q('xlink', 'href')) or ''
            if href in self.z.namelist():
                out = self.img_dir / ('%02d-odt-%s' % (self.next_img, pathlib.Path(href).name))
                out.write_bytes(self.z.read(href))
                self.images.append(out)
                self.next_img += 1
                self.lines += ['', '<!-- embedded in the document: ![](%s) -->' % out.name, '']
        box = f.find(q('draw', 'text-box'))
        if box is not None:
            self.blocks(box)

    def para(self, p, heading_level=None, prefix=None):
        text, segs, frames = self.inline(p)
        name = p.get(q('text', 'style-name'))
        if text:
            flat = plain(text.replace('<br>', ' '))
            if heading_level:
                self.lines += ['#' * min(heading_level + 1, 6) + ' ' + flat, '']
            elif self.st.is_para(name, 'Title'):
                self.lines += ['# ' + flat, '']
            elif prefix is not None:
                self.lines.append(prefix + text)
            else:
                # a paragraph that happens to start like markdown ("+ 44 (0)...",
                # "- 5%", "#1 seller") would become a bullet or a heading
                if re.match(r'^(?:[-+*•]\s|\d+[.)]\s|#|>|\|)', text):
                    text = '\\' + text
                self.lines += [text, '']
                if all(s[1] for s in segs if s[0].strip()) and len(flat.split()) <= 12:
                    self.candidates.append(flat)
        for f in frames:
            self.frame(f)

    def list(self, el, depth, style):
        style = el.get(q('text', 'style-name')) or style
        for item in el:
            if item.tag not in (q('text', 'list-item'), q('text', 'list-header')):
                continue
            first = True
            for c in item:
                if c.tag == q('text', 'list'):
                    self.list(c, depth + 1, style)
                elif c.tag in (q('text', 'p'), q('text', 'h')):
                    pstyle = (self.st.s.get(('paragraph', c.get(q('text', 'style-name')))) or {}).get('lst')
                    kind = self.st.lists.get(style or pstyle or '', {}).get(depth + 1, 'bullet')
                    mark = ('1. ' if kind == 'number' else '- ') if first and item.tag == q('text', 'list-item') else '  '
                    self.para(c, prefix='  ' * depth + mark)
                    first = False
        if depth == 0:
            self.lines.append('')

    def table(self, t):
        rows = [r for r in t.iter(q('table', 'table-row'))]
        grid, layout = [], False
        for r in rows:
            cells = []
            for c in r:
                if c.tag == q('table', 'table-cell'):
                    parts = [x for x in (self.inline(p)[0] for p in c.iter()
                                         if p.tag in (q('text', 'p'), q('text', 'h'))) if x]
                    # a cell holding several paragraphs or a long passage is page layout, not data
                    if len(parts) > 3 or len(' '.join(parts).split()) > 60:
                        layout = True
                    cells.append(' '.join(parts).replace('|', '/'))
            grid.append(cells)
        if not grid:
            return
        width = max(len(r) for r in grid)
        layout = layout or len(grid) <= 1 or width <= 1
        if layout:                                   # a table used to lay out a page
            for r in rows:
                for c in r:
                    if c.tag == q('table', 'table-cell'):
                        self.blocks(c)
            return
        grid = [r + [''] * (width - len(r)) for r in grid]
        self.lines += ['', '| ' + ' | '.join(grid[0]) + ' |', '|' + '---|' * width]
        self.lines += ['| ' + ' | '.join(r) + ' |' for r in grid[1:]]
        self.lines.append('')

    def blocks(self, el):
        for c in el:
            t = c.tag
            if t in TOC:
                self.skipped.append('a generated table of contents or index')
            elif t in SKIP:
                continue
            elif t == q('text', 'h'):
                self.para(c, heading_level=int(c.get(q('text', 'outline-level'), '1')))
            elif t == q('text', 'p'):
                self.para(c)
            elif t == q('text', 'list'):
                self.list(c, 0, None)
            elif t == q('table', 'table'):
                self.table(c)
            elif t in (q('text', 'section'), q('text', 'index-body')):
                self.blocks(c)


def md_inline(segs):
    """[(text, bold, italic, link)] -> markdown, with runs of one format merged."""
    merged = []
    for s in segs:
        if merged and merged[-1][1:] == s[1:] and '\n' not in s[0] and '\n' not in merged[-1][0]:
            merged[-1][0] += s[0]
        else:
            merged.append(list(s))
    out = []
    for text, b, i, link in merged:
        if text == '\n':
            out.append('<br>')
            continue
        lead = text[:len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        core = text.strip()
        if core:
            if i:
                core = '*%s*' % core
            if b:
                core = '**%s**' % core
            if link:
                core = '[%s](%s)' % (core, link)
        out.append(lead + core + trail)
    s = ''.join(out)
    s = re.sub(r'(<br>\s*)+$', '', s.strip())
    return s.strip()


def plain(s):
    s = re.sub(r'^#+\s*', '', s.strip()).replace('****', '')
    s = re.sub(r'\*\*|__', '', s)
    s = re.sub(r'(?<![\w])[*_](?=\S)|(?<=\S)[*_](?![\w])', '', s)
    return ' '.join(s.split())


def body(z):
    root = ET.fromstring(z.read('content.xml'))
    b = root.find(q('office', 'body'))
    return b.find(q('office', 'text')) if b is not None else None


def to_markdown(path, img_dir, first_index=1):
    z = zipfile.ZipFile(path)
    r = Reader(z, pathlib.Path(img_dir), first_index)
    text = body(z)
    if text is not None:
        r.blocks(text)
    if r.notes:
        r.lines.append('')
        r.lines += ['[^%d]: %s' % (n, t) for n, t in r.notes]
    md = re.sub(r'\n{3,}', '\n\n', '\n'.join(r.lines)).strip() + '\n'
    return md, r.images, r.candidates, sorted(set(r.skipped))


# ------------------------------------------------------------------ plain text for the check

def plain_text(path):
    """Every word a reader sees, in reading order, footnotes last. Written apart
    from the markdown reader on purpose: the check must not share its bugs."""
    z = zipfile.ZipFile(path)
    out, notes = [], []

    def inline(el, sink, frames):
        if el.text:
            sink.append(el.text)
        for c in el:
            if c.tag in SKIP:
                pass
            elif c.tag == q('text', 'note'):
                b = c.find(q('text', 'note-body'))
                buf = []
                for p in (b.iter() if b is not None else []):
                    if p.tag in (q('text', 'p'), q('text', 'h')):
                        inline(p, buf, [])
                        buf.append(' ')
                notes.append(''.join(buf))
            elif c.tag == q('draw', 'frame'):
                frames.append(c)                 # a caption box is read after its paragraph
            elif c.tag == q('text', 's'):
                sink.append(_ws(c))
            elif c.tag in (q('text', 'tab'), q('text', 'line-break')):
                sink.append(' ')
            else:
                inline(c, sink, frames)
            if c.tail:
                sink.append(c.tail)

    def walk(el):
        for c in el:
            if c.tag in SKIP or c.tag in TOC:
                continue
            if c.tag in (q('text', 'p'), q('text', 'h')):
                buf, frames = [], []
                inline(c, buf, frames)
                out.append(''.join(buf))
                for f in frames:
                    box = f.find(q('draw', 'text-box'))
                    if box is not None:
                        walk(box)
            else:
                walk(c)

    b = body(z)
    if b is not None:
        walk(b)
    return '\n'.join(out + notes)
