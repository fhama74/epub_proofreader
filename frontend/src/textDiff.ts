export interface DiffPart {text:string;changed:boolean}
export function textDiff(before:string,after:string):{before:DiffPart[];after:DiffPart[]}{
  const a=Array.from(before),b=Array.from(after);let head=0,tail=0;
  while(head<a.length && head<b.length && a[head]===b[head])head++;
  while(tail<a.length-head && tail<b.length-head && a[a.length-1-tail]===b[b.length-1-tail])tail++;
  const x=a.slice(head,a.length-tail),y=b.slice(head,b.length-tail);
  const left:DiffPart[]=[],right:DiffPart[]=[];
  const add=(out:DiffPart[],text:string,changed:boolean)=>{if(!text)return;const prev=out.at(-1);if(prev?.changed===changed)prev.text+=text;else out.push({text,changed});};
  add(left,a.slice(0,head).join(''),false);add(right,b.slice(0,head).join(''),false);
  // Myers' shortest edit path, bounded for entirely replaced, very long input.
  const trace:Map<number,number>[]=[];const v=new Map<number,number>([[1,0]]);let found=false,work=0;
  outer:for(let d=0;d<=x.length+y.length;d++){
    if(work>2000000 || d>1024)break;trace.push(new Map(v));
    for(let k=-d;k<=d;k+=2){
      let i=k===-d || k!==d && (v.get(k-1)??-1)<(v.get(k+1)??-1)?v.get(k+1)??0:(v.get(k-1)??0)+1;let j=i-k;work++;
      while(i<x.length && j<y.length && x[i]===y[j]){i++;j++;work++;}v.set(k,i);
      if(i>=x.length && j>=y.length){found=true;break outer;}
    }
  }
  if(found){
    const ops:{kind:'same'|'delete'|'insert';text:string}[]=[];let i=x.length,j=y.length;
    for(let d=trace.length-1;d>=0;d--){const old=trace[d],k=i-j;const pk=k===-d || k!==d && (old.get(k-1)??-1)<(old.get(k+1)??-1)?k+1:k-1;const pi=old.get(pk)??0,pj=pi-pk;
      while(i>pi && j>pj){ops.push({kind:'same',text:x[--i]});j--;}
      if(d>0){if(i===pi)ops.push({kind:'insert',text:y[--j]});else ops.push({kind:'delete',text:x[--i]});}
    }
    for(const op of ops.reverse()){if(op.kind!=='insert')add(left,op.text,op.kind==='delete');if(op.kind!=='delete')add(right,op.text,op.kind==='insert');}
  }else {add(left,x.join(''),true);add(right,y.join(''),true);}
  add(left,a.slice(a.length-tail).join(''),false);add(right,b.slice(b.length-tail).join(''),false);
  return {before:left,after:right};
}
