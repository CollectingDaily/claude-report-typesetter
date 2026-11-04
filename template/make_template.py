#!/usr/bin/env python3
"""Build the LibreOffice template (.ott) for Dan's documents, in the PFC report layout.

    python3 make_template.py [output.ott]

Default output: PFC report template.ott, beside this script.

Every measurement below is taken from the PFC report layout as it renders in
Chrome (assets/report.css), not estimated:

    page 1   navy band 33mm, logo 15mm high at 11mm/9mm, tag box 56.4 x 15.4mm
             at 142.6mm/8.8mm; cream title band from 33mm; text from 7mm below it
    pages 2+ navy band 20mm, logo 10mm high at 11mm/5mm, tag box 42.1 x 10.2mm
             at 156.9mm/4.9mm; text from 27mm
    all      11mm side margins, 10mm at the foot

How the pieces are built, and why:

  * The navy band and logo are each page style's background image. A page
    background is the only thing in Writer that reaches the edge of the paper;
    a header stops at the page margins.
  * The tag ("MARKET REPORT") is a frame in the header, so it can be retyped.
  * The cream title band is the Title and Subtitle paragraph styles: a cream
    background with negative indents that reach the paper edge, and padding that
    brings the text back to the 11mm margin. So the band grows with the title.
  * The styles are LibreOffice's own (Title, Subtitle, Heading 1-3, Text Body,
    Default Paragraph Style, Caption...), redefined. A document already written
    with them, like Dan's, takes the design when the styles are loaded into it.
  * The Title style carries the First Page page style, so a document that opens
    with a Title gets the tall header on page 1 and the compact one after.
  * Arial throughout: Dan works in LibreOffice on Windows, which has no Helvetica
    Neue, and Arial is the report stylesheet's own fallback.
"""
import pathlib
import sys
import tempfile
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))
import system  # noqa: E402
LOGO = HERE.parent / 'assets' / 'pfc-logo-navy.png'
DEFAULT_OUT = HERE / 'PFC report template.ott'

NAVY, CREAM, TEAL, INK, MUTED, LINE = '#323748', '#f7f4e2', '#8fd1d5', '#231f20', '#6f7280', '#e2e0d8'
FONT = 'Arial'


# ------------------------------------------------------------------ backgrounds

def background(band_mm, logo_top_mm, logo_h_mm, out):
    """A4 at 300 dpi: white, with the navy band and the logo in it."""
    import base64
    logo = 'data:image/png;base64,' + base64.b64encode(LOGO.read_bytes()).decode()
    page = ('<!DOCTYPE html><html><head><style>html,body{margin:0;background:#fff}'
            '.p{position:relative;width:210mm;height:297mm;overflow:hidden}'
            '.b{position:absolute;left:0;top:0;width:210mm;height:%smm;background:%s}'
            '.l{position:absolute;left:11mm;top:%smm;height:%smm}</style></head><body>'
            '<div class="p"><div class="b"></div><img class="l" src="%s"></div></body></html>'
            % (band_mm, NAVY, logo_top_mm, logo_h_mm, logo))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='pfc-bg-')) / 'bg.html'
    tmp.write_text(page, encoding='utf-8')
    # 793.7px is 210mm at 96px/in; x3.125 gives 300 dpi
    system.run([system.find_chrome(), '--headless=new', '--disable-gpu', '--hide-scrollbars',
                '--window-size=794,1123', '--force-device-scale-factor=3.125',
                '--screenshot=%s' % out, system.file_url(tmp)], check=True)
    return out.read_bytes()


# ------------------------------------------------------------------ XML

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
      'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
      'xmlns:xlink="http://www.w3.org/1999/xlink" '
      'xmlns:dc="http://purl.org/dc/elements/1.1/" '
      'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
      'xmlns:loext="urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0" '
      'office:version="1.3"')

FONTS = ('<office:font-face-decls><style:font-face style:name="%s" svg:font-family="%s" '
         'style:font-family-generic="swiss" style:font-pitch="variable"/></office:font-face-decls>' % (FONT, FONT))


