"""Original test content only; no downloaded books. Generates EPUB and image-only PDF.

Pass --font /path/to/Japanese.ttf on other operating systems to recreate the PDF.
The committed sample files are ready to use without local fonts.
"""
from pathlib import Path
from io import BytesIO
import argparse
import zipfile
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
TEXT = [
    ["吾輩は猫である。名前はまだない。", "今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。", "静かな午後、書物を開いて一文字ずつ確かめた。"],
    ["朝の光が窓から差し込む。", "東京の空を見上げ、明日の旅に思いを巡らせた。", "校正は急がず、原本と照らしながら進める。"]
]

def generate_epub():
    SAMPLES.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (180, 120), "#edf0df")
    d = ImageDraw.Draw(image)
    d.ellipse((60, 20, 120, 80), fill="#8a9c62")
    d.line((90, 70, 90, 110), fill="#54683c", width=4)
    buffer = BytesIO(); image.save(buffer, "PNG")
    entries = {
      "META-INF/container.xml": '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
      "EPUB/package.opf": '''<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:uuid:2e744e60-2a85-4aee-8c65-9134db7d8140</dc:identifier><dc:title>文字をたどる — 校正サンプル</dc:title><dc:language>ja</dc:language><dc:creator>EPUB Proofreader テスト制作</dc:creator><meta property="dcterms:modified">2026-10-16T00:00:00Z</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/><item id="c2" href="chapter2.xhtml" media-type="application/xhtml+xml"/><item id="css" href="style.css" media-type="text/css"/><item id="img" href="leaf.png" media-type="image/png"/></manifest><spine page-progression-direction="rtl"><itemref idref="c1"/><itemref idref="c2"/></spine></package>''',
      "EPUB/nav.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja" xml:lang="ja"><head><title>目次</title></head><body><nav epub:type="toc"><h1>目次</h1><ol><li><a href="chapter1.xhtml">第一章　午後の庭</a></li><li><a href="chapter2.xhtml">第二章　旅の朝</a></li></ol></nav></body></html>',
      "EPUB/style.css": 'body { writing-mode: vertical-rl; -epub-writing-mode: vertical-rl; font-family: serif; line-height: 2; } rt { font-size: .5em; } img { max-width: 180px; }',
      "EPUB/leaf.png": buffer.getvalue(),
    }
    bodies = [
      '<p id="original-p1"><ruby>吾輩<rp>（</rp><rt>わがはい</rt><rp>）</rp></ruby>は猫である。名前はまだない。</p><p>今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。</p><p>静かな午後、<em>書物</em>を開いて一文字ずつ確かめた。</p><figure><img src="leaf.png" alt="テスト用の葉の絵"/><figcaption>庭の若葉</figcaption></figure>',
      '<p>朝の光が窓から差し込む。</p><p><ruby><rb>東</rb><rt>とう</rt><rb>京</rb><rt>きょう</rt></ruby>の空を見上げ、明日の旅に思いを巡らせた。</p><p><ruby><rb>校正</rb><rt>こうせい</rt></ruby>は急がず、原本と照らしながら進める。</p>'
    ]
    for i, body in enumerate(bodies, 1):
        title = ['第一章　午後の庭', '第二章　旅の朝'][i-1]
        entries[f"EPUB/chapter{i}.xhtml"] = f'<html xmlns="http://www.w3.org/1999/xhtml" lang="ja" xml:lang="ja"><head><title>{title}</title><link rel="stylesheet" href="style.css"/></head><body><section><h1>{title}</h1>{body}</section></body></html>'
    with zipfile.ZipFile(SAMPLES / "book.epub", "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for path, data in entries.items(): archive.writestr(path, data, compress_type=zipfile.ZIP_DEFLATED)

def generate_pdf(font_path):
    font = ImageFont.truetype(str(font_path), 27)
    small = ImageFont.truetype(str(font_path), 15)
    pages = []
    for i, paragraphs in enumerate(TEXT, 1):
        page = Image.new("RGB", (900, 1200), "#fffcf3")
        draw = ImageDraw.Draw(page)
        draw.text((90, 70), f"校正テスト用原本　{i}", font=small, fill="#5d6456")
        x = 760
        for text in paragraphs:
            # Original image deliberately has the correct character 天気.
            text = text.replace('天汽', '天気')
            y = 170
            for char in text:
                draw.text((x, y), char, font=font, fill="#282c24")
                y += 36
                if y > 1000: x -= 60; y = 170
            x -= 95
        draw.text((440, 1120), str(i), font=small, fill="#777b6e")
        pages.append(page)
    pages[0].save(SAMPLES / "original.pdf", save_all=True, append_images=pages[1:], resolution=110)

def generate_decoder_regression_pdf():
    """Six original pages: JPEG first, then CCITT (same switch as scanned books)."""
    SAMPLES.mkdir(parents=True, exist_ok=True)
    pages = []
    for index in range(1, 7):
        page = Image.new("RGB" if index <= 3 else "1", (600, 800), "white")
        draw = ImageDraw.Draw(page)
        draw.text((60, 60), f"PDF DECODER TEST - PAGE {index}", fill="black", font_size=28)
        for stripe in range(index):
            draw.rectangle((60, 150 + stripe * 65, 500, 175 + stripe * 65), fill="black")
        pages.append(page)
    pages[0].save(SAMPLES / "decoder-regression.pdf", save_all=True, append_images=pages[1:], resolution=96)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--font', type=Path, default=Path('/System/Library/Fonts/ヒラギノ明朝 ProN.ttc'))
    parser.add_argument('--epub-only', action='store_true')
    args = parser.parse_args()
    generate_epub()
    generate_decoder_regression_pdf()
    if not args.epub_only:
        if not args.font.exists(): parser.error('日本語フォントを --font で指定してください。EPUBは生成済みです。')
        generate_pdf(args.font)
