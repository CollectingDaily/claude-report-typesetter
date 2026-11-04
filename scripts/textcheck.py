#!/usr/bin/env python3
"""Gate. The words and figures in the finished HTML are Dan's, in Dan's order.

    python3 textcheck.py <Dan's original file> <finished.html> [--tag "MARKET REPORT"]

This skill typesets. It does not write, edit, correct or improve. The only way
to be sure of that is to compare what came in with what went out, mechanically,
because "I only moved things around" is exactly what a model says after it has
tidied a sentence.

What is compared
    The source: Dan's original file, read directly -- markdown with its markup
    stripped, a Word document's own XML text, or plain text. Never the working
    markdown, because that is the file we edited.
    The output: every word a reader sees in the HTML, in reading order: title,
    focus line, headings, body, tables, captions, notes. Layout furniture is
    excluded and listed instead: the header tag, the date, the contact box and
    the disclaimer, all marked data-skip by build.py.

How
    Both sides become word tokens: lower-cased, straight quotes, surrounding
    punctuation trimmed. Figures keep their signs and symbols, so £4.2m, -5%
    and $181.2 are compared exactly. It is a check of words and figures, not of
    punctuation or capitals: a changed comma is not caught, a changed number is.

Result
    Any word or figure added, dropped or changed fails, with the context around
    it. Two exceptions are reported but pass:
      - the article's own opening label moved into the header tag;
      - text listed under `Removed:` in the working markdown's frontmatter, for
        notes Dan wrote to whoever lays it out ("image here"). Each is printed.

Exit 0 = identical. 1 = a difference that is not accounted for.
"""
import difflib
import html
import html.parser
import pathlib
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import odt      # noqa: E402
import system   # noqa: E402

STRIP = '.,;:!?"\'()[]{}<>*_~`#|•·–—-…/\\=^'
BLOCK_TAGS = {'p', 'div', 'li', 'td', 'th', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br',
              'figcaption', 'section', 'header', 'table', 'ul', 'ol', 'caption', 'aside',
              'blockquote', 'figure'}


def tokens(text):
    text = (text.replace('’', "'").replace('‘', "'").replace('“', '"')
                .replace('”', '"').replace('­', '').replace('​', '')
                .replace('‌', '').replace('‍', '').replace('﻿', '')
                .replace('−', '-'))
    out = []
    for t in text.split():
        t = t.replace('**', '').replace('__', '')
        left = t.lstrip(STRIP.replace('-', ''))
        if not re.match(r'^-\d', left):          # keep the sign on -5%, drop it on a dash
            left = left.lstrip(STRIP)
        t = left.rstrip(STRIP)
        if t:
            out.append(t.lower())
    return out


# ---------------------------------------------------------------- source side

def md_text(raw):
    raw = raw.replace('\r\n', '\n')
    if raw.startswith('---\n'):
        end = raw.find('\n---', 4)
        if end > 0:
            raw = raw[end + 4:]
    raw = re.sub(r'<!--.*?-->', ' ', raw, flags=re.S)
    raw = re.sub(r'!\[([^\]]*)\]\([^)]*\)(\{[^}]*\})?', r' \1 ', raw)       # image: alt text only
    raw = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', raw)                     # link: its text
    raw = re.sub(r'^\s*\[\^[^\]]+\]:', ' ', raw, flags=re.M)                # note definition
    raw = re.sub(r'\[\^[^\]]+\]', '', raw)                                  # note reference
    raw = re.sub(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$', ' ', raw, flags=re.M)
    raw = re.sub(r'<[^>]+>', ' ', raw)
    return html.unescape(raw)


W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def docx_text(path):
    import xml.etree.ElementTree as ET
    out = []
    with zipfile.ZipFile(path) as z:
        parts = ['word/document.xml'] + [n for n in ('word/footnotes.xml', 'word/endnotes.xml')
                                          if n in z.namelist()]
        for part in parts:
            root = ET.fromstring(z.read(part))
            for p in root.iter(W + 'p'):
                buf = []
                for el in p.iter():
                    if el.tag == W + 't' and el.text:
                        buf.append(el.text)
                    elif el.tag in (W + 'tab', W + 'br', W + 'cr'):
                        buf.append(' ')
                out.append(''.join(buf))
    return '\n'.join(out)


def source_text(path):
    path = pathlib.Path(path)
    ext = path.suffix.lower()
    if ext in ('.md', '.markdown', '.mdown'):
        return md_text(path.read_text(encoding='utf-8'))
    if ext == '.txt':
        return path.read_text(encoding='utf-8', errors='replace')
    if ext == '.docx':
        return docx_text(path)
    if ext in ('.odt', '.ott'):
        return odt.plain_text(path)
    # .doc, .rtf, .html: whatever this machine has that reads them
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='typesetter-check-'))
    soffice = system.find_soffice()
    if soffice:
        system.run([soffice, '-env:UserInstallation=' + (tmp / 'lo-profile').resolve().as_uri(), '--headless',
                    '--convert-to', 'odt', '--outdir', str(tmp), str(path)], timeout=180)
        if (tmp / (path.stem + '.odt')).exists():
            return odt.plain_text(tmp / (path.stem + '.odt'))
    if system.tool('textutil'):
        out = tmp / 'src.txt'
        r = system.run([system.tool('textutil'), '-convert', 'txt', '-output', str(out), str(path)])
        if r.returncode == 0 and out.exists():
            return out.read_text(encoding='utf-8', errors='replace')
    sys.exit('cannot read %s as text here: save it as .odt or .docx' % path)