def pstyle(name, display=None, parent='Standard', nxt=None, para='', text='', extra=''):
    # LibreOffice matches styles by display name, and the display name must be
    # exactly LibreOffice's own: the internal name with _20_ read as a space
    # ("Text_20_body" is "Text body"). Tested both ways it goes wrong: "Text Body"
    # made a second, unused style, and no display name at all made a style
    # literally called "Heading_20_1". So it is always derived, never typed.
    d = ' style:display-name="%s"' % name.replace('_20_', ' ') if '_20_' in name else ''
    p = ' style:parent-style-name="%s"' % parent if parent else ''
    n = ' style:next-style-name="%s"' % nxt if nxt else ''
    return ('<style:style style:name="%s"%s style:family="paragraph"%s%s%s>'
            '<style:paragraph-properties %s/><style:text-properties %s/></style:style>'
            % (name, d, p, n, extra, para, text))


def txt(size, bold=False, color=INK, extra=''):
    b = ' fo:font-weight="bold" style:font-weight-asian="bold" style:font-weight-complex="bold"' if bold else ''
    return ('style:font-name="%s" fo:font-size="%spt" style:font-size-asian="%spt" '
            'style:font-size-complex="%spt" fo:color="%s"%s %s' % (FONT, size, size, size, color, b, extra))


# Title and Subtitle merge into one cream block ("merge with next paragraph").
# Writer merges any two neighbours whose borders match, and a body paragraph has
# no border either, so without a border of its own the band would merge with the
# first paragraph of text and lose its bottom padding. A hairline in the band's
# own cream is invisible and makes Title and Subtitle match only each other.
BAND = ('fo:margin-left="-11mm" fo:margin-right="-11mm" fo:text-indent="0mm" style:auto-text-indent="false" '
        'fo:padding-left="11mm" fo:padding-right="11mm" fo:background-color="%s" '
        'fo:border="0.02mm solid %s" style:join-border="true"' % (CREAM, CREAM))

