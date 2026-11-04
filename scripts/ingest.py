#!/usr/bin/env python3
"""Set up a report: copy the article and images in, write the working markdown.

    python ingest.py "<article>" "<image>" "<image>" ... [--root=DIR] [--title="..."] [--replace]

(python3 on a Mac, python on Windows.) Runs on both with nothing but Python.

The article can be LibreOffice (.odt), Word (.docx), markdown (.md) or plain
text (.txt); all four are read directly. Older formats (.doc, .rtf, .html) are
converted with LibreOffice when it is installed, or with macOS's textutil on a
Mac. Pages and PDF files are refused: ask for the article as .odt or .docx.

What it does, and nothing else:
  1. copies the article, untouched, to <Workings>/source/. textcheck.py compares
     the finished document against this copy, so it must never be edited;
  2. copies each image to <Workings>/images/ as 01-<name>, 02-<name>... in the
     order given, plus any image embedded in the article. The originals are not
     touched. On a Mac, HEIC, TIFF and BMP become JPEG and anything wider than
     2400px is scaled down; elsewhere those formats are refused (save as PNG or
     JPG) and large images are used as they are;
  3. writes <root>/<Title>.md: frontmatter, then the article as markdown with
     the title line lifted into the frontmatter. Images are listed in a comment
     at the top, to be moved into place; they are not placed.

Where it goes: the folder the article is in, on every machine, so the PDF
lands beside the article. --root puts it somewhere else.

A working file that already exists is refused, because it carries the layout
decisions made on it. After the article itself has changed, run again with
--replace: the old working file, source copy and images are moved into
<Workings>/previous/<time>/, never deleted.
"""
import datetime
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dmd      # noqa: E402
import odt      # noqa: E402
import system   # noqa: E402

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
V = '{urn:schemas-microsoft-com:vml}'
PR = '{http://schemas.openxmlformats.org/package/2006/relationships}'

CONVERTIBLE = {'.doc', '.rtf', '.rtfd', '.html', '.htm', '.webarchive', '.wordml', '.fodt'}
CHROME_OK = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}
CONVERT = {'.heic', '.heif', '.tif', '.tiff', '.bmp'}
MAX_W = 2400


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:60] or 'document'


def safe_name(s):
    # Windows also refuses a name ending in a dot or a space
    return re.sub(r'[\\/:*?"<>|#^\[\]]+', '', s).strip()[:120].rstrip('. ') or 'Document'


def plain(s):
    """A line of markdown as the words it shows."""
    s = re.sub(r'^#+\s*', '', s.strip())
    s = s.replace('****', '')
    s = re.sub(r'\*\*|__', '', s)
    s = re.sub(r'(?<![\w])[*_](?=\S)|(?<=\S)[*_](?![\w])', '', s)
    return ' '.join(s.split())


# ------------------------------------------------------------------ Word

def is_on(el):
    if el is None:
        return False
    v = el.get(W + 'val')
    return v is None or v.lower() not in ('0', 'false', 'off', 'none')