# ---------------------------------------------------------------- output side

class Reader(html.parser.HTMLParser):
    """Visible text in reading order. data-skip is layout furniture, left out and
    listed. data-repeat is the article's own words shown a second time (a pull
    quote, a key figure): left out of the reading order, and kept to be proved
    word for word against the source."""
    VOID = {'img', 'br', 'hr', 'meta', 'link', 'input', 'source', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.stack = [], 0, []
        self.furniture, self.repeats = [], []
        self._buf, self._kind = None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.VOID:
            if tag == 'br':
                (self._buf if self._buf is not None else self.out).append(' ')
            return
        kind = 'skip' if 'data-skip' in a else 'repeat' if 'data-repeat' in a else None
        hide = (tag in ('style', 'script', 'head', 'title') or kind is not None
                or 'fnref' in (a.get('class') or '').split())
        self.stack.append(hide)
        if hide:
            if self.skip == 0 and kind:
                self._buf, self._kind = [], kind
            self.skip += 1
        if tag in BLOCK_TAGS:
            (self._buf if self._buf is not None else self.out if not self.skip else []).append(' ')

    def handle_endtag(self, tag):
        if tag in self.VOID or not self.stack:
            return
        hide = self.stack.pop()
        if hide:
            self.skip -= 1
            if self.skip == 0 and self._buf is not None:
                text = ' '.join(''.join(self._buf).split())
                if text:
                    (self.furniture if self._kind == 'skip' else self.repeats).append(text)
                self._buf, self._kind = None, None
        if tag in BLOCK_TAGS and not self.skip:
            self.out.append(' ')

    def handle_data(self, data):
        if self.skip:
            if self._buf is not None:
                self._buf.append(data)
            return
        self.out.append(data)


def output_text(html_path, repeats=None):
    r = Reader()
    r.feed(pathlib.Path(html_path).read_text(encoding='utf-8'))
    if repeats is not None:
        repeats.extend(r.repeats)
    return ''.join(r.out), r.furniture


# ---------------------------------------------------------------- compare

def compare(src_path, html_path, tag='', removed=()):
    src = tokens(source_text(src_path))
    repeats = []
    text, furniture = output_text(html_path, repeats)
    out = tokens(text)
    tag_t = tokens(tag)
    removed_t = [(r, tokens(r)) for r in removed if r.strip()]

    failures, notes = [], []
    sm = difflib.SequenceMatcher(None, src, out, autojunk=False)
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == 'equal':
            continue
        gone, new = src[a1:a2], out[b1:b2]
        if op == 'delete' and a1 == 0 and gone == tag_t:
            notes.append('moved to the header tag: "%s"' % ' '.join(gone))
            continue
        hit = next((r for r, t in removed_t if op == 'delete' and gone == t), None)
        if hit:
            notes.append('removed as listed under Removed: "%s"' % hit)
            continue
        before = ' '.join(src[max(0, a1 - 8):a1])
        after = ' '.join(src[a2:a2 + 8])
        if op == 'delete':
            what = 'DROPPED  "%s"' % ' '.join(gone)
        elif op == 'insert':
            what = 'ADDED    "%s"' % ' '.join(new)
        else:
            what = 'CHANGED  "%s"  ->  "%s"' % (' '.join(gone), ' '.join(new))
        failures.append('%s\n           in: ...%s [HERE] %s...' % (what, before, after))
    # every pull quote and key figure must be the article's words, word for word
    hay = ' ' + ' '.join(src) + ' '
    for r in repeats:
        rt = tokens(r)
        if rt and (' ' + ' '.join(rt) + ' ') not in hay:
            failures.append('NOT IN THE ARTICLE, WORD FOR WORD  "%s"\n           (a pull quote or key figure must '
                            'repeat the article exactly)' % r)
        elif rt:
            notes.append('repeated from the article: "%s"' % (r if len(r) < 90 else r[:87] + '...'))
    return src, out, furniture, failures, notes


def main():
    system.utf8_output()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    tag = ''
    for a in sys.argv[1:]:
        if a.startswith('--tag='):
            tag = a[6:]
    if len(args) < 2:
        sys.exit('usage: textcheck.py <Dan\'s original> <finished.html> [--tag=TEXT]')
    src, out, furniture, failures, notes = compare(args[0], args[1], tag)
    report(src, out, furniture, failures, notes)
    sys.exit(1 if failures else 0)


def report(src, out, furniture, failures, notes):
    print('text      source %d words, output %d words' % (len(src), len(out)))
    for f in dict.fromkeys(furniture):
        n = furniture.count(f)
        print('  furniture (not Dan\'s text, not compared): %s%s' % (f[:100], '   x%d' % n if n > 1 else ''))
    for n in notes:
        print('  accepted  %s' % n)
    for f in failures[:40]:
        print('  FAIL  %s' % f)
    if len(failures) > 40:
        print('  ...and %d more' % (len(failures) - 40))
    print('  %s' % ('PASS: every word and figure is Dan\'s, in his order.' if not failures else
                    'FAIL: %d difference(s). The text must go out exactly as Dan wrote it.' % len(failures)))


if __name__ == '__main__':
    main()
