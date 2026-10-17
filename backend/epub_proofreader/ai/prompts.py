"""Editable inspection policies; response and location protocols stay tool-owned."""
import json
from pydantic import BaseModel,ConfigDict,Field,field_validator
from fastapi import HTTPException
from .engine_manager import OWNER

DEFAULTS={
 'common':'あなたは日本語書籍のOCR復元検査者です。文章改善・リライト・現代語化はしません。旧字、歴史的仮名遣い、方言、口語、文学表現、倒置、省略、反復、ひらがな表記、独特な言い回し、著者の文体を許容し、誤り扱いしない。文法・意味・表現の不自然さだけでは報告しない。OCR由来と考えられる具体的な文字異常・混入だけを検出する。判断できない場合は報告を控える。',
 'body':'本文専用検査です。ルビの読みは検査しません。OCR由来と考えられる文字の誤認識・脱落・重複・混入、句読点の文字異常、柱・ページ番号の混入だけを検査する。その文字を別の文字に置き換えると意味が通る、またはその文字を取り除くと意味が通る箇所を主な検出対象とする。異常は多くの場合、連続した長い文字列ではなく、一文字または少数の文字に現れる。問題箇所はできるだけ短く特定する。ただし文脈上意味が通る別表現に書き換えられるというだけでは誤りと判断しない。長い範囲でも、柱などの混入に具体的な根拠がある場合は検出してよい。ひらがなを漢字へ変換する提案や、句読点の好み・文体上の省略の訂正はしない。OCR誤認識の参考例：犀根→屋根、垂麗→華麗、芸奢→華奢、感酸→威厳、鋭ぎ→鋭さ。これらは文脈に応じた検出の手掛かりであり、必ず置換する辞書ではない。同じ文字列でも原文の表現として成立する場合は変更しない。誤認識が複数文字に及ぶ場合もあるため、一文字だけという制限は設けない。',
 'ruby':'ルビ専用検査です。本文の一般的な誤字は検査せず、親文字と読みの対応・読みのOCR誤認識を検査する。本文検査の一文字の置換・削除という条件はルビには適用せず、読みを語として確認する。親文字と意味の近い当て字、熟字訓、歴史的な読み、文学的な独自ルビを許容し、一般的な辞書の読みと違うだけでは報告しない。日本語の単語・活用形として成立しない読みを検出対象とする。ただし固有名詞、外来語、方言、擬音語・擬態語、造語、複数語からなる読みは、未知の語・辞書にないというだけで誤り扱いしない。周辺の文脈と親文字の意味を踏まえ、OCR由来の文字異常が疑われる場合だけ報告し、判断できない場合は報告を控える。',
}
LEGACY_BODY=DEFAULTS['body']
DEFAULTS['body']='本文専用のOCR誤認識検査です。ルビの読みは検査しません。別の文字なら意味が通る誤認識、または削除すれば意味が通る混入だけを検出してください。原文の指摘は1文字または連続最大2文字に限定します。離れた複数箇所はそれぞれ別の指摘にしてください。連続3文字以上になる範囲を分割して報告しないでください。口語、文学表現、倒置、省略、反復、ひらがな表記、旧字、歴史的仮名遣い、固有名詞、当て字を許容します。判断できない場合は報告を控えてください。訂正案は確かな場合のみ返し、不明ならnullにしてください。参考例：犀根→屋根、垂麗→華麗、芸奢→華奢、感酸→威厳、鋭ぎ→鋭さ。これは置換辞書ではなく、文脈上成立する表現は変更しないでください。'
class Policy(BaseModel):
 model_config=ConfigDict(extra='forbid')
 common:str=Field(min_length=1,max_length=6000)
 body:str=Field(min_length=1,max_length=6000)
 ruby:str=Field(min_length=1,max_length=6000)
 @field_validator('common','body','ruby')
 @classmethod
 def nonempty(cls,v):
  if not v.strip():raise ValueError('空の指示は保存できません。')
  return v.strip()
class Update(Policy):
 revision:int=Field(ge=0)

def read(con):
 row=con.execute('SELECT value FROM ai_settings WHERE key=?',('prompt_policy:'+OWNER,)).fetchone()
 data=json.loads(row[0]) if row else {'values':dict(DEFAULTS),'revision':0}
 if data['values'].get('body')==LEGACY_BODY:data['values']['body']=DEFAULTS['body']
 return {**data,'defaults':dict(DEFAULTS)}

def save(con,req):
 current=read(con)
 if req.revision!=current['revision']:raise HTTPException(409,'別の画面で指示が更新されています。閉じて開き直してください。')
 value={'values':req.model_dump(exclude={'revision'}),'revision':req.revision+1}
 con.execute('INSERT INTO ai_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('prompt_policy:'+OWNER,json.dumps(value,ensure_ascii=False)))
 return {**value,'defaults':dict(DEFAULTS)}
