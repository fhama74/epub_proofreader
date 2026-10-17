from pathlib import Path
import zipfile
import pytest
from epub_proofreader.epub import Book
from test_epub import changed,SAMPLES

@pytest.mark.parametrize('style,inline,expected',[
 ('body {writing-mode: horizontal-tb}', '', 'horizontal-tb'),
 ('body {writing-mode: vertical-rl}', '', 'vertical-rl'),
 ('html {-epub-writing-mode: vertical-lr}', '', 'vertical-lr'),
 ('body {-webkit-writing-mode:tb-rl}', '', 'vertical-rl'),
 ('body {writing-mode:vertical-rl} body {writing-mode:horizontal-tb}', '', 'horizontal-tb'),
 ('body {writing-mode:vertical-rl!important}', 'writing-mode:horizontal-tb', 'vertical-rl'),
 ('body {writing-mode:vertical-rl}', 'writing-mode:horizontal-tb', 'horizontal-tb'),
 ('/* writing-mode:vertical-rl */ .unused {writing-mode:vertical-rl}', '', 'horizontal-tb'),
 ('@media print {body {writing-mode:vertical-rl}} @media screen {body {writing-mode:horizontal-tb}}', '', 'horizontal-tb'),
 ('p {writing-mode:vertical-rl}', '', 'vertical-rl'),
 ('body.reader {writing-mode:vertical-rl}', '', 'vertical-rl'),
])
def test_css_cascade_and_default_are_not_spine_direction(style,inline,expected):
 with zipfile.ZipFile(SAMPLES/'book.epub') as z:chapter=z.read('EPUB/chapter1.xhtml').decode()
 chapter=chapter.replace('<body>',f'<body class="reader" style="{inline}">')
 model=Book(changed({'EPUB/style.css':style.encode(),'EPUB/chapter1.xhtml':chapter.encode()}))
 assert model.direction=='rtl'
 assert model.chapters[0]['writing_mode']==expected

def test_local_import_and_chapter_overrides_ignore_remote_and_cyclic_imports():
 with zipfile.ZipFile(SAMPLES/'book.epub') as z:chapter=z.read('EPUB/chapter1.xhtml').decode()
 chapter=chapter.replace('</head>','<style>body {writing-mode:horizontal-tb}</style></head>')
 data=changed({'EPUB/style.css':b'@import "layout.css"; @import url("https://example.com/remote.css");',
  'EPUB/layout.css':b'@import "style.css"; body {writing-mode:vertical-rl}', 'EPUB/chapter1.xhtml':chapter.encode()})
 model=Book(data)
 assert model.chapters[0]['writing_mode']=='horizontal-tb'
 assert model.chapters[1]['writing_mode']=='vertical-rl'