def docx_to_md(path, img_dir, first_index):
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    doc = ET.fromstring(z.read('word/document.xml'))

    rels = {}
    if 'word/_rels/document.xml.rels' in names:
        for r in ET.fromstring(z.read('word/_rels/document.xml.rels')).iter(PR + 'Relationship'):
            rels[r.get('Id')] = r.get('Target')

    styles = {}
    if 'word/styles.xml' in names:
        for s in ET.fromstring(z.read('word/styles.xml')).iter(W + 'style'):
            n = s.find(W + 'name')
            styles[s.get(W + 'styleId')] = (n.get(W + 'val') if n is not None else '').lower()

    fmt = {}                          # (numId, ilvl) -> numFmt
    if 'word/numbering.xml' in names:
        num = ET.fromstring(z.read('word/numbering.xml'))
        abstract = {}
        for an in num.iter(W + 'abstractNum'):
            lv = {}
            for l in an.iter(W + 'lvl'):
                f = l.find(W + 'numFmt')
                lv[l.get(W + 'ilvl')] = f.get(W + 'val') if f is not None else 'bullet'
            abstract[an.get(W + 'abstractNumId')] = lv
        for n in num.iter(W + 'num'):
            a = n.find(W + 'abstractNumId')
            if a is not None:
                for ilvl, f in abstract.get(a.get(W + 'val'), {}).items():
                    fmt[(n.get(W + 'numId'), ilvl)] = f

    images, candidates = [], []

    def extract(rid):
        target = rels.get(rid)
        if not target:
            return None
        member = 'word/' + target if not target.startswith('/') else target[1:]
        if member not in names:
            return None
        n = first_index + len(images)
        out = img_dir / ('%02d-word-%s' % (n, pathlib.Path(target).name))
        out.write_bytes(z.read(member))
        images.append(out)
        return out

    def runs(el, link=None):
        """[(text, bold, italic, link)] in document order, plus images found."""
        segs, pics = [], []
        for c in el:
            t = c.tag
            if t in (W + 'del', W + 'moveFrom', W + 'rPr', W + 'pPr'):
                continue
            if t == W + 'hyperlink':
                href = rels.get(c.get(R + 'id')) if c.get(R + 'id') else None
                s, p = runs(c, href or link)
                segs += s
                pics += p
                continue
            if t in (W + 'ins', W + 'smartTag', W + 'fldSimple', W + 'sdt', W + 'sdtContent', W + 'customXml'):
                s, p = runs(c, link)
                segs += s
                pics += p
                continue
            if t != W + 'r':
                continue
            rpr = c.find(W + 'rPr')
            b = is_on(rpr.find(W + 'b')) if rpr is not None else False
            i = is_on(rpr.find(W + 'i')) if rpr is not None else False
            for x in c:
                if x.tag == W + 't' and x.text:
                    segs.append([x.text, b, i, link])
                elif x.tag in (W + 'tab', W + 'br', W + 'cr'):
                    segs.append([' ', b, i, link])
                elif x.tag == W + 'footnoteReference':
                    segs.append(['[^%s]' % x.get(W + 'id'), False, False, None])
                elif x.tag in (W + 'drawing', W + 'pict'):
                    for blip in x.iter(A + 'blip'):
                        pics.append(blip.get(R + 'embed'))
                    for im in x.iter(V + 'imagedata'):
                        pics.append(im.get(R + 'id'))
        return segs, pics

    def md_inline(segs):
        merged = []
        for s in segs:
            if merged and merged[-1][1:] == s[1:]:
                merged[-1][0] += s[0]
            else:
                merged.append(list(s))
        out = []
        for text, b, i, link in merged:
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
        return ''.join(out).strip(), merged

    lines = []

    def para(p):
        ppr = p.find(W + 'pPr')
        style = ''
        list_prefix = None
        if ppr is not None:
            ps = ppr.find(W + 'pStyle')
            if ps is not None:
                style = styles.get(ps.get(W + 'val'), ps.get(W + 'val', '')).lower()
            np_ = ppr.find(W + 'numPr')
            if np_ is not None and np_.find(W + 'numId') is not None:
                nid = np_.find(W + 'numId').get(W + 'val')
                il = np_.find(W + 'ilvl').get(W + 'val') if np_.find(W + 'ilvl') is not None else '0'
                if nid != '0':
                    f = fmt.get((nid, il), 'bullet')
                    list_prefix = '  ' * int(il) + ('- ' if f in ('bullet', 'none') else '1. ')
        segs, pics = runs(p)
        text, merged = md_inline(segs)
        m = re.match(r'heading\s*(\d)', style)
        if text:
            if style == 'title':
                lines.append('# ' + plain(text))
            elif m:
                lines.append('#' * min(int(m.group(1)) + 1, 6) + ' ' + plain(text))
            elif list_prefix:
                lines.append(list_prefix + text)
            else:
                # A Word paragraph that happens to start like markdown ("+ 44 (0)...",
                # "- 5%", "#1 seller") would become a bullet or a heading. Escape it.
                if re.match(r'^(?:[-+*•]\s|\d+[.)]\s|#|>|\|)', text):
                    text = '\\' + text
                lines.append(text)
                if all(s[1] for s in merged if s[0].strip()) and len(plain(text).split()) <= 12:
                    candidates.append(plain(text))
        for rid in pics:
            out = extract(rid)
            if out:
                lines.append('')
                lines.append('<!-- embedded in the Word file: ![](%s) -->' % out.name)
        if not list_prefix:
            lines.append('')

    def table(t):
        rows = []
        for tr in t.iter(W + 'tr'):
            cells = []
            for tc in tr.iter(W + 'tc'):
                texts = [md_inline(runs(p)[0])[0] for p in tc.iter(W + 'p')]
                cells.append(' '.join(x for x in texts if x))
            rows.append(cells)
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [''] * (width - len(r)) for r in rows]
        lines.append('')
        lines.append('| ' + ' | '.join(rows[0]) + ' |')
        lines.append('|' + '---|' * width)
        for r in rows[1:]:
            lines.append('| ' + ' | '.join(r) + ' |')
        lines.append('')

    def layout_table(t):
        """Word documents are often laid out inside a table: a two-column page, a
        sidebar. A cell holding several paragraphs, or a single-row or
        single-column table, is layout, not data."""
        rows = [r for r in t if r.tag == W + 'tr']
        cells = [c for r in rows for c in r if c.tag == W + 'tc']
        if len(rows) <= 1 or all(len([c for c in r if c.tag == W + 'tc']) <= 1 for r in rows):
            return True
        for c in cells:
            ps = [p for p in c.iter(W + 'p') if ''.join(x.text or '' for x in p.iter(W + 't')).strip()]
            words = sum(len(''.join(x.text or '' for x in p.iter(W + 't')).split()) for p in ps)
            if len(ps) > 3 or words > 60:
                return True
        return False

    def walk(el):
        for c in el:
            if c.tag == W + 'p':
                para(c)
            elif c.tag == W + 'tbl':
                if layout_table(c):
                    for tr in (r for r in c if r.tag == W + 'tr'):
                        for tc in (x for x in tr if x.tag == W + 'tc'):
                            walk(tc)
                else:
                    table(c)
            elif c.tag in (W + 'sdt', W + 'sdtContent', W + 'customXml'):
                walk(c)

    walk(doc.find(W + 'body'))

    if 'word/footnotes.xml' in names:
        for fn in ET.fromstring(z.read('word/footnotes.xml')).iter(W + 'footnote'):
            if fn.get(W + 'type') in ('separator', 'continuationSeparator', 'continuationNotice'):
                continue
            text = ' '.join(md_inline(runs(p)[0])[0] for p in fn.iter(W + 'p')).strip()
            if text:
                lines.append('[^%s]: %s' % (fn.get(W + 'id'), text))
    md = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip() + '\n'
    return md, images, candidates


