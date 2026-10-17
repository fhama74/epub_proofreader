export interface ReaderBookmark {chapterId:string;paragraphId:string;sentenceIndex?:number;offset:number;scroll:number}
export function bookmarkElement(doc:Document,bookmark:ReaderBookmark){
 const sentences=Array.from(doc.querySelectorAll<HTMLElement>('[data-sentence]')).filter(el=>el.getAttribute('data-sentence-paragraph')===bookmark.paragraphId);
 const sentence=sentences.find(el=>Number(el.getAttribute('data-sentence'))===bookmark.sentenceIndex) || (bookmark.sentenceIndex!==undefined?sentences[Math.min(bookmark.sentenceIndex,sentences.length-1)]:undefined);
 return sentence || Array.from(doc.querySelectorAll<HTMLElement>('[data-paragraph]')).find(el=>el.getAttribute('data-paragraph')===bookmark.paragraphId);
}
