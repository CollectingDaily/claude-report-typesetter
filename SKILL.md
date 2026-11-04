---
name: report-typesetter
description: "Typeset an article and images supplied by Dan as a finished A4 PDF and a self-contained HTML page, in the Paul Fraser Collectibles report layout. Conversion only: it never writes, edits, corrects, humanises or source-checks the text. Use when Dan (Daniel) sends an article, with or without images, to be turned into a designed PDF or HTML, or when asked to lay out someone else's finished text in the PFC report design."
---

# Report typesetter: article and images in, designed PDF and HTML out

Requested by Daniel (Dan). He sends two things: **an article** and **images**. This skill turns them into a designed A4 document in the PFC report layout, and nothing more.

## What this skill does not do

This skill only designs. That is the whole point of it, so hold to it exactly:

- **Never write.** No new sentence, heading, caption, summary, section or "about us". A pull quote or a key figure may only repeat his words exactly. If a section is empty in Dan's article, it is empty in the PDF.
- **Never edit.** Not a word, not a figure, not a spelling, not British English, not a comma. Dan's text goes out as Dan wrote it, typos included. The humanizer is not used.
- **Never check sources.** No fetching, no verification, no evidence log. The figures are Dan's and are typeset as given.
- **Never fill a gap.** A placeholder like `TEXT TO GO HERE` stays in and is reported. A missing image is reported, not found elsewhere.

`scripts/textcheck.py` enforces the first two mechanically: the build compares every word and figure in the finished HTML against Dan's original file, in his order, and proves every pull quote and key figure word for word against it; it **refuses to write a PDF if anything differs**. It checks words and figures, not punctuation or capitals.

What you may do is layout, and only layout: decide which lines are headings, where each image sits, which passages become cards, panels or boxes, which of his sentences to repeat as pull quotes, which of his figures go in the sidebar, where a page must break, and the frontmatter below.

If you notice something that would embarrass in print (a placeholder, text pointing at an image nobody supplied, a figure in the text that disagrees with the same figure in a chart), **do not fix it.** List it in the handover, quoting both sides, and let a person decide.

## The layout

The PFC report layout, carried in full inside this skill so it depends on nothing else:

| Path | What it is |
| --- | --- |
| `assets/report.css` | The PFC report stylesheet. Do not edit it to change one document. |
| `assets/typesetter.css` | Everything added for Dan's documents: exact block measurement, supplied images of any shape, split paragraphs and tables, links, footnotes. Loaded after `report.css`. |
| `assets/pfc-logo-navy.png` | The PFC logo lockup on navy. |

Navy header band with the logo and a tag on every page (full height on page 1, compact after), the cream title band on page 1 with the title and `DATE` (and `FOCUS` when the article gives one), single-column body, navy table headers, the cream pull-out band, the disclaimer centred at the foot of the last page.

## The scripts

| Script | What it does |
| --- | --- |
| `scripts/ingest.py` | Sets a job up. Copies Dan's article **untouched** into `WORKINGS/<slug>/source/` (the text check compares against this copy, so it is never edited), copies the images into `WORKINGS/<slug>/images/` as `01-…`, `02-…`, then writes the working markdown with the title lifted into the frontmatter. Reads LibreOffice `.odt`, Word `.docx`, `.md` and `.txt` directly, keeping headings, lists, bold, italics, links, tables, footnotes and embedded images. Older formats (`.doc .rtf .html`) go through LibreOffice if it is installed, or macOS `textutil`. Layout tables (two-column pages, sidebars) are read as flowing text. It refuses Pages and PDF files: ask for `.odt` or `.docx`. `--replace` re-runs it after the article has changed, keeping the previous version. |
| `scripts/odt.py` | The LibreOffice reader, plus a separate plain-text reader the text check uses, so the check never trusts the conversion it is checking. |
| `scripts/system.py` | Everything that differs between macOS and Windows: where Chrome, Edge and LibreOffice live, file addresses, UTF-8 output. |
| `scripts/build.py` | Turns the working markdown into the deliverables. Measures every block in headless Chrome, flows them into A4 sheets, verifies the real sheets, runs the gates, prints the PDF, renders page previews. |
| `scripts/dmd.py` | The markdown dialect. Its docstring is the reference. |
| `scripts/textcheck.py` | The gate that proves the words are Dan's. Runs inside the build; can be run alone. |

## Mac and Windows

The same folder runs on both. It needs **Python 3** (standard library only) and a **Chromium browser**: Google Chrome, or Microsoft Edge, which every Windows PC has. Nothing else is required.

