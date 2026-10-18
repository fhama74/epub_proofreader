"""Read EPUB without extracting ZIP entries or changing any source bytes.

Paragraph locators refer to the original XML tree. Preview is a separate,
allowlisted serialization and must NEVER be used as an export source.
"""
from __future__ import annotations
import copy
import hashlib
import io
import posixpath
import stat
import zipfile
from urllib.parse import unquote, urlsplit, quote
from lxml import etree
from .segments import describe
from .writing_mode import chapter_mode

MAX_UPLOAD = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_ENTRY = 32 * 1024 * 1024
NS = {"opf": "http://www.idpf.org/2007/opf", "x": "http://www.w3.org/1999/xhtml", "dc": "http://purl.org/dc/elements/1.1/"}

class EpubError(ValueError):
    pass

def local(element):
    return etree.QName(element).localname if isinstance(element.tag, str) else ""

class NoExternalXML(etree.Resolver):
    def resolve(self, url, public_id, context):
        # no_network alone does not block local filesystem/catalog access.
        raise EpubError("XMLの外部DTD・実体ファイルは読み込めません。")


def xml(data: bytes, source_name: str = "XML"):
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    parser.resolvers.add(NoExternalXML())
    try:
        tree = etree.fromstring(data, parser)
        # A DOCTYPE (notably EPUB's <!DOCTYPE html>) is not an entity.
        # Keep the declaration in the immutable original, without loading its DTD.
        dtd = tree.getroottree().docinfo.internalDTD
        if (dtd is not None and any(dtd.iterentities())) or any(isinstance(e, etree._Entity) for e in tree.iter()):
            raise EpubError("独自の実体宣言・未解決の実体参照を含むXMLは安全のため読み込めません。")
        return tree
    except etree.XMLSyntaxError as exc:
        issue = next((entry for entry in parser.error_log if entry.level >= etree.ErrorLevels.ERROR), None)
        line, column = (issue.line, issue.column) if issue is not None else exc.position
        message = issue.message if issue is not None else exc.msg
        hint = " 数値文字参照（&#1234; / &#xABCD;）の書式を確認してください。" if "CharRef" in message else ""
        raise EpubError(f"XMLが不正です: {source_name}（{line}行、{column}列）: {message}.{hint} 元データは変更していません。") from exc

def safe_name(name: str):
    if not name or name.startswith("/") or "\\" in name or "\x00" in name or ":" in name or any(p == ".." for p in name.split("/")):
        raise EpubError("ZIP内に安全でないパスがあります。")
    return name

def reference(base: str, href: str):
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or href.startswith("/") or "\\" in href:
        raise EpubError("外部参照または絶対パスは利用できません。")
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(parts.path))) if parts.path else base
    return safe_name(path)

