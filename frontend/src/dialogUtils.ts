import {useEffect,useRef,type KeyboardEvent} from 'react';
export async function api<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(url,{method,headers: body === undefined ? undefined : {'Content-Type':'application/json'},body: body === undefined ? undefined : JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '入力内容または保存処理を確認してください。');
  return value as T;
}
export function useDialogFocus() {
  const ref=useRef<HTMLElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement | null;ref.current?.focus();return ()=>previous?.focus();},[]);
  return ref;
}
export function dialogKeys(event: KeyboardEvent<HTMLElement>,close:()=>void) {
  if(event.key==='Escape'){event.preventDefault();close();return;}
  if(event.key!=='Tab')return;
  const elements=Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled])')).filter(el=>el.getClientRects().length>0);
  if(!elements.length){event.preventDefault();return;}
  const active=document.activeElement;
  if(event.shiftKey && (active===elements[0] || active===event.currentTarget)){event.preventDefault();elements[elements.length-1].focus();}
  else if(!event.shiftKey && (active===elements[elements.length-1] || active===event.currentTarget)){event.preventDefault();elements[0].focus();}
}