STYLES = [
    # Default Paragraph Style: the body of the report
    pstyle('Standard', parent=None,
           para='fo:margin-top="0mm" fo:margin-bottom="2.5mm" fo:line-height="150%" fo:orphans="2" fo:widows="2" '
                'fo:hyphenation-ladder-count="no-limit"',
           text=txt(9.5) + ' fo:language="en" fo:country="GB" fo:hyphenate="false"'),
    pstyle('Text_20_body', 'Text Body', nxt='Text_20_body',
           para='fo:margin-top="0mm" fo:margin-bottom="2.5mm" fo:line-height="150%"', text=txt(9.5)),
    pstyle('Heading', parent='Standard', nxt='Text_20_body',
           para='fo:keep-with-next="always" fo:line-height="150%"', text=txt(9.5, True)),
    # report h2: section heading
    pstyle('Heading_20_1', 'Heading 1', parent='Heading', nxt='Text_20_body',
           para='fo:margin-top="6mm" fo:margin-bottom="2.4mm" fo:keep-with-next="always"',
           text=txt(15, True), extra=' style:default-outline-level="1" style:list-style-name=""'),
    # report h3: sub-heading (1.17em of the 9.5pt body, 1em above and below)
    pstyle('Heading_20_2', 'Heading 2', parent='Heading', nxt='Text_20_body',
           para='fo:margin-top="3.9mm" fo:margin-bottom="3.9mm" fo:keep-with-next="always"',
           text=txt(11.1, True), extra=' style:default-outline-level="2" style:list-style-name=""'),
    pstyle('Heading_20_3', 'Heading 3', parent='Heading', nxt='Text_20_body',
           para='fo:margin-top="3mm" fo:margin-bottom="1mm" fo:keep-with-next="always"',
           text=txt(9.5, True), extra=' style:default-outline-level="3" style:list-style-name=""'),
    # the cream title band on page 1
    pstyle('Title', parent='Standard', nxt='Subtitle',
           para=BAND + ' fo:margin-top="0mm" fo:margin-bottom="4mm" fo:padding-top="8mm" fo:padding-bottom="7mm" '
                'fo:line-height="108%" fo:text-align="start" fo:keep-with-next="always"',
           text=txt(25, True) + ' fo:text-transform="uppercase" fo:letter-spacing="0.49mm"',
           extra=' style:master-page-name="First_20_Page"'),
    pstyle('Subtitle', parent='Standard', nxt='Text_20_body',
           para=BAND + ' fo:margin-top="0mm" fo:margin-bottom="7mm" fo:padding-top="8mm" fo:padding-bottom="7mm" '
                'fo:line-height="155%" fo:text-align="start"',
           text=txt(9.4)),
    # the cream pull-out band
    pstyle('PFC_20_Pull-out', 'PFC Pull-out', nxt='Text_20_body',
           para='fo:margin-top="4mm" fo:margin-bottom="4mm" fo:padding-top="6mm" fo:padding-bottom="6mm" '
                'fo:padding-left="9mm" fo:padding-right="9mm" fo:background-color="%s" fo:text-align="center" '
                'fo:line-height="135%%" style:join-border="false"' % CREAM,
           text=txt(13.5)),
    pstyle('Quotations', parent='PFC_20_Pull-out', nxt='Text_20_body'),
    # captions under images
    pstyle('Caption', parent='Standard', nxt='Text_20_body',
           para='fo:margin-top="2.5mm" fo:margin-bottom="4mm" fo:text-align="center" fo:line-height="135%"',
           text=txt(7.4, color=MUTED)),
    pstyle('Figure', parent='Caption', nxt='Text_20_body'),
    pstyle('Illustration', parent='Caption', nxt='Text_20_body'),
    # tables
    pstyle('Table_20_Contents', 'Table Contents', para='fo:margin-top="0mm" fo:margin-bottom="0mm" fo:line-height="130%"',
           text=txt(8.5)),
    pstyle('Table_20_Heading', 'Table Heading', parent='Table_20_Contents',
           para='fo:text-align="start"',
           text=txt(7.8, True, '#ffffff') + ' fo:text-transform="uppercase" fo:letter-spacing="0.14mm"'),
    # lists
    pstyle('List_20_Paragraph', 'List Paragraph', para='fo:margin-top="0mm" fo:margin-bottom="1mm"'),
    pstyle('List', parent='Text_20_body'),
    # the contact box and the disclaimer, as the reports close
    pstyle('PFC_20_Contact_20_label', 'PFC Contact label', nxt='PFC_20_Contact',
           para='fo:margin-top="7mm" fo:margin-bottom="0mm" fo:padding-top="6mm" fo:padding-bottom="3.5mm" '
                'fo:padding-left="8mm" fo:padding-right="8mm" fo:background-color="%s" fo:text-align="center" '
                'fo:keep-with-next="always" fo:line-height="100%%" style:join-border="false"' % NAVY,
           text=txt(7.6, True, TEAL) + ' fo:text-transform="uppercase" fo:letter-spacing="0.48mm"'),
    pstyle('PFC_20_Contact', 'PFC Contact', nxt='PFC_20_Disclaimer',
           para='fo:margin-top="0mm" fo:margin-bottom="0mm" fo:padding-top="0mm" fo:padding-bottom="6mm" '
                'fo:padding-left="8mm" fo:padding-right="8mm" fo:background-color="%s" fo:text-align="center" '
                'fo:line-height="180%%" style:join-border="false"' % NAVY,
           text=txt(11.5, color='#ffffff')),
    pstyle('PFC_20_Disclaimer', 'PFC Disclaimer',
           para='fo:margin-top="8mm" fo:margin-bottom="0mm" fo:text-align="center" fo:line-height="130%"',
           text=txt(7, color=MUTED)),
    # the tag in the header band
    pstyle('Header', parent='Standard',
           para='fo:margin-top="0mm" fo:margin-bottom="0mm" fo:line-height="100%"', text=txt(2)),
    pstyle('PFC_20_Tag', 'PFC Tag', parent=None,
           para='fo:margin="0mm" fo:text-align="center" fo:line-height="100%"',
           text=txt(11, True, '#ffffff') + ' fo:letter-spacing="0.62mm"'),
    pstyle('PFC_20_Tag_20_compact', 'PFC Tag compact', parent=None,
           para='fo:margin="0mm" fo:text-align="center" fo:line-height="100%"',
           text=txt(8.5, True, '#ffffff') + ' fo:letter-spacing="0.42mm"'),
]

CHAR_STYLES = [
    '<style:style style:name="Internet_20_link" style:display-name="Internet link" style:family="text">'
    '<style:text-properties fo:color="%s" style:text-underline-style="solid" style:text-underline-width="auto" '
    'style:text-underline-color="font-color"/></style:style>' % NAVY,
    '<style:style style:name="PFC_20_Label" style:display-name="PFC Label" style:family="text">'
    '<style:text-properties fo:font-weight="bold" fo:letter-spacing="0.1mm"/></style:style>',
    '<style:style style:name="Strong_20_Emphasis" style:display-name="Strong Emphasis" style:family="text">'
    '<style:text-properties fo:font-weight="bold"/></style:style>',
]

