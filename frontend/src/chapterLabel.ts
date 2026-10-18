export function chapterLabel(chapter:{title:string;heading_level?:number}){
 const level=Math.max(1,Math.min(6,chapter.heading_level || 1));
 return '\u3000'.repeat(level-1)+chapter.title;
}
