/** Always translate HTTP/JSON failures into actionable messages, including Safari. */
export class APIError extends Error {constructor(message:string,public status:number){super(message);this.name='Error';}}
export async function api<T>(url:string,method='GET',body?:unknown):Promise<T>{
 let response:Response;
 try{response=await fetch(url,{method,headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});}
 catch{throw new APIError('サーバーに接続できません。接続状態を確認して、もう一度操作してください。',0);}
 let value:unknown;
 try{value=await response.json();}
 catch{throw new APIError(response.ok?'サーバーの返答を読み込めませんでした。画面を再読み込みしてください。':`サーバーの処理に失敗しました（HTTP ${response.status}）。少し待ってからもう一度操作してください。`,response.status);}
 if(!response.ok){
  const detail=typeof value==='object' && value!==null && 'detail' in value?value.detail:null;
  throw new APIError(typeof detail==='string'?detail:`入力内容または保存処理を確認してください（HTTP ${response.status}）。`,response.status);
 }
 return value as T;
}
