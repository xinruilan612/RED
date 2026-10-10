"""Versioned trusted template directory and transactional account rotation.

Database rows are metadata only; rendering executes repository-owned templates.
"""
import json
from backend.contracts import require
from backend.workflow import digest
from backend.media_exports import confirmed_snapshot

TEMPLATE_IDS = ('xhs-e','xhs-a','xhs-b','xhs-c','xhs-d','xhs-f','xhs-g','xhs-h')


def _catalog(db):
    rows = db.execute('SELECT id,version,name,source_url,source_commit,license FROM media_templates WHERE enabled=1 ORDER BY sort_order,id').fetchall()
    return [dict(id=r[0],version=r[1],name=r[2],source_url=r[3],source_commit=r[4],license=r[5],
                 thumbnail_url='/assets/templates/'+r[0]+'.png') for r in rows if r[0] in TEMPLATE_IDS and r[1] == 1]


def _selection(db, run):
    row = db.execute('SELECT template_id,template_version,draft_ref,content_hash FROM media_template_selection WHERE run_id=? AND owner=?', (run.run_id,run.owner_id)).fetchone()
    if not row or row[2] != run.accepted_ref or row[3] != (run.acceptance or {}).get('content_hash'):
        return None
    return dict(template_id=row[0],template_version=row[1],draft_ref=row[2],content_hash=row[3])


def catalog(store, owner, run_id=None):
    from backend.html_cards import available
    renderer_available = available()
    with store.connect() as db:
        run = store._get(db,run_id,owner) if run_id else None
        return {'available':renderer_available,'templates':_catalog(db),'selection':_selection(db,run) if run else None}


def choose(store, owner, run_id, data):
    require(isinstance(data,dict) and set(data) <= {'action','template_id','draft_ref','content_hash','idempotency_key'}, 'INVALID_INPUT','模板请求字段无效')
    action, key = data.get('action'),data.get('idempotency_key')
    require(isinstance(action,str) and action in ('init','next','select') and isinstance(key,str) and 1<=len(key)<=128, 'INVALID_INPUT','模板操作或幂等键无效')
    require(action=='select' or 'template_id' not in data,'INVALID_INPUT','自动轮换不能指定模板')
    fingerprint = digest({'run_id':run_id,**data})
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        run = store._get(db,run_id,owner)
        snapshot = confirmed_snapshot(run)
        require(data.get('draft_ref')==snapshot['draft_ref'] and data.get('content_hash')==snapshot['content_hash'],'VERSION_CONFLICT','已确认稿件已变化，请重新打开图卡')
        old = db.execute('SELECT fingerprint,response FROM media_template_commands WHERE owner=? AND key=?',(owner,key)).fetchone()
        if old:
            require(old[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他模板操作')
            return json.loads(old[1])
        templates = _catalog(db)
        require(templates,'INVALID_TRANSITION','没有可用图卡模板')
        current = _selection(db,run)
        if action == 'init' and current and current['template_id'] in {t['id'] for t in templates}:
            selected = current
        else:
            if action == 'select':
                template = next((t for t in templates if t['id']==data.get('template_id')),None)
                require(template is not None,'INVALID_INPUT','模板不存在或版本不可用')
            else:
                account = run.context.get('operations',{}).get('account_id') or '__unassigned__'
                row = db.execute('SELECT position FROM media_template_rotation WHERE owner=? AND account_id=?',(owner,account)).fetchone()
                position = row[0]+1 if row else 0
                template = templates[position % len(templates)]
                if action == 'next' and current and len(templates)>1 and template['id']==current['template_id']:
                    position += 1
                    template = templates[position % len(templates)]
                db.execute('INSERT INTO media_template_rotation(owner,account_id,position) VALUES(?,?,?) ON CONFLICT(owner,account_id) DO UPDATE SET position=excluded.position',(owner,account,position))
            selected = dict(template_id=template['id'],template_version=template['version'],draft_ref=snapshot['draft_ref'],content_hash=snapshot['content_hash'])
            db.execute('INSERT INTO media_template_selection(run_id,owner,draft_ref,content_hash,template_id,template_version) VALUES(?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET draft_ref=excluded.draft_ref,content_hash=excluded.content_hash,template_id=excluded.template_id,template_version=excluded.template_version',
                       (run_id,owner,selected['draft_ref'],selected['content_hash'],selected['template_id'],selected['template_version']))
        db.execute('INSERT INTO media_template_commands(owner,key,fingerprint,response) VALUES(?,?,?,?)',(owner,key,fingerprint,json.dumps(selected)))
        return selected