# ------------------------------------------------------------------ images

def take_image(src, dst_dir, n):
    src = pathlib.Path(src).expanduser()
    if not src.exists():
        sys.exit('image not found: %s' % src)
    ext = src.suffix.lower()
    stem = slug(src.stem)
    sips = system.tool('sips')                      # macOS only; an extra, not a need
    if ext in CHROME_OK:
        dst = dst_dir / ('%02d-%s%s' % (n, stem, '.jpg' if ext == '.jpeg' else ext))
        shutil.copy2(src, dst)
    elif ext in CONVERT and sips:
        dst = dst_dir / ('%02d-%s.jpg' % (n, stem))
        subprocess.run([sips, '-s', 'format', 'jpeg', '-s', 'formatOptions', '90', str(src),
                        '--out', str(dst)], check=True, capture_output=True)
    elif ext in CONVERT:
        sys.exit('%s is %s, which the browser cannot show. Save it as PNG or JPG and run again.'
                 % (src.name, ext[1:].upper()))
    else:
        sys.exit('cannot use %s: use PNG, JPG, GIF, WebP or SVG.' % src.name)
    if dst.suffix == '.svg':
        return dst, 'vector'
    w, h = dmd.image_size(dst)
    note = ''
    if w > MAX_W and sips:
        subprocess.run([sips, '--resampleWidth', str(MAX_W), str(dst)], check=True, capture_output=True)
        note = ', scaled down from %dx%d' % (w, h)
        w, h = MAX_W, round(h * MAX_W / w)
    return dst, '%dx%d px%s' % (w, h, note)


def convert(article, tmp):
    """An older format, as .odt (LibreOffice) or .docx (textutil, macOS)."""
    soffice = system.find_soffice()
    if soffice:
        prof = (tmp / 'lo-profile').resolve().as_uri()
        system.run([soffice, '-env:UserInstallation=' + prof, '--headless', '--convert-to', 'odt',
                    '--outdir', str(tmp), str(article)], timeout=180)
        out = tmp / (article.stem + '.odt')
        if out.exists():
            return out
    textutil = system.tool('textutil')
    if textutil:
        out = tmp / 'converted.docx'
        r = system.run([textutil, '-convert', 'docx', '-output', str(out), str(article)])
        if r.returncode == 0 and out.exists():
            return out
    sys.exit('%s cannot be read here. Open it in LibreOffice or Word and save it as .odt or .docx.'
             % article.name)


def set_aside(md_path, work, source_dir):
    """--replace: keep the previous working file, source and images, dated."""
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H%M%S')
    prev = work / 'previous' / stamp
    prev.mkdir(parents=True, exist_ok=True)
    shutil.move(str(md_path), str(prev / md_path.name))
    for d in ('source', 'images'):
        if (work / d).exists():
            shutil.move(str(work / d), str(prev / d))
    return prev


# ------------------------------------------------------------------ main

