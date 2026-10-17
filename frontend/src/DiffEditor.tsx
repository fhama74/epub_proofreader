import {useEffect,useRef,type RefObject,type TextareaHTMLAttributes} from 'react';
import type {DiffPart} from './textDiff';
export function DiffText({parts}:{parts:DiffPart[]}){return <>{parts.map((part,i)=><span key={i} className={part.changed?'diff-changed':undefined}>{part.text}</span>)}</>;}
export default function DiffEditor({parts,inputRef,...props}:{parts:DiffPart[];inputRef:RefObject<HTMLTextAreaElement|null>}&TextareaHTMLAttributes<HTMLTextAreaElement>){
 const mirror=useRef<HTMLPreElement>(null);
 function sync(){if(mirror.current && inputRef.current){mirror.current.scrollTop=inputRef.current.scrollTop;mirror.current.scrollLeft=inputRef.current.scrollLeft;}}
 useEffect(sync,[props.value]);
 return <div className="diff-editor"><pre className="diff-mirror" ref={mirror} aria-hidden="true"><DiffText parts={parts}/>{'\u200b'}</pre><textarea {...props} ref={inputRef} onScroll={e=>{sync();props.onScroll?.(e);}}/></div>;
}
