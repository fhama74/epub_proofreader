import {reviewStatus} from './reviewState';
import type {Candidate} from './aiTypes';
import type {Paragraph} from './types';
export default function ReviewBadge({paragraph,flags=[],target='body'}:{paragraph?:Paragraph;flags?:Candidate[];target?:'body'|'ruby'}){
 if(!paragraph)return null;
 const state=paragraph.review_state?.[target];
 const {color,label}=reviewStatus(paragraph,flags,target);
 return <span className={`review-badge ${color}`} role="status" aria-label={`${target==='body'?'段落':'ルビ'}の校閲状態：${label}`}><span aria-hidden="true">●</span> {label}{state && state.total>1 && <small> {state.done}/{state.total}{target==='body'?'文':'箇所'}</small>}</span>;
}