- **Run the scripts with the Python this machine has:** `python3` on macOS, `python` on Windows. Use the commands exactly as written below, with the skill folder given as `${CLAUDE_SKILL_DIR}`, which Claude Code fills in on either system. If Python is missing on Windows, say so in one line and point to the **Python Install Manager** in the Microsoft Store; do not install anything without asking.
- **macOS extras, used only when present:** `sips` (HEIC, TIFF and BMP images become JPEG, and anything over 2400px wide is scaled down), `textutil` (older document formats), `pdftoppm` (page previews rendered from the PDF itself). Without them: images must be PNG, JPG, GIF, WebP or SVG, large ones are used as they are, and **the previews are Chrome screenshots of each sheet, which the handover must say**.
- **Fonts:** the stylesheet asks for Helvetica Neue, then Arial. Windows has no Helvetica Neue, so a PDF made there is set in Arial. The pages are measured on the machine that builds them, so the layout adjusts; it is not an error.

## Where the files go

```
<root>/                         see below; --root=<dir> overrides it
    <Title>.md                  working file: Dan's text, plus layout
    PDFs/<Title>.pdf            deliverable
    HTML/<Title>.html           deliverable, fully self-contained (logo, images, CSS inlined)
    WORKINGS/<slug>/
        source/<Dan's file>     his original, untouched
        images/                 his images, numbered in the order given
        previews/page-NN.png    every page, for the visual review
```

`<root>` is **the folder the article is in**, on every machine, so the PDF and HTML land in `PDFs/` and `HTML/` beside it. `--root=<dir>` puts them somewhere else.

## Steps

1. **Get the inputs onto disk.** Usually Dan opens his report folder and asks for "the article and images in this folder": the article is the one `.odt`, `.docx` or `.md` file in it (ask which, in one line, if there are several), and every PNG, JPG, GIF, WebP or SVG beside it is an image to place. List back what you found. If his article arrived pasted into the chat instead, save it verbatim to a `.md` or `.txt` file first; that file becomes the source the text check trusts. If a file or folder cannot be read (a permission, a privacy setting, a file that is open elsewhere), **stop and say so in one line**, with what to click or where to move the file. Do not carry on with other work as if the input were there.

2. **Read the whole article before anything else**, and look at every image. Know what each image shows and which paragraph it belongs to.

3. **Ingest.**

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/ingest.py" "<article>" "<image 1>" "<image 2>" ...
   ```

   (`python` in place of `python3` on Windows, here and in step 7.) It takes the first line as the title when it looks like one. When the first line is a label rather than the title ("Market update:" above "Music memorabilia"), pass `--title="Music memorabilia"` exactly as Dan wrote it.

   **Running again after Dan has changed his article:** add `--replace`. The previous working file, source copy and images move to `WORKINGS/<slug>/previous/<date time>/`; nothing is deleted. Then redo steps 4 to 8 on the new working file. Without `--replace`, ingest refuses to overwrite a working file, because it carries the layout decisions.

4. **Set the frontmatter** in the working file:

   | Field | Rule |
   | --- | --- |
   | `Title` | From the article, exactly as Dan wrote it. |
   | `Tag` | The label in the header band. Default `MARKET REPORT`. If the article opens with its own label ("Market update:"), use that and delete the line from the body: the text check recognises a label moved into the header. |
   | `Date` | Defaults to today, the day it is typeset. Use Dan's date if the article states one. |
   | `Focus` | Only if the article carries a focus or subtitle line, such as "Instruments · Stage-worn clothing · Autographs". Move it here and delete it from the body. Otherwise leave it empty: never compose one. |
   | `Contact box` | `true` puts the navy PFC contact box after the last text. Set `false` when Dan's own text already ends with the contact details, so they are not printed twice. |
   | `Disclaimer` | Empty gives the standard PFC line, "This document is non-independent investment research and a marketing communication." `none` removes it. |
   | `Removed` | A list of exact strings from the source that were deliberately left out: only notes to the designer, such as "[image here]" where the image now sits. Never text for the reader. The build prints each one. |

5. **Structure the body, without changing a word.**
   - Headings: `#`, `##`, `###` are ranked, so an article that uses `#` for sections and `##` for sub-sections gets the report's section and sub-section styles. From LibreOffice or Word, headings written with the Heading styles arrive already marked. When a document uses bold lines instead, ingest lists them; mark the ones that work as headings with `##`.
   - Keep Dan's own numbering in headings ("1. Stamp collecting…"). Do not add numbers he did not write.
   - A standalone quotation paragraph may become a pull-out: put `> ` in front of it.
   - A bold headline followed by its paragraph (a list of sales) needs nothing: the build keeps them together.

   **Make it less linear, with his own text.** Dan asked for pull-outs, boxes and a less linear page. Every tool below only rearranges or repeats his words; none adds one. Use what the article gives you and skip what it does not: an article without a list of sales gets no cards, and nothing is ever left empty.

   | Mark | Use it for | Rules |
   | --- | --- | --- |
   | *(automatic)* | Section headings sit on a navy band. | Nothing to do. |
   | `::: cards` … `:::` | A run of items that each open with a bold headline and a paragraph (a list of sales, of lots). Each item becomes a card, two to a row; sums of money in the headline are set larger. | Wrap the whole run. |
   | `::: panels` … `:::` | A run of short numbered sub-sections ("1. Stamp collecting is a dying hobby."). Each heading and what follows becomes a panel, the number set large. | Only where Dan numbered them himself, or where the sub-sections are short; long sub-sections stay as text. |
   | `::: box` … `:::` | A list with the sentence that introduces it, or a self-contained passage (an index, a set of figures). | One or two a report; never a whole section. |
   | `::: contact` … `:::` | The article's own contact or "next steps" passage, heading included, on navy. | Then set `Contact box: false`. |
   | `::: beside` … `:::` | A tall or square image with the paragraphs it belongs to, side by side. | Never a wide chart: at half width its labels become unreadable. Look at the preview. |
   | `>> exact words` | A pull quote: a striking sentence repeated large. | Three to six a report, **word for word**: the build refuses one that is not in the article. Put it where it introduces its section (after the heading, before the text or panels), never directly next to the sentence it repeats, and never as the last thing in a section, where it gets pushed onto the next page on its own. |
   | `::: keyfigures` … `:::` | The page-one sidebar. One line per figure: `- $181.2 million \| Jackson Pollock's Number 7A, 1948`. | Four to six figures the article states. **Both the figure and its label must be word for word from the article**; the build proves each. Its heading "Key figures" is layout furniture: say so in the handover. |

   If page 1 ends well short, the first box after its text is too tall for the narrow column beside the sidebar: move a pull quote off page 1, not the figures.