# inserted images: no text wrap, centred in the column
GRAPHIC = ('<style:style style:name="Frame" style:family="graphic"><style:graphic-properties text:anchor-type="paragraph" style:wrap="parallel"/></style:style>'
           '<style:style style:name="Graphics" style:family="graphic">'
           '<style:graphic-properties text:anchor-type="paragraph" svg:x="0mm" svg:y="0mm" '
           'fo:margin-top="4mm" fo:margin-bottom="2mm" style:wrap="none" style:vertical-pos="top" '
           'style:vertical-rel="paragraph" style:horizontal-pos="center" style:horizontal-rel="paragraph" '
           'fo:border="none" fo:padding="0mm"/></style:style>')

LIST_STYLE = ('<text:list-style style:name="List_20_1" style:display-name="Bullet •">%s</text:list-style>'
              % ''.join('<text:list-level-style-bullet text:level="%d" text:bullet-char="•">'
                        '<style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
                        '<style:list-level-label-alignment text:label-followed-by="listtab" '
                        'text:list-tab-stop-position="%.1fmm" fo:text-indent="-4.6mm" fo:margin-left="%.1fmm"/>'
                        '</style:list-level-properties><style:text-properties style:font-name="%s"/>'
                        '</text:list-level-style-bullet>' % (n, 4.6 * n, 4.6 * n, FONT) for n in range(1, 11)))

# Chapter numbering with nothing in it. Word-born documents (Dan's among them)
# carry an outline whose empty number is followed by a tab, which pushes every
# heading to the next tab stop. Loading these styles puts the headings back at
# the margin.
OUTLINE = ('<text:outline-style style:name="Outline">%s</text:outline-style>'
           % ''.join('<text:outline-level-style text:level="%d" style:num-format="">'
                     '<style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
                     '<style:list-level-label-alignment text:label-followed-by="nothing" fo:text-indent="0mm" '
                     'fo:margin-left="0mm"/></style:list-level-properties></text:outline-level-style>' % n
                     for n in range(1, 11)))

NUM_STYLE = ('<text:list-style style:name="Numbering_20_123" style:display-name="Numbering 123">%s</text:list-style>'
             % ''.join('<text:list-level-style-number text:level="%d" style:num-suffix="." style:num-format="1">'
                       '<style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
                       '<style:list-level-label-alignment text:label-followed-by="listtab" '
                       'text:list-tab-stop-position="%.1fmm" fo:text-indent="-4.6mm" fo:margin-left="%.1fmm"/>'
                       '</style:list-level-properties></text:list-level-style-number>'
                       % (n, 4.6 * n, 4.6 * n) for n in range(1, 11)))


def page_layout(name, image, header_h, gap):
    # header_h is Writer's header height, which INCLUDES the gap below it
    # (measured: 20mm with a 7mm gap put the text at 20mm, not 27mm)
    return ('<style:page-layout style:name="%s"><style:page-layout-properties fo:page-width="210mm" '
            'fo:page-height="297mm" style:print-orientation="portrait" fo:margin-top="0mm" fo:margin-bottom="10mm" '
            'fo:margin-left="11mm" fo:margin-right="11mm" style:writing-mode="lr-tb" '
            'draw:fill="bitmap" draw:fill-image-name="%s" style:repeat="stretch" draw:background-size="full"/>'
            '<style:header-style><style:header-footer-properties svg:height="%smm" fo:margin-left="0mm" '
            'fo:margin-right="0mm" fo:margin-bottom="%smm" style:dynamic-spacing="false"/></style:header-style>'
            '<style:footer-style/></style:page-layout>' % (name, image, header_h, gap))


def tag_frame(style, x, y, w, h, para):
    return ('<text:p text:style-name="Header"><draw:frame draw:style-name="%s" draw:name="Tag %s" '
            'text:anchor-type="paragraph" svg:x="%smm" svg:y="%smm" svg:width="%smm" svg:height="%smm" '
            'draw:z-index="1"><draw:text-box fo:min-height="%smm"><text:p text:style-name="%s">MARKET REPORT</text:p>'
            '</draw:text-box></draw:frame></text:p>' % (style, style, x, y, w, h, h, para))


FRAME_STYLE = ('<style:style style:name="%s" style:family="graphic" style:parent-style-name="Frame">'
               '<style:graphic-properties '
               'style:wrap="run-through" style:run-through="foreground" style:vertical-pos="from-top" '
               'style:vertical-rel="page" style:horizontal-pos="from-left" style:horizontal-rel="page" '
               'fo:border="0.37mm solid #ffffff" fo:padding="0mm" draw:fill="none" fo:background-color="transparent" '
               'draw:textarea-vertical-align="middle" style:flow-with-text="false"/></style:style>')