def main():
    system.utf8_output()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opts = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    replace = '--replace' in sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    article = pathlib.Path(args[0]).expanduser().resolve()
    if not article.exists():
        sys.exit('article not found: %s' % article)
    ext = article.suffix.lower()
    if ext in ('.pages', '.key', '.numbers'):
        sys.exit('A Pages file cannot be read. Ask for it as Word: File > Export To > Word.')
    if ext == '.pdf':
        sys.exit('A PDF is a finished layout, not a source. Ask for the article as .odt or .docx.')

    root = pathlib.Path(opts['root']).expanduser() if 'root' in opts else article.parent
    root = root.resolve()

    # read the article into markdown
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='typesetter-ingest-'))
    (tmp / 'img').mkdir()
    embedded, candidates, skipped = [], [], []
    src = convert(article, tmp) if ext in CONVERTIBLE else article
    kind = src.suffix.lower()
    if kind in ('.md', '.markdown', '.mdown'):
        body = src.read_text(encoding='utf-8')
        if body.startswith('---\n') and '\n---' in body[4:]:
            body = body[body.find('\n---', 4) + 4:].lstrip('\n')
    elif kind == '.txt':
        body = src.read_text(encoding='utf-8', errors='replace')
    elif kind == '.docx':
        body, embedded, candidates = docx_to_md(src, tmp / 'img', 1)
    elif kind in ('.odt', '.ott'):
        body, embedded, candidates, skipped = odt.to_markdown(src, tmp / 'img', 1)
    else:
        sys.exit('Unknown article format %s. LibreOffice (.odt), Word (.docx), markdown and text are read.' % ext)

    # the title: --title, else the first line when it reads as one
    lines = body.split('\n')
    first = next((k for k, l in enumerate(lines) if l.strip()), None)
    title = opts.get('title', '').strip()
    took = False
    if first is not None:
        cand = plain(lines[first])
        looks = (lines[first].lstrip().startswith('#') or re.match(r'^\s*(\*\*|__).+(\*\*|__)\s*$', lines[first])
                 or len(cand.split()) <= 14)
        if (title and cand.lower() == title.lower()) or (not title and looks):
            title = title or cand
            del lines[first]
            took = True
    if not title:
        sys.exit('No title found. Give one with --title="..." exactly as the article has it.')
    body = '\n'.join(lines).lstrip('\n')

    md_path = root / (safe_name(title) + '.md')
    s = slug(title)
    work = root / 'WORKINGS' / s
    prev = None
    if md_path.exists():
        if not replace:
            sys.exit('%s already exists. It carries the layout work done on it: edit and rebuild it, '
                     'or, if the article itself has changed, run again with --replace.' % md_path)
        prev = set_aside(md_path, work, work / 'source')
    for d in ('source', 'images', 'previews'):
        (work / d).mkdir(parents=True, exist_ok=True)
    source_copy = work / 'source' / article.name
    if article.is_dir():                                  # .rtfd is a folder
        shutil.copytree(article, source_copy, dirs_exist_ok=True)
    else:
        shutil.copy2(article, source_copy)

    placed = []
    n = 1
    for e in embedded:
        dst = work / 'images' / e.name
        shutil.copy2(e, dst)
        placed.append((dst, 'embedded in the article'))
        n += 1
    for img in args[1:]:
        dst, note = take_image(img, work / 'images', n)
        placed.append((dst, '%s, from %s' % (note, pathlib.Path(img).name)))
        n += 1
    # embedded images were named before the workings path was known
    for dst, _ in placed:
        body = body.replace('![](%s)' % dst.name, '![](WORKINGS/%s/images/%s)' % (s, dst.name))

    rel = lambda p: p.relative_to(root).as_posix()
    fm = ['---',
          'Title: "%s"' % title.replace('"', '\\"'),
          'Tag: MARKET REPORT',
          'Date: %s' % datetime.date.today().isoformat(),
          'Focus: ',
          'Source: "%s"' % rel(source_copy),
          'Workings: "%s"' % rel(work),
          'Contact box: true',
          'Disclaimer: ',
          'Removed:',
          '---', '']
    head = []
    if placed:
        head.append('<!-- Images to place. Move each line to where the text discusses it, then delete this note.')
        for dst, note in placed:
            head.append('     ![](%s)      %s' % (rel(dst), note))
        head.append('-->')
        head.append('')
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text('\n'.join(fm + head) + body.rstrip() + '\n', encoding='utf-8')

    print('working file  %s' % md_path)
    if prev:
        print('previous      kept in %s' % prev)
    print('title         %s%s' % (title, '   (lifted from the first line)' if took else ''))
    print('source copy   %s' % source_copy)
    print('images        %d in %s' % (len(placed), work / 'images'))
    for dst, note in placed:
        print('  %s   %s' % (dst.name, note))
    for sk in skipped:
        print('left out      %s (generated, not written text)' % sk)
    if candidates:
        print('\nBold one-line paragraphs. If one works as a heading, mark it with ##:')
        for c in candidates:
            print('  %s' % c)
    print('\nNext: set Tag, Focus and Date from the article, place the images, then')
    print('  %s "%s" "%s"' % (system.python_cmd(), pathlib.Path(__file__).with_name('build.py'), md_path))


if __name__ == '__main__':
    main()