6. **Place every image.** Put `![](WORKINGS/<slug>/images/01-….png)` on its own line after the paragraph that discusses what the image shows, at the most specific reference (the paragraph that names the index a chart plots, not a later general one). Every supplied image must be placed exactly once, or the build refuses.
   - **No caption unless Dan gave one.** `![Caption](path "Credit: X")` when he did. The chart's own title is not a caption to repeat.
   - `{w=150}` or `{h=90}` after the line sets the size in mm. By default an image fills the column but is never enlarged past 110 dpi or made taller than 120mm.
   - Never crop, retouch, recolour or redraw an image. If a screenshot carries interface chrome (buttons, toggles, a cursor) or is too low-resolution, say so in the handover.

7. **Build.**

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/build.py" "<root>/<Title>.md"
   ```

   It flows the blocks into pages. A paragraph may run on to the next page, keeping at least two lines on each side; a table breaks between rows and repeats its header; a list breaks between items; a heading or bold lead-in never ends a page; an image that misses the end of a page by a little is reduced (never by more than 20%) to fit. Then it measures the real sheets and reflows until nothing is clipped, and runs the gates: **text identical to Dan's original, every image placed once, no markdown left showing, no page clipped.** It writes to `HTML/` and `PDFs/` only if all pass. It also warns (without failing) on placeholders in Dan's text and on text that points at an image ("(above)", "pictured").

8. **Look at every page image** in `WORKINGS/<slug>/previews/`. This is not optional, and a gate PASS is not a substitute for it. Check: the header on every page; nothing cut at the foot; images sharp, in proportion and beside the text that discusses them; no heading alone at the foot of a page; captions with their images; no page ending far short of the foot except the last.
   - A page that ends well short because the next image did not fit: the build names the image. Move its line a paragraph or two earlier *within its section*, or give it `{h=…}`, and rebuild.
   - Repeat until every page is right. Say in the handover what you moved and why.

9. **Deliver** the PDF and the HTML, and hand over:
   - the two paths, the page count (tell Dan in plain words: "your PDF is in the PDFs folder inside your report folder");
   - what you decided: where each image went, the tag, the date, every pull quote and key figure (quoted), which passages became cards, panels or boxes, contact box on or off, the disclaimer;
   - **everything in Dan's text you left as it is but a person should see**: every placeholder, every reference to an image that was not supplied, every place the text and an image disagree (quote both), anything visibly wrong in a supplied image;
   - that the text check passed (source and output word counts), and what the previews were rendered from.

## Things to check rather than assume

**The text check is only as good as its source.** It compares against `WORKINGS/<slug>/source/`. If that file is not Dan's original (a copy you tidied, a re-typed version), the check proves nothing. Never edit it.

**A suppression is a decision, not a workaround.** `Removed:` exists for notes to the designer. If you are reaching for it to get a sentence past the text check, the sentence should not have changed.

**Word files lie about structure.** Headings are often just bold lines, whole documents sit inside layout tables, and a paragraph can begin with "+ 44" or "- 5%" that markdown would read as a bullet. Ingest escapes those (`\+ 44`) and reads layout tables as text; check its heading candidates rather than trusting its first guess at the title.

**Chrome flags.** Do not add `--user-data-dir`: a fresh profile made headless Chrome hang without returning on the machine this was built on.
