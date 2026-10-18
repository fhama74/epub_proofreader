import json,copy
from dataclasses import dataclass
import httpx
from ..models import Result
from ..engine_manager import validate_url

@dataclass
class Reply:
    text:str
    input_tokens:int|None=None
    output_tokens:int|None=None

class ResponseFormatError(ValueError):
    def __init__(self,message,output):
        super().__init__(message)
        self.output=output

def schema(engine=None):
    value=copy.deepcopy((engine or {}).get('_response_schema') or Result.model_json_schema())
    def clean(v):
        if isinstance(v,dict):
            for k in ['minimum','maximum','minLength','maxLength','maxItems','minItems','default']:v.pop(k,None)
            for item in v.values():clean(item)
        elif isinstance(v,list):
            for item in v:clean(item)
    clean(value);return value

def request(engine,method,path,**kwargs):
    url=validate_url(engine['url'],engine['provider'])+path
    # No redirects, environment proxies, or arbitrary cloud origins; never reflect response bodies (may contain keys).
    try:
        with httpx.Client(timeout=httpx.Timeout(180,connect=10),follow_redirects=False,trust_env=False) as client:
            with client.stream(method,url,**kwargs) as response:
                if response.status_code in {502,503,504}:raise ValueError(f'AIサービスを利用できません（HTTP {response.status_code}）。サービスの稼働状態を確認してください。')
                if response.status_code==400:raise ValueError('AI接続先が送信内容を受け付けませんでした（HTTP 400）。モデル名・送信形式・設定を確認してください。')
                if response.status_code>=300:raise ValueError(f"AI接続先がHTTP {response.status_code}を返しました。URL・モデル・認証を確認してください。")
                content=bytearray()
                for part in response.iter_bytes():
                    content.extend(part)
                    if len(content)>10*1024*1024:raise ValueError('AIの応答が大きすぎます。')
                try:return json.loads(content)
                except (json.JSONDecodeError,UnicodeDecodeError):
                    raise ResponseFormatError('AI接続先から不正なJSONが返りました。',content.decode('utf-8',errors='replace')) from None
    except (httpx.ConnectError,httpx.ConnectTimeout):raise ValueError('接続エラー：AIサービスに接続できません。サービスの起動状態・接続先・ネットワークを確認してください。') from None
    except httpx.TimeoutException:raise ValueError('AIから応答がありません。処理の長期化、サービス停止、通信断の可能性があります。') from None
    except httpx.HTTPError:raise ValueError('AIへ接続できません。URL・ネットワーク・Tailscaleの接続を確認してください。') from None
    except json.JSONDecodeError:raise ValueError('AI接続先から不正なJSONが返りました。') from None
