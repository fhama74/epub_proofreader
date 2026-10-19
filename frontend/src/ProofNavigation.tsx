type Props={rightToLeft:boolean;previous:boolean;next:boolean;previousAI:boolean;nextAI:boolean;onPrevious:()=>void;onNext:()=>void;onPreviousAI:()=>void;onNextAI:()=>void};
export default function ProofNavigation(p:Props){
 const items=[
  {id:'previous-ai',label:'前のAI検知',name:'前のAI検知',back:true,enabled:p.previousAI,run:p.onPreviousAI},
  {id:'previous',label:'前へ',name:'前の段落・文',back:true,enabled:p.previous,run:p.onPrevious},
  {id:'next',label:'次へ',name:'次の段落・文',back:false,enabled:p.next,run:p.onNext},
  {id:'next-ai',label:'次のAI検知',name:'次のAI検知',back:false,enabled:p.nextAI,run:p.onNextAI},
 ];
 if(p.rightToLeft)items.reverse();
 return <nav className="combined-navigation" aria-label="校正箇所の移動">{items.map(item=>{
  const pointsRight=item.back?p.rightToLeft:!p.rightToLeft;
  return <button key={item.id} aria-label={item.name} disabled={!item.enabled} onClick={item.run}>{!pointsRight && '◀ '}{item.label}{pointsRight && ' ▶'}</button>;
 })}</nav>;
}
