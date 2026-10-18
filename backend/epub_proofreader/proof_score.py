"""Cached counts: ordinary confirmation changes one row and one counter."""


def ensure(con):
    con.execute('CREATE TABLE IF NOT EXISTS proof_scores(book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,total INTEGER NOT NULL,reviewed INTEGER NOT NULL,ai_completed INTEGER NOT NULL DEFAULT 0,epoch INTEGER NOT NULL DEFAULT 0)')
    con.execute('CREATE TABLE IF NOT EXISTS proof_score_units(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,unit_id TEXT NOT NULL,version INTEGER NOT NULL,reviewed INTEGER NOT NULL,PRIMARY KEY(book_id,unit_id))')


def rebuild(con,book_id,book=None):
    from . import editing,projects,reviews
    book=book or editing.working_model(editing.state(con,book_id));meta=projects.read(con,book_id)
    records=[p for c in book.chapters for p in [*c['headings'],*c['paragraphs']]]
    before=con.execute('SELECT ai_completed FROM proof_scores WHERE book_id=?',(book_id,)).fetchone()
    ai=bool(before and before[0]) or meta.get('ai_proofread_complete',False)
    # Existing successful whole-book jobs also qualify when counters are added.
    ai=ai or bool(con.execute("SELECT 1 FROM ai_jobs j WHERE book_id=? AND scope='book' AND status='completed' AND EXISTS(SELECT 1 FROM ai_items i WHERE i.job_id=j.id AND i.status='done') LIMIT 1",(book_id,)).fetchone())
    units=[(book_id,p['id'],p.get('unit_version',1),int(reviews.summary(meta,reviews.record_details(p))['confirmed'])) for p in records]
    con.execute('DELETE FROM proof_score_units WHERE book_id=?',(book_id,))
    con.executemany('INSERT INTO proof_score_units VALUES (?,?,?,?)',units)
    con.execute('INSERT INTO proof_scores VALUES (?,?,?,?,0) ON CONFLICT(book_id) DO UPDATE SET total=excluded.total,reviewed=excluded.reviewed,ai_completed=excluded.ai_completed,epoch=proof_scores.epoch+1',(book_id,len(units),sum(r[3] for r in units),int(ai)))


def refresh_unit(con,book_id,pid,details,meta):
    from . import reviews
    row=con.execute('SELECT reviewed FROM proof_score_units WHERE book_id=? AND unit_id=?',(book_id,pid)).fetchone()
    if row is None:return  # Structure changes rebuild the denominator once.
    confirmed=int(reviews.summary(meta,details)['confirmed'])
    con.execute('UPDATE proof_score_units SET version=?,reviewed=? WHERE book_id=? AND unit_id=?',(details.get('unit_version',1),confirmed,book_id,pid))
    con.execute('UPDATE proof_scores SET reviewed=reviewed+?,epoch=epoch+1 WHERE book_id=?',(confirmed-row[0],book_id))


def complete_ai(con,book_id):
    from . import projects
    con.execute('UPDATE proof_scores SET ai_completed=1,epoch=epoch+1 WHERE book_id=?',(book_id,))
    meta=projects.read(con,book_id)
    if not meta.get('ai_proofread_complete'):
        meta['ai_proofread_complete']=True;meta['version']+=1;projects.write(con,book_id,meta)


def read(con,book_id):
    row=con.execute('SELECT total,reviewed,ai_completed,epoch FROM proof_scores WHERE book_id=?',(book_id,)).fetchone()
    if row is None:return None
    total,reviewed,ai,epoch=row;human=round(50*reviewed/total,1) if total else 0
    return dict(book_id=book_id,version=epoch,total=total,reviewed=reviewed,ai_completed=bool(ai),ai_points=50 if ai else 0,review_points=human,score=round((50 if ai else 0)+human,1))
