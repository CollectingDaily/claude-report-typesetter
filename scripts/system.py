"""What differs between macOS and Windows, in one place.

Everything else in this skill is plain Python and runs the same on both. The
only outside programs it needs are a Chromium browser (Chrome, Edge, Brave or
Chromium) and, for a few rare input formats, LibreOffice. The macOS tools it
used to rely on (sips, textutil, pdftoppm) are now optional extras: used when
present, never required.
"""
import os
import pathlib
import shutil
import subprocess
import sys

IS_WIN = sys.platform.startswith('win')
IS_MAC = sys.platform == 'darwin'


def utf8_output():
    """Windows sends a script's output through the old code page unless told
    otherwise, and a £ or a curly quote in a report would then crash the print."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        except (AttributeError, ValueError):
            pass


def _win_dirs():
    return [os.environ.get(k) for k in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA') if os.environ.get(k)]


def find_chrome():
    """A Chromium browser to lay out and print the pages. Chrome first, then Edge,
    which every Windows PC has, then Brave and Chromium."""
    cands = [os.environ.get('CHROME')] if os.environ.get('CHROME') else []
    if IS_WIN:
        for base in _win_dirs():
            cands += [os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                      os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                      os.path.join(base, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
                      os.path.join(base, 'Chromium', 'Application', 'chrome.exe')]
    elif IS_MAC:
        for base in ('/Applications', str(pathlib.Path.home() / 'Applications')):
            cands += [base + '/Google Chrome.app/Contents/MacOS/Google Chrome',
                      base + '/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
                      base + '/Brave Browser.app/Contents/MacOS/Brave Browser',
                      base + '/Chromium.app/Contents/MacOS/Chromium']
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge', 'msedge', 'chrome'):
        cands.append(shutil.which(name) or '')
    for c in cands:
        if c and os.path.isfile(c):
            return c
    sys.exit('No Chrome or Edge found. The PDF is laid out and printed by a Chromium browser. '
             'Install Google Chrome, or set CHROME to the path of chrome.exe or msedge.exe.')


def find_soffice():
    """LibreOffice, for the rare input it is the only thing that reads (.doc, .rtf)."""
    cands = []
    if IS_WIN:
        for base in _win_dirs():
            cands.append(os.path.join(base, 'LibreOffice', 'program', 'soffice.exe'))
    elif IS_MAC:
        cands.append('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    cands += [shutil.which('soffice') or '', shutil.which('libreoffice') or '']
    return next((c for c in cands if c and os.path.isfile(c)), None)


def tool(name):
    """An optional helper (sips, textutil, pdftoppm): its path, or None."""
    return shutil.which(name)


def run(args, **kw):
    """subprocess.run with text decoded as UTF-8 on every system."""
    kw.setdefault('capture_output', True)
    return subprocess.run(args, text=True, encoding='utf-8', errors='replace', **kw)


def file_url(p):
    """A file:// address that works with a Windows drive letter as well."""
    return pathlib.Path(p).resolve().as_uri()


def python_cmd():
    """How to name this Python in an instruction a person or agent will run."""
    return 'python' if IS_WIN else 'python3'
