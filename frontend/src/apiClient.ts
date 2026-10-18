/** Always translate HTTP/JSON failures into actionable messages, including Safari. */
export class APIError extends Error {constructor(message:string,public status:number){super(message);this.name='Error';}}
// One owner per browser tab. This also works on HTTP iPad connections.
let owner:string;
export function editOwner(){
 if(!owner){try{owner=sessionStorage.getItem('eproof-edit-owner') || ''; }catch{}
  if(!owner){owner=globalThis.crypto?.randomUUID?.() || `browser-${Date.now()}-${Math.random().toString(36).slice(2)}`;try{sessionStorage.setItem('eproof-edit-owner',owner);}catch{}}
 }
 return owner;
}
export async function readJSON<T>(response:Response):Promise<T>{
 let value:unknown;
 try{value=await response.json();}
 catch(error){if(typeof error==='object' && error!==null && 'name' in error && error.name==='AbortError')throw error;throw new APIError(response.ok?'サーバーの返答を読み込めませんでした。画面を再読み込みしてください。':`サーバーの処理に失敗しました（HTTP ${response.status}）。少し待ってからもう一度操作してください。`,response.status);}
 if(!response.ok){
  const detail=typeof value==='object' && value!==null && 'detail' in value?value.detail:null;
  throw new APIError(typeof detail==='string'?detail:`入力内容または保存処理を確認してください（HTTP ${response.status}）。`,response.status);
 }
 return value as T;
}
export async function requestJSON<T>(url:string,options?:RequestInit):Promise<T>{
 let response:Response;
 const headers=new Headers(options?.headers);headers.set('X-Edit-Owner',editOwner());
 try{response=await fetch(url,{...options,headers});}
 catch(error){if(typeof error==='object' && error!==null && 'name' in error && error.name==='AbortError')throw error;throw new APIError('サーバーに接続できません。接続状態を確認して、もう一度操作してください。',0);}
 return readJSON<T>(response);
}
export async function api<T>(url:string,method='GET',body?:unknown):Promise<T>{
 return requestJSON<T>(url,{method,headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
}
