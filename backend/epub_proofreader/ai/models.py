from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Category=Literal['kanji','kana','missing','extra','punctuation','page_contamination','header_contamination','ruby','unnatural']
class Suggestion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target:Literal['text','ruby']
    start:int|None
    end:int|None
    original:str=Field(max_length=4000)
    replacement:str|None=Field(max_length=4000)
    reason:str=Field(min_length=1,max_length=1000)
    category:Category
    confidence:float=Field(ge=0,le=1)
    ruby_index:int|None
    base_after:str|None
    reading_after:str|None
class Result(BaseModel):
    model_config=ConfigDict(extra='forbid')
    paragraph_id:str
    suggestions:list[Suggestion]=Field(max_length=100)
class Engine(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    provider:Literal['ollama','gemini','anthropic','openai']
    url:str=Field(max_length=1000)
    model:str=Field(min_length=1,max_length=150,pattern=r'^[a-zA-Z0-9_.:/-]+$')
    is_default:bool=False
    visibility:Literal['private','shared']='private'
    api_key:str|None=Field(default=None,max_length=500)
    input_price:float|None=Field(default=None,ge=0,le=10000)
    output_price:float|None=Field(default=None,ge=0,le=10000)
    chunk_chars:int=Field(default=1200,ge=200,le=4000)
    max_output_tokens:int=Field(default=4096,ge=256,le=8192)
class Start(BaseModel):
    skip_confirmed:bool=True
    batch_paragraphs:int=Field(default=1,ge=1,le=8)
    engine_id:str
    scope:Literal['paragraph','chapter','book']
    paragraph_id:str|None=None
    chapter_id:str|None=None
    request_id:str=Field(min_length=16,max_length=100)
    revision:int=Field(ge=0)
    cloud_confirmed:bool=False
    budget:float|None=Field(default=None,gt=0,le=10000)

class StoredSuggestion(Suggestion):
    match_count:int=Field(default=1,ge=1)
    suggested_replacement:str|None=Field(default=None,max_length=4000)
    query_type:Literal["body","ruby"]|None=None
    proposal_note:str|None=Field(default=None,max_length=500)
