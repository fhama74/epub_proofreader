import type {ProofScore as Score} from './types';
export default function ProofScore({value}:{value?:Score|null}){
 if(!value)return null;
 const explanation=`AI：${value.ai_completed?'書籍全体の検査完了 · 50点':'全体検査未完了 · 0点'}／人の確認・修正：${value.reviewed}/${value.total}単位 · ${value.review_points}点（段落・見出しごと、重複なし）`;
 return <span className="proof-score" title={explanation} aria-label={`校正進捗 ${value.score}点 / 100点。${explanation}`}><span>校正進捗 <strong>{value.score} / 100</strong></span><small>AI {value.ai_completed?'完了':'未完了'} · 確認 {value.reviewed}/{value.total}</small></span>;
}