class Book:
    def __init__(self, data: bytes, *, repair_import=False):
        from .working import WorkingFiles
        if isinstance(data,WorkingFiles):
            self.__dict__.update(data.model().__dict__)
            return
        if len(data) > MAX_UPLOAD:
            raise EpubError("EPUBは64 MiB以下にしてください。")
        self.repair_import = repair_import
        self.import_repairs = []
        self.original = data
        self.fingerprint = hashlib.sha256(data).hexdigest()
        self.warnings = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if not entries or len(entries) > 10000:
                    raise EpubError("ZIPの項目数が不正です。")
                seen, total = set(), 0
                for info in entries:
                    safe_name(info.filename)
                    if info.filename in seen:
                        raise EpubError("ZIPに重複ファイルがあります。")
                    seen.add(info.filename)
                    total += info.file_size
                    if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                        raise EpubError("暗号化ZIP・シンボリックリンクは利用できません。")
                    if info.file_size > MAX_ENTRY or total > MAX_EXPANDED or info.file_size > max(info.compress_size, 1) * 250:
                        raise EpubError("ZIPの展開サイズ・圧縮率が上限を超えています。")
                if archive.read("mimetype") != b"application/epub+zip":
                    raise EpubError("mimetypeがEPUB形式ではありません。")
                if entries[0].filename != "mimetype" or entries[0].compress_type != zipfile.ZIP_STORED:
                    self.warnings.append("mimetypeはZIPの先頭・無圧縮ではありません。元データは修復していません。")
                self.files = {i.filename: archive.read(i) for i in entries if not i.is_dir()}
        except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError, OSError) as exc:
            raise EpubError("EPUBのZIP構造または必須ファイルが不正です。") from exc
        if "META-INF/encryption.xml" in self.files:
            raise EpubError("暗号化・難読化リソースを含むEPUBはPhase 1では未対応です。")
        container = self.read_xml("META-INF/container.xml")
        roots = container.xpath('//*[local-name()="rootfile"]/@full-path')
        if not roots:
            raise EpubError("OPFファイルが見つかりません。")
        self.opf_path = safe_name(roots[0])
        opf = self.read_xml(self.opf_path)
        if not opf.get("version", "").startswith("3"):
            self.warnings.append("EPUB 3以外の書籍です。表示の互換性は保証しません。")
        self.metadata = {}
        for element in opf.xpath("opf:metadata/*", namespaces=NS):
            self.metadata.setdefault(local(element), []).append("".join(element.itertext()))
        self.manifest = []
        ids = {}
        for item in opf.xpath("opf:manifest/opf:item", namespaces=NS):
            item_id = item.get("id")
            if not item_id or item_id in ids:
                raise EpubError("manifestのIDが欠落または重複しています。")
            record = {"id": item_id, "path": reference(self.opf_path, item.get("href", "")), "media_type": item.get("media-type", ""), "properties": item.get("properties", "")}
            self.get(record["path"])
            ids[item_id] = record
            self.manifest.append(record)
        spine = opf.find("opf:spine", NS)
        if spine is None:
            raise EpubError("spineがありません。")
        self.direction = spine.get("page-progression-direction", "default")
        self.spine = []
        self.chapters = []
        self.trees = {}
        for item in self.manifest:
            if item["media_type"] == "application/xhtml+xml":
                self.trees[item["path"]] = self.read_xml(item["path"])
        for itemref in spine:
            ident = itemref.get("idref")
            if ident not in ids:
                raise EpubError("spineが存在しないmanifest項目を参照しています。")
            item = ids[ident]
            self.spine.append({"idref": ident, "linear": itemref.get("linear", "yes")})
            if item["media_type"] != "application/xhtml+xml":
                self.warnings.append(f"spine内の非XHTML項目は表示対象外です: {item['path']}")
                continue
            self.chapters.append(self.analyze_chapter(item['path'],len(self.chapters)+1))
        self.refresh_units()
        if not self.chapters:
            raise EpubError("表示可能なXHTML章がありません。")
        self.toc = []
        for item in self.manifest:
            if "nav" in item["properties"].split() and item["path"] in self.trees:
                for link in self.trees[item["path"]].xpath('//x:nav[@*[local-name()="type"]="toc"]//x:a', namespaces=NS):
                    try:
                        path = reference(item["path"], link.get("href", ""))
                        self.toc.append({"label": "".join(link.itertext()), "path": path, "fragment": urlsplit(link.get("href", "")).fragment})
                    except EpubError:
                        self.warnings.append("目次内の外部参照を表示対象から除外しました。")
        if not self.toc:
            self.warnings.append("EPUB 3の目次が見つかりません。章一覧で移動できます。")
        if any(not r["editable"] for c in self.chapters for p in c["paragraphs"] for r in p["rubies"]):
            self.warnings.append("複雑なルビを検出しました。構造を保持して表示します。専用編集はできません。前後の本文は編集できます。")
        # Preview never uses external references, scripts or source CSS.
        if any(t.xpath('//*[local-name()="script"]') for t in self.trees.values()):
            self.warnings.append("スクリプトはプレビューでは無効です。")

    def analyze_chapter(self,path,number):
        item={"path":path}
        tree = self.trees[item["path"]]
        if tree.find("x:body", NS) is None:
            raise EpubError("XHTMLに名前空間付きbodyがありません。")
        elements = tree.xpath("//x:p | //x:li[not(.//x:p)] | //x:blockquote[not(.//x:p)]", namespaces=NS)
        paragraphs = []
        for index, element in enumerate(elements, 1):
            rubies = []
            for ruby in element.xpath(".//x:ruby", namespaces=NS):
                rt = ruby.xpath(".//x:rt", namespaces=NS)
                simple = simple_ruby(ruby)
                rubies.append({"xpath": tree.getroottree().getpath(ruby), "base": base_text(ruby), "readings": ["".join(r.itertext()) for r in rt], "editable": simple, "original_xml": etree.tostring(ruby, encoding="unicode", with_tail=False)})
            paragraphs.append({"id": f"chapter{number:04d}-p{index:05d}", "xpath": tree.getroottree().getpath(element), "text": base_text(element), "original_xml": etree.tostring(element, encoding="unicode", with_tail=False), "rubies": rubies, "status": "unchecked", "revision": 0})
        for paragraph, element in zip(paragraphs,elements):
            paragraph.update(describe(element)[0])
        headings=[]
        for index, element in enumerate(tree.xpath('//x:body//x:h1 | //x:body//x:h2 | //x:body//x:h3 | //x:body//x:h4 | //x:body//x:h5 | //x:body//x:h6', namespaces=NS),1):
            following=next((i for i,p in enumerate(elements) if element in p.xpath('preceding::*')),len(elements))
            rubies=[]
            for ruby in element.xpath('.//x:ruby',namespaces=NS):
                rubies.append({'xpath':tree.getroottree().getpath(ruby),'base':base_text(ruby),'readings':[''.join(rt.itertext()) for rt in ruby.xpath('.//x:rt',namespaces=NS)],'editable':simple_ruby(ruby),'original_xml':etree.tostring(ruby,encoding='unicode',with_tail=False)})
            headings.append({'id':f'chapter{number:04d}-h{index:05d}','xpath':tree.getroottree().getpath(element),'text':base_text(element),'original_xml':etree.tostring(element,encoding='unicode',with_tail=False),'rubies':rubies,'status':'unchecked','revision':0,'next_paragraph_index':following,**describe(element)[0]})
        titles=tree.xpath('//x:body//x:h1 | //x:body//x:h2',namespaces=NS)
        title=base_text(titles[0]) if titles else ''.join(tree.xpath('//x:title/text()',namespaces=NS))
        return {"id": f"chapter{number:04d}", "path": item["path"], "title": title.strip() or f"第{number}章", "paragraphs": paragraphs, "headings": headings, "writing_mode": chapter_mode(tree,item["path"],self.files,reference)}

    def read_xml(self, path):
        data=self.get(path)
        try:return xml(data,path)
        except EpubError as error:
            if not self.repair_import or not isinstance(error.__cause__,etree.XMLSyntaxError) or 'CharRef' not in str(error):raise
            from .import_repair import repair_numeric_references
            repaired,records=repair_numeric_references(data,path)
            if not records:raise
            # Never use XML recovery mode; any remaining error rejects the import.
            tree=xml(repaired,path)
            self.files[path]=repaired
            self.import_repairs.extend(records)
            self.warnings.append(f'読み込み時に文字参照の破損を{len(records)}箇所修復しました: {path}。原本は変更していません。')
            return tree

    @property
    def normalized(self):
        if not self.import_repairs:return self.original
        if not hasattr(self,'_normalized'):
            from .editing import repack
            self._normalized=repack(self.original,{r['path']:self.files[r['path']] for r in self.import_repairs})
        return self._normalized

    def updated(self,replacements):
        from .working import WorkingFiles
        result=copy.copy(self);result.files={**self.files,**replacements};result.trees=dict(self.trees);result.chapters=list(self.chapters)
        if any(len(v)>MAX_ENTRY for v in replacements.values()) or sum(map(len,result.files.values()))>MAX_EXPANDED:raise EpubError('編集後のXHTML・書籍サイズが上限を超えています。')
        for path,data in replacements.items():
            if path not in self.trees:raise EpubError('変更先は既存のXHTMLに限ります。')
            result.trees[path]=xml(data,path)
        changed=[]
        for index,chapter in enumerate(self.chapters):
            if chapter['path'] in replacements:
                result.chapters[index]=result.analyze_chapter(chapter['path'],index+1);changed.append(result.chapters[index])
        result.refresh_units(changed)
        result.original=WorkingFiles.merge(self.original,replacements)
        result.fingerprint=result.original.fingerprint
        # Chapter text edits may change navigation labels; update the small TOC only.
        result.toc=[]
        for item in result.manifest:
            if 'nav' in item['properties'].split() and item['path'] in result.trees:
                for link in result.trees[item['path']].xpath('//x:nav[@*[local-name()="type"]="toc"]//x:a',namespaces=NS):
                    try:result.toc.append({'label':''.join(link.itertext()),'path':reference(item['path'],link.get('href','')),'fragment':urlsplit(link.get('href','')).fragment})
                    except EpubError:pass
        return result

    def apply_ids(self,mapping):
        if not mapping:return self
        result=copy.copy(self);result.chapters=list(self.chapters);changed=[]
        for index,chapter in enumerate(self.chapters):
            ids=mapping.get(chapter['id'])
            heading_ids=mapping.get(chapter['id']+':headings')
            if ids is not None or heading_ids is not None:
                if ids is None:ids=[p['id'] for p in chapter['paragraphs']]
                if len(ids)!=len(chapter['paragraphs']) or len(set(ids))!=len(ids):raise EpubError('段落IDと章の構造が一致しません。')
                chapter=copy.deepcopy(chapter);result.chapters[index]=chapter;changed.append(chapter)
                for paragraph,ident in zip(chapter['paragraphs'],ids):paragraph['id']=ident
                if heading_ids is not None:
                    if len(heading_ids)!=len(chapter['headings']) or len(set(heading_ids))!=len(heading_ids):raise EpubError('見出しIDと章の構造が一致しません。')
                    for heading,ident in zip(chapter['headings'],heading_ids):heading['id']=ident
        all_ids=[p['id'] for c in result.chapters for p in [*c['paragraphs'],*c['headings']]]
        if len(all_ids)!=len(set(all_ids)):raise EpubError('段落・見出しのIDが重複しています。')
        result.refresh_units(changed)
        return result

    def refresh_units(self,chapters=None):
        for chapter in self.chapters if chapters is None else chapters:
            units=[]
            for index,p in enumerate(chapter['paragraphs']):
                common={'paragraph_id':p['id'],'paragraph_index':index}
                if p['unit_mode']=='sentence' and p['sentences']:
                    units.extend({**common,'kind':'sentence','sentence_index':sentence['index'],'text':sentence['text']} for sentence in p['sentences'])
                else:units.append({**common,'kind':'paragraph','sentence_index':None,'text':p['text']})
            chapter.update(proof_units=units,paragraph_count=len(chapter['paragraphs']),sentence_count=sum(len(p['sentences']) for p in chapter['paragraphs']),long_paragraph_count=sum(p['unit_mode']=='sentence' for p in chapter['paragraphs']))

    def get(self, path):
        try:
            return self.files[path]
        except KeyError as exc:
            raise EpubError(f"参照ファイルがありません: {path}") from exc

    def summary(self):
        return {"fingerprint": self.fingerprint, "metadata": self.metadata, "manifest": self.manifest, "spine": self.spine, "opf_path": self.opf_path, "direction": self.direction, "chapters": self.chapters, "toc": self.toc, "warnings": self.warnings, "file_count": len(self.files)}

    def preview(self, chapter_id, book_id):
        chapter = next((c for c in self.chapters if c["id"] == chapter_id), None)
        if chapter is None:
            raise EpubError("章がありません。")
        source = self.trees[chapter["path"]]
        locators = {p["xpath"]: p["id"] for p in [*chapter["paragraphs"],*chapter.get("headings",[])]}
        ruby_locators = {r["xpath"]: (p["id"], index) for p in [*chapter["paragraphs"],*chapter.get("headings",[])] for index,r in enumerate(p["rubies"])}
        text_marks={}; ruby_marks={}
        nodes_by_path={source.getroottree().getpath(e):e for e in source.iter() if isinstance(e.tag,str)}
        for p in [*chapter['paragraphs'],*chapter.get('headings',[])]:
            element=nodes_by_path[p['xpath']]
            _,slots,rubies=describe(element)
            ruby_nodes={ruby for ruby,_,_ in rubies}
            for node,field,start,end in slots:
                # Keep native ruby content intact; mark the entire ruby instead.
                inside=any(ancestor in ruby_nodes for ancestor in node.iterancestors()) or node in ruby_nodes and field=='text'
                if inside:continue
                chunks=[]
                value=getattr(node,field) or ''
                for sentence in p['sentences']:
                    a=max(start,sentence['start']);b=min(end,sentence['end'])
                    if b>a:chunks.append((p['id'],sentence['index'],value[a-start:b-start]))
                if chunks:text_marks[(source.getroottree().getpath(node),field)]=chunks
            for ruby,start,end in rubies:
                sentence=next((part for part in p['sentences'] if part['start']<=start<part['end']),None)
                if sentence:ruby_marks[source.getroottree().getpath(ruby)]=(p['id'],sentence['index'])
        def append_text(parent,value,node,field):
            chunks=text_marks.get((source.getroottree().getpath(node),field))
            if chunks:
                for paragraph_id,index,text in chunks:
                    span=etree.SubElement(parent,'span',{'data-sentence-paragraph':paragraph_id,'data-sentence':str(index)})
                    span.text=text
            elif value:
                if len(parent):parent[-1].tail=(parent[-1].tail or '')+value
                else:parent.text=(parent.text or '')+value
        allowed = {"body", "div", "section", "article", "p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "ruby", "rb", "rt", "rp", "rtc", "em", "strong", "b", "i", "br", "hr", "a", "img", "figure", "figcaption", "blockquote", "ul", "ol", "li", "table", "tbody", "tr", "td", "th", "sup", "sub"}
        def clean(node):
            tag = local(node)
            if tag not in allowed:
                return None
            result = etree.Element("div" if tag == "body" else tag)
            append_text(result,node.text,node,'text')
            locator = source.getroottree().getpath(node)
            if locator in locators:
                result.set("data-paragraph", locators[locator])
                result.set("tabindex", "0")
            if locator in ruby_marks:
                paragraph_id,index=ruby_marks[locator]
                result.set('data-sentence-paragraph',paragraph_id)
                result.set('data-sentence',str(index))
            if locator in ruby_locators:
                paragraph_id, index = ruby_locators[locator]
                result.set("data-ruby", str(index))
                result.set("data-ruby-paragraph", paragraph_id)
                result.set("tabindex", "0")
            if tag == "img":
                try:
                    path = reference(chapter["path"], node.get("src", ""))
                    item = next((i for i in self.manifest if i["path"] == path), None)
                    if item and item["media_type"] in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                        result.set("src", f"/api/books/{book_id}/assets/{quote(path, safe='/')}")
                        result.set("alt", node.get("alt", ""))
                except EpubError:
                    result.set("alt", "外部画像は表示しません")
            for child in node:
                child_result = clean(child)
                if child_result is not None:
                    result.append(child_result)
                append_text(result,child.tail,child,'tail')
            return result
        body = source.find("x:body", NS)
        return etree.tostring(clean(body), encoding="unicode", method="html")

def simple_ruby(ruby):
    children = list(ruby)
    rt = ruby.findall('x:rt', NS)
    rb = ruby.findall('x:rb', NS)
    simple = (len(rt) == 1 and len(rt[0]) == 0 and len(rb) <= 1 and
              all(local(c) in {'rb','rt','rp'} and len(c) == 0 for c in children) and
              all(not (c.tail or '').strip() for c in children))
    if rb:
        simple = simple and not (ruby.text or '').strip() and children.index(rb[0]) < children.index(rt[0])
    return simple

def base_text(element, strip=True):
    clone = copy.deepcopy(element)
    for child in list(clone.iter()):
        if local(child) in {"rt", "rp", "rtc"}:
            parent = child.getparent()
            if parent is not None:
                tail = child.tail or ""
                prev = child.getprevious()
                if prev is None:
                    parent.text = (parent.text or "") + tail
                else:
                    prev.tail = (prev.tail or "") + tail
                parent.remove(child)
    result = "".join(clone.itertext())
    return result.strip() if strip else result