def styles_xml():
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<office:document-styles %s>%s'
            '<office:styles>'
            '<draw:fill-image draw:name="PFC_20_first" draw:display-name="PFC first" xlink:href="Pictures/pfc-first.png" '
            'xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>'
            '<draw:fill-image draw:name="PFC_20_page" draw:display-name="PFC page" xlink:href="Pictures/pfc-page.png" '
            'xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>'
            '<style:default-style style:family="paragraph"><style:paragraph-properties style:tab-stop-distance="12.5mm"/>'
            '<style:text-properties style:font-name="%s" fo:font-size="9.5pt" fo:language="en" fo:country="GB" '
            'fo:hyphenate="false"/></style:default-style>'
            '%s%s%s%s%s%s'
            '</office:styles>'
            '<office:automatic-styles>%s%s%s%s</office:automatic-styles>'
            '<office:master-styles>'
            '<style:master-page style:name="Standard" style:page-layout-name="pm_page">'
            '<style:header>%s</style:header></style:master-page>'
            '<style:master-page style:name="First_20_Page" style:display-name="First Page" '
            'style:page-layout-name="pm_first" style:next-style-name="Standard">'
            '<style:header>%s</style:header></style:master-page>'
            '</office:master-styles></office:document-styles>'
            % (NS, FONTS, FONT, ''.join(STYLES), ''.join(CHAR_STYLES), GRAPHIC, LIST_STYLE, NUM_STYLE, OUTLINE,
               page_layout('pm_page', 'PFC_20_page', 27, 7), page_layout('pm_first', 'PFC_20_first', 33, 0),
               FRAME_STYLE % 'fr_tag_page', FRAME_STYLE % 'fr_tag_first',
               tag_frame('fr_tag_page', 156.93, 4.89, 42.07, 10.22, 'PFC_20_Tag_20_compact'),
               tag_frame('fr_tag_first', 142.64, 8.83, 56.36, 15.35, 'PFC_20_Tag')))


