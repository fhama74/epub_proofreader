import {clearAITextMarks,markAIText} from './aiTextMarks';
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {Chapter,ProofUnit} from './types';
import {bookmarkElement,type ReaderBookmark} from './readerBookmark';
import type {Candidate} from './aiTypes';
const style=`html{height:100%;overflow:hidden;background:#fffef9;color:#24342d}body{margin:0;padding:0;height:100%;width:100%;box-sizing:border-box;font-family:'Yu Mincho','Hiragino Mincho ProN',serif;line-height:2.3;letter-spacing:.05em}h1,h2{font-weight:500;line-height:1.8;margin:0 0 0 2em}p{padding:.6em .45em;margin:0 0 0 1.5em;cursor:pointer;border-radius:3px}ruby{cursor:pointer}ruby:hover{background:#dae8c3}rt{font-size:.5em}rp{display:none}img{max-height:65vh;max-width:220px;object-fit:contain}.selected{background:#e7eee2;outline:1px solid #afbf9e}.sentence-selected{background:#dceabf;outline:1px solid #afc383}::highlight(ai-unreviewed){color:#b43131;text-decoration:underline;text-decoration-color:#b43131}.ai-unreviewed-text{color:#b43131}.ai-unreviewed-text rt,.ai-unreviewed-text rp,.ai-unreviewed-text rtc{color:#24342d}::highlight(ai-candidate){background:#ffe18b}[data-paragraph]:focus{outline:2px solid #668352}`;
function scrollRoot(doc:Document|null|undefined){return doc?.getElementById('epub-content');}
export default function EpubPane({html,chapter,unit,fontSize,onChoose,onRuby,onKey,initialScroll,onScroll,aiHighlight,readingOnly=false,pendingCandidates=[],readerNavigation=false,onVisibleUnit,onBookmark,restoreBookmark=null,rightToLeft=false,visible=true,initialLanding=null,hasPreviousChapter=false,hasNextChapter=false,onChapterTurn}:{onBookmark?:(bookmark:ReaderBookmark)=>void;restoreBookmark?:ReaderBookmark|null;rightToLeft?:boolean;visible?:boolean;initialLanding?:'start'|'end'|null;hasPreviousChapter?:boolean;hasNextChapter?:boolean;onChapterTurn?:(step:number)=>void;onVisibleUnit?:(paragraphId:string,sentenceIndex?:number)=>void;readerNavigation?:boolean;pendingCandidates?:Candidate[];readingOnly?:boolean;aiHighlight?:Candidate|null;initialScroll?:number|null;onScroll?:(position:number)=>void;html:string;chapter?:Chapter;unit?:ProofUnit;fontSize:number;onChoose:(paragraphId:string,sentenceIndex?:number)=>void;onRuby:(paragraphId:string,rubyIndex:number,sentenceIndex?:number)=>void;onKey:(e:KeyboardEvent)=>void}){
  const mode=chapter?.writing_mode || 'horizontal-tb';const vertical=mode!=='horizontal-tb';
  const callbacks=useRef({onChoose,onRuby,onKey,onScroll,initialScroll,onVisibleUnit,onBookmark,visible});callbacks.current={onChoose,onRuby,onKey,onScroll,initialScroll,onVisibleUnit,onBookmark,visible};
  const restore=useRef(restoreBookmark);
  const landing=useRef(initialLanding);const lastUnit=useRef(unit);
  const manualPage=useRef(false);const holdPosition=useRef(false);
  const frame=useRef<HTMLIFrameElement>(null);const cleanup=useRef<()=>void>(()=>{});const sign=useRef(-1);
  const [pages,setPages]=useState({current:1,total:1});
  const targets=useRef<number[]>([0]);
  const source=useMemo(()=>`<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; img-src 'self'; style-src 'unsafe-inline';"><style>${style}#epub-content{writing-mode:${mode};width:100vw;height:100vh;overflow:auto;overscroll-behavior:contain;contain:layout paint;transform:translateZ(0);box-sizing:border-box;padding:16px 22px}body{font-size:${fontSize}px}${vertical?'':'h1,h2{margin:0 0 1em}p{margin:0 0 1.2em}img{max-width:100%;max-height:65vh}'}</style></head><body><div id="epub-content">${html}</div></body></html>`,[html,fontSize,mode,vertical]);
  const measure=useCallback(()=>{
    const root=scrollRoot(frame.current?.contentDocument);
    const box=frame.current?.getBoundingClientRect();
    if(!root || !box || box.width<40 || box.height<40 || root.clientWidth<40 || root.clientHeight<40)return;
    const viewport=vertical?root.clientWidth:root.clientHeight;const extent=vertical?root.scrollWidth:root.scrollHeight;
    const max=Math.max(0,extent-viewport);const count=Math.max(1,Math.ceil((extent-1)/viewport));
    targets.current=Array.from({length:count},(_,index)=>Math.min(index*viewport,max));
    const position=vertical?Math.abs(root.scrollLeft):root.scrollTop;
    const selected=targets.current.reduce((best,value,index)=>Math.abs(value-position)<Math.abs(targets.current[best]-position)?index:best,0);
    setPages({current:selected+1,total:count});
  },[vertical]);
  const applyLanding=()=>{const root=scrollRoot(frame.current?.contentDocument);if(!root || !landing.current)return;const position=landing.current==='end'?Math.max(0,vertical?root.scrollWidth-root.clientWidth:root.scrollHeight-root.clientHeight):0;if(vertical)root.scrollLeft=sign.current*position;else root.scrollTop=position;measure();};
  function capture(element?:Element|null){
    const doc=frame.current?.contentDocument,root=scrollRoot(doc),box=frame.current?.getBoundingClientRect();if(!doc || !root || !chapter || !callbacks.current.visible || !box || box.width<40 || box.height<40)return;
    const visible=(el:Element)=>Array.from(el.getClientRects()).some(r=>r.width>0 && r.height>0 && r.right>16 && r.left<root.clientWidth-16 && r.bottom>16 && r.top<root.clientHeight-16);
    const el=element || Array.from(doc.querySelectorAll('[data-sentence],[data-paragraph]')).find(visible);if(!el)return;
    const pid=el.getAttribute('data-sentence-paragraph') || el.getAttribute('data-paragraph');if(!pid)return;const bookmark:ReaderBookmark={chapterId:chapter.id,paragraphId:pid,sentenceIndex:el.hasAttribute('data-sentence')?Number(el.getAttribute('data-sentence')):undefined,offset:0,scroll:vertical?root.scrollLeft:root.scrollTop};const canonical=bookmarkElement(doc,bookmark) || el;const rect=canonical.getClientRects()[0];if(!rect)return;bookmark.offset=vertical?rect.right-root.clientWidth:rect.top;callbacks.current.onBookmark?.(bookmark);
  }
  function restoreReader(){
    const doc=frame.current?.contentDocument,root=scrollRoot(doc),box=frame.current?.getBoundingClientRect(),saved=restore.current;
    if(!callbacks.current.visible || !doc || !root || !box || box.width<40 || box.height<40 || !saved || saved.chapterId!==chapter?.id)return false;
    const el=bookmarkElement(doc,saved);const rect=el?.getClientRects()[0];
    if(rect){if(vertical)root.scrollLeft+=rect.right-root.clientWidth-saved.offset;else root.scrollTop+=rect.top-saved.offset;}else{if(vertical)root.scrollLeft=saved.scroll;else root.scrollTop=saved.scroll;}manualPage.current=true;measure();return true;
  }
  function turn(step:number){restore.current=null;
    if(step<0 && pages.current<=1 && hasPreviousChapter || step>0 && pages.current>=pages.total && hasNextChapter){onChapterTurn?.(step);return;}landing.current=null;
    manualPage.current=true;const doc=frame.current?.contentDocument;const root=scrollRoot(doc);if(!root || !doc)return;
    const index=Math.max(0,Math.min(pages.total-1,pages.current-1+step));if(vertical)root.scrollLeft=sign.current*targets.current[index];else root.scrollTop=targets.current[index];measure();
    // Select the leading visible sentence without opening the iPad editor or
    // scrolling the EPUB back to the start of its paragraph.
    let leading:{element:Element;position:number}|undefined;
    for(const element of doc.querySelectorAll('[data-sentence]'))for(const rect of Array.from(element.getClientRects())){
      if(rect.width<=0 || rect.height<=0 || rect.right<16 || rect.left>root.clientWidth-16 || rect.bottom<16 || rect.top>root.clientHeight-16)continue;
      const position=vertical?-Math.min(rect.right,root.clientWidth):Math.max(rect.top,0);
      if(!leading || position<leading.position)leading={element,position};
    }
    if(leading){const pid=leading.element.getAttribute('data-sentence-paragraph')!,sentence=Number(leading.element.getAttribute('data-sentence'));const current=currentUnit.current;
      if(pid && callbacks.current.onVisibleUnit && (current?.paragraph_id!==pid || current.kind==='sentence' && current.sentence_index!==sentence)){holdPosition.current=true;callbacks.current.onVisibleUnit?.(pid,sentence);}
    }
  }
  const aiCurrent=useRef(aiHighlight);aiCurrent.current=aiHighlight;
  const markAI=useCallback(()=>{
    const doc=frame.current?.contentDocument;if(!doc)return;
    const win=doc.defaultView as (Window & {CSS?:{highlights?:Map<string,unknown>};Highlight?:new(r:Range)=>unknown})|null;
    win?.CSS?.highlights?.delete('ai-candidate');
    doc.querySelectorAll('.ai-ruby-selected').forEach(e=>e.classList.remove('ai-ruby-selected'));
    const c=aiCurrent.current;if(!c)return;
    const paragraph=Array.from(doc.querySelectorAll('[data-paragraph]')).find(e=>e.getAttribute('data-paragraph')===c.paragraph_id);if(!paragraph)return;
    const walker=doc.createTreeWalker(paragraph,NodeFilter.SHOW_TEXT,{acceptNode:node=>node.parentElement?.closest('rt,rp,rtc')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
    let offset=0;let node;const range=doc.createRange();let started=false;let ended=false;
    while((node=walker.nextNode())){const n=Array.from(node.textContent || '').length;const chars=Array.from(node.textContent || '');if(!started && offset+n>=c.start){range.setStart(node,chars.slice(0,Math.max(0,c.start-offset)).join('').length);started=true;}if(started && offset+n>=c.end){range.setEnd(node,chars.slice(0,Math.max(0,c.end-offset)).join('').length);ended=true;break;}offset+=n;}
    if(!started || !ended)return;
    if(win?.CSS?.highlights && win.Highlight)win.CSS.highlights.set('ai-candidate',new win.Highlight(range));
    const rect=range.getClientRects()[0];const root=scrollRoot(doc);if(rect && root){if(vertical && (rect.left<20 || rect.right>root.clientWidth-20))root.scrollLeft+=rect.right-(root.clientWidth-24);else if(!vertical && (rect.top<20 || rect.bottom>root.clientHeight-20))root.scrollTop+=rect.top-24;}
    measure();
  },[measure,vertical]);
  useEffect(()=>{markAI();},[aiHighlight,markAI]);
  const pending=useRef(pendingCandidates);pending.current=pendingCandidates;
  const markPending=useCallback(()=>{
    const doc=frame.current?.contentDocument;if(!doc)return;
    const win=doc.defaultView as (Window & {CSS?:{highlights?:Map<string,unknown>};Highlight?:new(...r:Range[])=>unknown})|null;
    win?.CSS?.highlights?.delete('ai-unreviewed');
    clearAITextMarks(doc);
    doc.querySelectorAll('.ai-unreviewed-text').forEach(e=>e.classList.remove('ai-unreviewed-text'));
    const paragraphs=new Map(Array.from(doc.querySelectorAll('[data-paragraph]')).map(el=>[el.getAttribute('data-paragraph'),el]));
    const grouped=new Map<string,Candidate[]>();
    for(const c of pending.current){const list=grouped.get(c.paragraph_id) || [];list.push(c);grouped.set(c.paragraph_id,list);}
    for(const [pid,candidates] of grouped){const paragraph=paragraphs.get(pid);if(paragraph)markAIText(paragraph,candidates);}

  },[]);
  useEffect(()=>{markPending();},[pendingCandidates,markPending]);
  const currentUnit=useRef(unit);currentUnit.current=unit;
  const highlight=useCallback(()=>{
    const unit=currentUnit.current;const keepPosition=holdPosition.current || landing.current!==null || restore.current!==null;holdPosition.current=false;
    const doc=frame.current?.contentDocument;if(!doc || !callbacks.current.visible)return;
    doc.querySelectorAll('[data-paragraph]').forEach(el=>el.classList.toggle('selected',!readingOnly && unit?.kind==='paragraph' && el.getAttribute('data-paragraph')===unit.paragraph_id));
    doc.querySelectorAll('[data-sentence]').forEach(el=>el.classList.toggle('sentence-selected',!readingOnly && unit?.kind==='sentence' && el.getAttribute('data-sentence-paragraph')===unit.paragraph_id && Number(el.getAttribute('data-sentence'))===unit.sentence_index));
    const selected=Array.from(doc.querySelectorAll(unit?.kind==='sentence'?'.sentence-selected':'.selected'));
    const root=scrollRoot(doc);
    if(root && selected.length && !vertical && !keepPosition){
      const rects=selected.flatMap(el=>Array.from(el.getClientRects())).filter(r=>r.width>0 && r.height>0);
      if(rects.length){const top=Math.min(...rects.map(r=>r.top)),bottom=Math.max(...rects.map(r=>r.bottom));if(top<16 || bottom>root.clientHeight-16)root.scrollTop+=top-16;}
    }
    if(root && selected.length && vertical && !keepPosition){
      // Vertical text runs across columns. Use every fragment, not the inline
      // bounding box or scrollIntoView's logical-axis "nearest" behavior.
      const rectangles=selected.flatMap(element=>{
        const range=doc.createRange();range.selectNodeContents(element);
        return Array.from(range.getClientRects());
      }).filter(rect=>rect.width>0 && rect.height>0);
      if(rectangles.length){
        const margin=Math.min(24,root.clientWidth/10);
        const left=Math.min(...rectangles.map(r=>r.left));
        const right=Math.max(...rectangles.map(r=>r.right));
        const fits=right-left<=root.clientWidth-margin*2;
        const leading=rectangles[0];
        const visible=fits?left>=margin && right<=root.clientWidth-margin:
          leading.left>=margin && leading.right<=root.clientWidth-margin;
        if(!visible)root.scrollLeft+=(fits?right:leading.right)-(root.clientWidth-margin);
        // Also recover if an earlier manual scroll moved the text vertically.
        if(leading.top<0 || leading.bottom>root.clientHeight)root.scrollTop+=leading.top-margin;
      }
    }
    measure();
  },[measure,vertical,readingOnly]);
  const reflow=useRef(highlight);reflow.current=highlight;
  useEffect(()=>{if(lastUnit.current!==unit){landing.current=null;lastUnit.current=unit;}manualPage.current=holdPosition.current;highlight();},[unit,highlight]);
  useEffect(()=>()=>cleanup.current(),[]);
  useEffect(()=>{restore.current=restoreBookmark;if(!visible)return;const id=requestAnimationFrame(()=>{if(restoreReader())return;const root=scrollRoot(frame.current?.contentDocument);if(!root)return;if(landing.current){applyLanding();return;}const restored=callbacks.current.initialScroll;if(restored!=null){manualPage.current=true;if(vertical)root.scrollLeft=restored;else root.scrollTop=restored;}measure();});return()=>cancelAnimationFrame(id);},[visible,vertical,measure,restoreBookmark]);
  const previousButton=<button className={readerNavigation?'reader-side-page previous-side':undefined} aria-label="本文前の表示ページ" disabled={!chapter || pages.current<=1 && !hasPreviousChapter} onClick={()=>turn(-1)}>{readerNavigation?(rightToLeft?'▶':'◀'):'前のページ'}</button>;
  const nextButton=<button className={readerNavigation?'reader-side-page next-side':undefined} aria-label="本文次の表示ページ" disabled={!chapter || pages.current>=pages.total && !hasNextChapter} onClick={()=>turn(1)}>{readerNavigation?(rightToLeft?'◀':'▶'):'次のページ'}</button>;
  return <>
    <div className={`epub-page-controls ${rightToLeft?'vertical-pages':''}`} data-writing-mode={mode}>{!readerNavigation && previousButton}<span aria-label="本文表示ページ">表示 {pages.current} / {pages.total}ページ</span>{!readerNavigation && nextButton}</div>
    <div className="epub-frame-viewport">
    {readerNavigation && <div className={`reader-side-navigation ${rightToLeft?'vertical-sides':''}`} aria-label="本文のページ送り">{previousButton}{nextButton}</div>}
    {/* WebKit blocks parent-installed document event handlers without allow-scripts.
        Preview HTML is allowlist-sanitized on the server; CSP still denies all
        embedded/loaded scripts, handlers, objects, forms and navigation bases. */}
    <iframe title={vertical?'EPUB縦書きプレビュー':'EPUB横書きプレビュー'} ref={frame} sandbox="allow-same-origin allow-scripts" srcDoc={source} onLoad={()=>{
      cleanup.current();const doc=frame.current?.contentDocument;const root=scrollRoot(doc);if(!doc || !root)return;
      const saved=root.scrollLeft;root.scrollLeft=-1;sign.current=root.scrollLeft<0?-1:1;root.scrollLeft=saved;
      const click=(event:MouseEvent)=>{landing.current=null;restore.current=null;
        const target=event.target as Node|null;const el=target?.nodeType===1?target as Element:target?.parentElement;if(!el)return;const ruby=el.closest('[data-ruby]');const sentence=el.closest('[data-sentence]');const paragraph=el.closest('[data-paragraph]');
        capture(sentence || paragraph);
        if(ruby){callbacks.current.onChoose(ruby.getAttribute('data-ruby-paragraph')!,sentence?Number(sentence.getAttribute('data-sentence')):undefined);callbacks.current.onRuby(ruby.getAttribute('data-ruby-paragraph')!,Number(ruby.getAttribute('data-ruby')),sentence?Number(sentence.getAttribute('data-sentence')):undefined);}
        else if(paragraph){callbacks.current.onChoose(paragraph.getAttribute('data-paragraph')!,sentence?Number(sentence.getAttribute('data-sentence')):undefined);}
      };
      const keyboard=(event:KeyboardEvent)=>callbacks.current.onKey(event);
      const scroll=()=>{const box=frame.current?.getBoundingClientRect();if(!callbacks.current.visible || !box || box.width<40 || box.height<40 || root.clientWidth<40 || root.clientHeight<40)return;capture();measure();callbacks.current.onScroll?.(vertical?root.scrollLeft:root.scrollTop);};
      const resize=()=>{if(!callbacks.current.visible)return;if(restoreReader())return;landing.current?applyLanding():manualPage.current?measure():reflow.current();};
      const wheel=()=>{manualPage.current=true;landing.current=null;restore.current=null;};
      const touch=()=>{manualPage.current=true;landing.current=null;restore.current=null;};
      doc.addEventListener('wheel',wheel);doc.addEventListener('touchstart',touch,{passive:true});
      doc.addEventListener('click',click);doc.addEventListener('keydown',keyboard);root.addEventListener('scroll',scroll);doc.addEventListener('load',resize,true);
      const observer=new ResizeObserver(resize);observer.observe(frame.current!);observer.observe(doc.body);
      cleanup.current=()=>{observer.disconnect();doc.removeEventListener('click',click);doc.removeEventListener('keydown',keyboard);root.removeEventListener('scroll',scroll);doc.removeEventListener('wheel',wheel);doc.removeEventListener('touchstart',touch);doc.removeEventListener('load',resize,true);};
      const restored=callbacks.current.initialScroll;highlight();markAI();markPending();
      if(restoreReader()){}else if(landing.current){manualPage.current=true;applyLanding();}else if(restored!=null){manualPage.current=true;if(vertical)root.scrollLeft=restored;else root.scrollTop=restored;measure();}else manualPage.current=false;
      void doc.fonts.ready.then(()=>{if(frame.current?.contentDocument===doc)resize();});
    }}/></div>
  </>;
}
