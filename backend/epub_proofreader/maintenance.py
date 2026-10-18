"""Drain this process's DB connections before SQLite compaction."""
import threading
import time
from contextlib import contextmanager

condition=threading.Condition();local=threading.local();users=0;owner=None;pending=False


@contextmanager
def access():
    global users
    nested=getattr(local,'depth',0)>0 or owner==threading.get_ident()
    with condition:
        if not nested:
            while pending or owner is not None:condition.wait()
            users+=1
        local.depth=getattr(local,'depth',0)+1
    try:yield
    finally:
        with condition:
            local.depth-=1
            if not nested:users-=1;condition.notify_all()


@contextmanager
def exclusive():
    global pending,owner
    from fastapi import HTTPException
    with condition:
        if pending or owner is not None:raise HTTPException(409,'データベースの整理は既に実行中です。')
        pending=True
        try:
            deadline=time.monotonic()+10
            while users:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise HTTPException(409,'保存処理が続いています。少し待ってから整理してください。')
                condition.wait(remaining)
            owner=threading.get_ident()
        except BaseException:
            pending=False;condition.notify_all();raise
    try:yield
    finally:
        with condition:owner=None;pending=False;condition.notify_all()


def compact(con):
    """Keep all active content, publications, review flags and AI evidence."""
    page_size=con.execute('PRAGMA page_size').fetchone()[0]
    before=page_size*con.execute('PRAGMA page_count').fetchone()[0]
    con.execute('BEGIN IMMEDIATE')
    try:
        expired=con.execute('DELETE FROM unit_locks WHERE expires<=?',(time.time(),)).rowcount
        old_reviews=con.execute('DELETE FROM unit_reviews WHERE NOT EXISTS(SELECT 1 FROM unit_nodes n WHERE n.book_id=unit_reviews.book_id AND n.id=unit_reviews.unit_id AND n.version=unit_reviews.version AND n.active=1)').rowcount
        removed=con.execute("DELETE FROM unit_nodes WHERE active=0 AND kind='unit' AND NOT EXISTS(SELECT 1 FROM unit_nodes child WHERE child.book_id=unit_nodes.book_id AND child.parent=unit_nodes.id AND child.active=1)").rowcount
        if con.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('関連データの整合性を確認できなかったため、整理を取り消しました。')
        con.commit()
    except BaseException:con.rollback();raise
    # VACUUM must run outside a transaction; active content is already safe if
    # an external reader or lack of temporary disk space prevents compaction.
    warning=None
    try:
        con.execute('VACUUM');con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    except __import__('sqlite3').OperationalError:
        warning='不要データは整理しましたが、容量の縮小は完了しませんでした。空き容量や他の接続を確認して再実行してください。'
    after=page_size*con.execute('PRAGMA page_count').fetchone()[0]
    return dict(before_bytes=before,after_bytes=after,reclaimed_bytes=max(0,before-after),removed_units=removed,expired_locks=expired,obsolete_reviews=old_reviews,compacted=warning is None,warning=warning)