def content_xml():
    """The sample a new document opens with: one of everything, to be typed over."""
    ph = lambda s: '<text:placeholder text:placeholder-type="text">&lt;%s&gt;</text:placeholder>' % s
    cell = lambda style, p, t: ('<table:table-cell table:style-name="%s" office:value-type="string">'
                                '<text:p text:style-name="%s">%s</text:p></table:table-cell>' % (style, p, t))
    auto = ('<office:automatic-styles>'
            '<style:style style:name="Tbl" style:family="table"><style:table-properties style:width="188mm" '
            'table:align="margins" fo:margin-top="0mm" fo:margin-bottom="3.2mm"/></style:style>'
            '<style:style style:name="TblH" style:family="table-cell"><style:table-cell-properties '
            'fo:background-color="%s" fo:padding-top="1.1mm" fo:padding-bottom="1.1mm" fo:padding-left="1.6mm" '
            'fo:padding-right="1.6mm" fo:border="none"/></style:style>'
            '<style:style style:name="TblC" style:family="table-cell"><style:table-cell-properties '
            'fo:padding-top="0.9mm" fo:padding-bottom="0.9mm" fo:padding-left="1.6mm" fo:padding-right="1.6mm" '
            'fo:border-left="none" fo:border-right="none" fo:border-top="none" fo:border-bottom="0.26mm solid %s"/>'
            '</style:style>'
            '<style:style style:name="TblE" style:family="table-cell"><style:table-cell-properties '
            'fo:background-color="#fbfaf4" fo:padding-top="0.9mm" fo:padding-bottom="0.9mm" fo:padding-left="1.6mm" '
            'fo:padding-right="1.6mm" fo:border-left="none" fo:border-right="none" fo:border-top="none" '
            'fo:border-bottom="0.26mm solid %s"/></style:style>'
            '<style:style style:name="Num" style:family="paragraph" style:parent-style-name="Table_20_Contents">'
            '<style:paragraph-properties fo:text-align="end"/><style:text-properties fo:font-weight="bold"/></style:style>'
            '<style:style style:name="NumH" style:family="paragraph" style:parent-style-name="Table_20_Heading">'
            '<style:paragraph-properties fo:text-align="end"/></style:style>'
            '</office:automatic-styles>' % (NAVY, LINE, LINE))
    body = [
        '<text:p text:style-name="Title">%s</text:p>' % ph('Report title'),
        '<text:p text:style-name="Subtitle"><text:span text:style-name="PFC_20_Label">DATE</text:span> %s'
        '<text:line-break/><text:span text:style-name="PFC_20_Label">FOCUS</text:span> %s</text:p>'
        % (ph('YYYY-MM-DD'), ph('Category · Category · Category')),
        '<text:h text:style-name="Heading_20_1" text:outline-level="1">Section heading (Heading 1)</text:h>',
        '<text:p text:style-name="Text_20_body">Body text (Text Body). Replace this sample with the article. '
        'Sections use Heading 1, sub-sections Heading 2, and everything else Text Body. The header, the '
        'title band and the page layout follow on their own.</text:p>',
        '<text:h text:style-name="Heading_20_2" text:outline-level="2">Sub-heading (Heading 2)</text:h>',
        '<text:p text:style-name="Text_20_body">A second paragraph of body text.</text:p>',
        '<text:list text:style-name="List_20_1"><text:list-item><text:p text:style-name="List_20_Paragraph">'
        'A bullet point (List Paragraph)</text:p></text:list-item><text:list-item>'
        '<text:p text:style-name="List_20_Paragraph">A second bullet point</text:p></text:list-item></text:list>',
        '<text:p text:style-name="PFC_20_Pull-out">A pull-out quotation, in the cream band (PFC Pull-out).</text:p>',
        '<table:table table:name="Sample" table:style-name="Tbl"><table:table-column table:number-columns-repeated="3"/>'
        '<table:table-header-rows><table:table-row>%s%s%s</table:table-row></table:table-header-rows>'
        '<table:table-row>%s%s%s</table:table-row><table:table-row>%s%s%s</table:table-row></table:table>'
        % (cell('TblH', 'Table_20_Heading', 'Lot'), cell('TblH', 'Table_20_Heading', 'Sale'),
           cell('TblH', 'NumH', 'Price'),
           cell('TblC', 'Table_20_Contents', 'Sample lot'), cell('TblC', 'Table_20_Contents', 'House, Mon YYYY'),
           cell('TblC', 'Num', '£0,000'),
           cell('TblE', 'Table_20_Contents', 'Sample lot'), cell('TblE', 'Table_20_Contents', 'House, Mon YYYY'),
           cell('TblE', 'Num', '£0,000')),
        '<text:p text:style-name="Caption">An image caption (Caption).</text:p>',
        '<text:p text:style-name="PFC_20_Contact_20_label">Contact</text:p>',
        '<text:p text:style-name="PFC_20_Contact">+44 (0) 1534 639998<text:line-break/>'
        '<text:span text:style-name="Strong_20_Emphasis">paulfrasercollectibles.com</text:span>'
        '<text:line-break/>info@paulfrasercollectibles.com</text:p>',
        '<text:p text:style-name="PFC_20_Disclaimer">This document is non-independent investment research '
        'and a marketing communication.</text:p>',
    ]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content %s>%s%s'
            '<office:body><office:text>%s</office:text></office:body></office:document-content>'
            % (NS, FONTS, auto, ''.join(body)))


META = ('<?xml version="1.0" encoding="UTF-8"?>\n<office:document-meta %s><office:meta>'
        '<dc:title>PFC report</dc:title><meta:generator>report-typesetter make_template.py</meta:generator>'
        '</office:meta></office:document-meta>' % NS)

MANIFEST = ('<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest '
            'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
            '<manifest:file-entry manifest:full-path="/" manifest:version="1.3" '
            'manifest:media-type="application/vnd.oasis.opendocument.text-template"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="Pictures/pfc-first.png" manifest:media-type="image/png"/>'
            '<manifest:file-entry manifest:full-path="Pictures/pfc-page.png" manifest:media-type="image/png"/>'
            '</manifest:manifest>')


def main():
    out = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='pfc-ott-'))
    first = background(33, 9, 15, tmp / 'first.png')
    page = background(20, 5, 10, tmp / 'page.png')
    with zipfile.ZipFile(out, 'w') as z:
        # the mimetype must come first and uncompressed, or it is not an ODF file
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/vnd.oasis.opendocument.text-template',
                   compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/manifest.xml', MANIFEST, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('meta.xml', META, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('styles.xml', styles_xml(), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('content.xml', content_xml(), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('Pictures/pfc-first.png', first, compress_type=zipfile.ZIP_STORED)
        z.writestr('Pictures/pfc-page.png', page, compress_type=zipfile.ZIP_STORED)
    print('wrote %s (%d KB)' % (out, out.stat().st_size // 1024))


if __name__ == '__main__':
    main()
