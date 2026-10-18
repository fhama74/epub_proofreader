"""Immutable XHTML overlays. ZIP assembly is reserved for explicit exports."""
from dataclasses import dataclass
from functools import lru_cache,cached_property
from collections import OrderedDict
from hashlib import sha256
import json

@lru_cache(maxsize=2)
def baseline(data):
 from .epub import Book
 return Book(data)

recent=OrderedDict()

@dataclass(frozen=True)
class WorkingFiles:
 base:bytes
 replacements:tuple=()
 @classmethod
 def merge(cls,source,changes=None):
  current=dict(source.replacements) if isinstance(source,cls) else {}
  base=source.base if isinstance(source,cls) else source
  for path,value in (changes or {}).items():
   if value is None:
    if path in baseline(base).files:current[path]=None
    else:current.pop(path,None)
   else:current[path]=value
  return cls(base,tuple(sorted(current.items())))
 @cached_property
 def fingerprint(self):
  if not self.replacements:return sha256(self.base).hexdigest()
  return sha256(json.dumps([sha256(self.base).hexdigest(),[(p,sha256(v).hexdigest() if v is not None else None) for p,v in self.replacements]],ensure_ascii=False).encode()).hexdigest()
 def model(self):return model(self)
 def materialize(self):
  from .editing import repack
  return repack(self.base,dict(self.replacements)) if self.replacements else self.base

@lru_cache(maxsize=4)
def model(source):
 key=sha256(source.base).digest();base=baseline(source.base)
 previous=recent.get(key)
 current=dict(source.replacements)
 # A new upload or a complete Undo is the exact baseline, even when another
 # project with identical bytes most recently populated the incremental cache.
 if not current:previous=None
 if previous:
  old,book=previous;prior=dict(old.replacements)
  changes={p:current.get(p,base.files.get(p)) for p in current.keys()|prior.keys() if current.get(p,base.files.get(p))!=prior.get(p,base.files.get(p))}
 else:book=base;changes=current
 if any(p not in book.trees or data is None for p,data in changes.items()):
  # Explicit chapter operations can change the package and add files. Text edits
  # continue to use the XHTML-only fast path.
  from .epub import Book
  result=Book(source.materialize())
 else:result=book.updated(changes) if changes else book
 # Use the exact snapshot, including removals, as the source of a later export.
 import copy
 result=copy.copy(result);result.original=source;result.fingerprint=source.fingerprint
 recent[key]=(source,result);recent.move_to_end(key)
 while len(recent)>2:recent.popitem(last=False)
 return result


def materialize(source):return source.materialize() if hasattr(source,'materialize') else source
