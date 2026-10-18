import {useEffect,useState} from 'react';
import {api} from './apiClient';

type Lease={listeners:Set<(message:string)=>void>;message:string;timer:ReturnType<typeof setInterval>;pending:Promise<void>};
const leases=new Map<string,Lease>();
// Several ruby rows and the body editor can share one tab's lease.
export default function useEditLease(bookId:string,pid:string,enabled=true){
 const [message,setMessage]=useState('');
 useEffect(()=>{
  if(!enabled){setMessage('');return;}
  const url=`/api/books/${bookId}/paragraphs/${pid}/lock`;
  let lease=leases.get(url);
  if(!lease){
   const entry:Lease={listeners:new Set(),message:'',timer:undefined as unknown as ReturnType<typeof setInterval>,pending:Promise.resolve()};
   const acquire=()=>{entry.pending=api(url,'POST').then(()=>{entry.message='';}).catch(e=>{entry.message=String(e);}).then(()=>{entry.listeners.forEach(fn=>fn(entry.message));});};
   entry.timer=setInterval(acquire,20000);leases.set(url,entry);lease=entry;acquire();
  }
  const current=lease;current.listeners.add(setMessage);setMessage(current.message);
  return()=>{current.listeners.delete(setMessage);if(!current.listeners.size){clearInterval(current.timer);leases.delete(url);void current.pending.then(()=>{if(!leases.has(url))return api(url,'DELETE');}).catch(()=>{});}};
 },[bookId,pid,enabled]);
 return message;
}
