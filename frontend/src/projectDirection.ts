import type {Book} from './types';
/** Covers and colophons may use a different writing mode from the main text. */
export function projectRightToLeft(book:Pick<Book,'direction'|'chapters'>|null){
 if(!book)return false;
 if(book.direction==='rtl')return true;
 if(book.direction==='ltr')return false;
 const main=book.chapters.reduce<(typeof book.chapters)[number]|undefined>((best,c)=>!best || c.paragraphs.reduce((n,p)=>n+p.character_count,0)>best.paragraphs.reduce((n,p)=>n+p.character_count,0)?c:best,undefined);
 return !!main?.writing_mode?.startsWith('vertical');
}
