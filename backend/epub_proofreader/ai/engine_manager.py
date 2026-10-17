import json, os
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from ..editing import timestamp
from .models import Engine
from uuid import uuid4

DEFAULT_SECRET_FILE=Path(__file__).resolve().parents[3]/'secrets/ai_secret_key'

OWNER='local' # Replace this trusted principal with authenticated identity before multi-user hosting.
OFFICIAL={'openai':'https://api.openai.com','gemini':'https://generativelanguage.googleapis.com','anthropic':'https://api.anthropic.com'}
def allowed_origins():
    cfg=json.loads((Path(__file__).resolve().parents[3]/'config/initial-engines.json').read_text())
    return set(cfg['allowed_origins'])|set(filter(None,os.getenv('AI_ALLOWED_ORIGINS','').split(',')))
def validate_url(url,provider):
    p=urlsplit(url)
    origin=f'{p.scheme}://{p.netloc}'
    if p.scheme not in {'http','https'} or p.username or p.password or p.query or p.fragment or p.path not in {'','/'} or origin not in allowed_origins():
        raise HTTPException(422,'接続先は管理者の許可リストにある http/https の起点URLを指定してください。AI_ALLOWED_ORIGINSで追加できます。')
    if provider in OFFICIAL and origin!=OFFICIAL[provider]:raise HTTPException(422,'クラウドは公式APIの接続先を指定してください。')
    return origin

def cipher():
    key=os.getenv('AI_SECRET_KEY')
    key_file=os.getenv('AI_SECRET_KEY_FILE') or (str(DEFAULT_SECRET_FILE) if DEFAULT_SECRET_FILE.is_file() else None)
    if not key and key_file:
        path=Path(key_file).resolve()
        data=Path(os.getenv('DATA_DIR',os.getenv('EPROOF_DATA_DIR',str(Path(__file__).resolve().parents[3]/'.data')))).resolve()
        if path.is_relative_to(data):raise HTTPException(503,'暗号化キーは通常のデータフォルダーの外で管理してください。')
        try:key=path.read_text().strip()
        except OSError:raise HTTPException(503,'暗号化キーファイルを読み込めません。') from None
    if not key:raise HTTPException(503,'APIキー保存用の暗号化キーが未設定です。scripts/configure_local.pyを実行するか、AI_SECRET_KEY_FILEを指定してください。')
    try:return Fernet(key.encode())
    except ValueError:raise HTTPException(503,'暗号化キーの形式が不正です。') from None

def engine(con,ident,secret=False):
    row=con.execute('SELECT config,key_cipher FROM ai_engines WHERE id=? AND owner_id=?',(ident,OWNER)).fetchone()
    if not row:raise HTTPException(404,'AIエンジンがありません。')
    result={'id':ident,**Engine(**json.loads(row[0])).model_dump(exclude={'api_key'}),'has_api_key':bool(row[1])}
    if secret and row[1]:
        try:result['api_key']=cipher().decrypt(row[1].encode()).decode()
        except InvalidToken:raise HTTPException(503,'暗号化キーが一致しません。保存時の秘密キーを設定してください。') from None
    return result

def save(con,request,ident=None):
    previous=engine(con,ident) if ident else None
    if previous and previous['provider']!=request.provider and con.execute('SELECT 1 FROM ai_jobs WHERE engine_id=? LIMIT 1',(ident,)).fetchone():raise HTTPException(409,'校正履歴のあるエンジンはプロバイダーを変更できません。新しいエンジンとして登録してください。')
    cfg=request.model_dump(exclude={'api_key'});cfg['url']=validate_url(cfg['url'],cfg['provider'])
    encrypted=None
    if request.api_key:encrypted=cipher().encrypt(request.api_key.encode()).decode()
    if cfg['is_default']:
        for r in con.execute('SELECT id,config FROM ai_engines WHERE owner_id=?',(OWNER,)).fetchall():
            old=json.loads(r[1]);old['is_default']=False;con.execute('UPDATE ai_engines SET config=? WHERE id=?',(json.dumps(old),r[0]))
    if ident:
        old=con.execute('SELECT key_cipher FROM ai_engines WHERE id=?',(ident,)).fetchone()[0]
        if previous['provider']!=cfg['provider']:old=None
        con.execute('UPDATE ai_engines SET config=?,key_cipher=? WHERE id=?',(json.dumps(cfg),encrypted or old,ident))
    else:
        ident=str(uuid4());con.execute('INSERT INTO ai_engines VALUES (?,?,?,?,?)',(ident,OWNER,json.dumps(cfg),encrypted,timestamp()))
    return engine(con,ident)
