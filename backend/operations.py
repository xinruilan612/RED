"""Local operations demo: owned, versioned records; no external publishing."""
import copy
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from backend.contracts import require, integer
from backend.demo import validate_text
from backend.workflow import digest
from backend.accounts import migrate, find_account, save_account, account_id, new_account
from backend.analytics import AnalyticsAgent, invalidate, refresh_plans
from backend.planning import make_plan, update_plan, update_task
from backend.experiments import recommend

PLATFORMS = ('xiaohongshu', 'douyin')


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    value = validate_text(value, '时间', 80)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        valid = parsed.tzinfo is not None and parsed <= datetime.now(timezone.utc)
    except ValueError:
        valid = False
    require(valid, 'INVALID_INPUT', '时间需包含时区，且不能晚于现在')
    return value


def url(value, platform=None):
    value = validate_text(value, '来源链接', 1000)
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password
        host = (parsed.hostname or '').lower()
    except ValueError:
        valid = False; host = ''
    require(valid, 'INVALID_INPUT', '请填写有效的 http/https 链接')
    if platform:
        domains = {'xiaohongshu': ('xiaohongshu.com', 'xhslink.com'), 'douyin': ('douyin.com', 'iesdouyin.com')}[platform]
        require(any(host == d or host.endswith('.' + d) for d in domains), 'INVALID_INPUT', '作品链接与目标平台不一致')
    return value


def seed():
    ideas = [
        ('秋季通勤：一件白衬衫的三种搭配', 'xiaohongshu', '穿搭', '从已有衣橱入手，展示通勤、周末、约会三种场景。', '适合服饰与生活方式账号；需要自己的实拍素材。'),
        ('新学期，把学习资料整理成一个系统', 'xiaohongshu', '学习', '展示文件命名、课程分类和每周归档的方法。', '适合学生与效率账号；用个人过程支撑建议。'),
        ('30 秒讲清一个穿搭误区', 'douyin', '穿搭', '开场提出问题，中段做对照，结尾给出可尝试的搭配。', '适合短视频口播；需要用户自行拍摄成片。'),
        ('周末城市散步：记录身边的小发现', 'douyin', '生活', '围绕一条真实路线编排开场、沿途细节与结尾。', '适合生活记录；不要虚构店铺、价格和亲历。'),
    ]
    return {'version': 0, 'trends': [dict(id='example-'+str(i), title=t, platform=p, category=c,
            angle=a, reason=r, source_type='example', source_url='', observed_at=None,
            created_at=None) for i,(t,p,c,a,r) in enumerate(ideas)],
            'publications': [], 'metrics': [], 'memories': []}


def item(rows, identity):
    found = next((x for x in rows if x['id'] == identity), None)
    require(found is not None, 'RESOURCE_NOT_FOUND', '记录不可访问')
    return found


class Operations:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS operations (
                owner TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations_commands (
                owner TEXT NOT NULL, key TEXT NOT NULL, hash TEXT NOT NULL, response TEXT NOT NULL,
                PRIMARY KEY(owner,key));''')

    def read(self, owner, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.read(owner, connection)
        row = db.execute('SELECT payload FROM operations WHERE owner=?', (owner,)).fetchone()
        return migrate(json.loads(row[0]) if row else seed(), owner)

    def context(self, owner, data, mode):
        require(isinstance(data, dict) and set(data) <= {'platform','account','account_id','trend_id','experiment_id'}, 'INVALID_INPUT', '运营上下文字段无效')
        platform = data.get('platform', 'xiaohongshu')
        require(platform in PLATFORMS, 'INVALID_INPUT', '平台无效')
        account = validate_text(data.get('account','我的账号'), '账号名称', 80)
        state = self.read(owner)
        profile = find_account(state, data['account_id']) if data.get('account_id') else next((a for a in state['accounts'] if a['platform'] == platform and account in a['aliases']), None)
        if profile:
            require(profile['platform'] == platform, 'INVALID_INPUT', '账号与平台不一致')
            account = profile['name']
        identity = profile['id'] if profile else account_id(owner, platform, account)
        trend = item(state['trends'], data['trend_id']) if data.get('trend_id') else None
        require(not trend or trend['platform'] == platform, 'INVALID_INPUT', '选题平台不一致')
        experiment = item(state['experiments'], data['experiment_id']) if data.get('experiment_id') else None
        require(not experiment or (experiment['account_id'] == identity and experiment['source_type'] == ('simulation' if mode == 'simulation' else 'manual')
                and experiment['status'] == 'accepted'), 'INVALID_INPUT', '实验建议未接受、已失效或不属于当前账号')
        # Demo evidence is never fed into paid/real creation.
        require(not (mode == 'live' and trend and trend['source_type'] == 'example'), 'INVALID_INPUT', '示例选题只用于模拟模式；真实创作请导入自己的来源')
        memories = [copy.deepcopy(m) for m in state['memories'] if m['status'] == 'accepted'
                    and m['platform'] == platform and m.get('account_id') == identity
                    and m['source_type'] == ('simulation' if mode == 'simulation' else 'manual')]
        source = 'simulation' if mode == 'simulation' else 'manual'
        publications = [p for p in state['publications'] if p.get('account_id') == identity
                        and p['provenance'] == source and p['published_at']]
        ids = {p['id'] for p in publications}
        history = [{'id': p['id'], 'title': p['content']['selected_title'], 'published_at': p['published_at'],
                    'format': p['format'], 'pillar': p['pillar'], 'traffic': p['traffic'], 'source_type': p['provenance']}
                   for p in publications[:20]]
        latest = {}
        for metric in state['metrics']:
            if metric['publication_id'] in ids:
                latest[(metric['publication_id'], metric['window'])] = copy.deepcopy(metric)
        return {'platform': platform, 'account': account, 'account_id': identity,
                'profile': copy.deepcopy(profile), 'trend': copy.deepcopy(trend), 'experiment': copy.deepcopy(experiment), 'memories': memories[:5],
                'history': history, 'metrics': list(latest.values())[-60:],
                'competitors': [copy.deepcopy(c) for c in state['competitors'] if c['account_id'] == identity][-10:],
                'preferences': [copy.deepcopy(p) for p in state['preferences'] if p['account_id'] == identity
                                and p['mode'] == mode][-10:]}

    def command(self, owner, command):
        require(set(command) == {'action','payload','version','key'}, 'INVALID_INPUT', '操作字段无效')
        integer(command['version'], 'version')
        key = validate_text(command['key'], '操作标识', 100)
        require(isinstance(command['payload'],dict), 'INVALID_INPUT', '参数无效')
        fingerprint = digest(command)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT hash,response FROM operations_commands WHERE owner=? AND key=?', (owner,key)).fetchone()
            if previous:
                require(previous[0] == fingerprint, 'IDEMPOTENCY_CONFLICT', '操作标识已被使用')
                return json.loads(previous[1])
            state = self.read(owner, db)
            require(state['version'] == command['version'], 'VERSION_CONFLICT', '运营数据已更新，请刷新后重试')
            self.apply(db, owner, state, command['action'], command['payload'])
            state['version'] += 1
            encoded = json.dumps(state, ensure_ascii=False)
            db.execute('INSERT INTO operations VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET payload=excluded.payload', (owner,encoded))
            from backend.database import project_operations
            project_operations(db, owner, state)
            db.execute('INSERT INTO operations_commands VALUES(?,?,?,?)', (owner,key,fingerprint,encoded))
            return state

    def apply(self, db, owner, state, action, data):
        if action == 'load_sample':
            require(not data, 'INVALID_INPUT', '演示数据无需参数')
            require(not any(a.get('demo_sample') for a in state['accounts']), 'DUPLICATE', '已载入演示账号，请从顶部切换')
            account = new_account(str(uuid4()), '衣橱观察 · 演示账号', 'xiaohongshu')
            account.update(demo_sample=True, profile=dict(positioning='大学生的日常衣橱记录', audience='预算有限、希望提高搭配利用率的学生',
                tone='具体、真实、少用夸张承诺', pillars='搭配清单, 衣橱整理, 场景穿搭', goal='观察收藏表现，验证内容是否有参考价值',
                resources='每周可准备三组搭配素材', banned='必爆、保证变美', weekly_frequency=3))
            state['accounts'].append(account)
            for i in range(4):
                published = datetime.now(timezone.utc)-timedelta(days=18-i*4)
                identity = str(uuid4())
                content = dict(selected_title=['白衬衫搭配清单','旧衣橱整理记录','通勤搭配小清单','一件衬衫的三种场景'][i], body='仅用于演示的虚构内容，不代表真实发布。', cta='', tags=[])
                state['publications'].insert(0, dict(id=identity, account_id=account['id'], account=account['name'],
                    platform='xiaohongshu', run_id=None, draft_ref='sample-'+str(uuid4()), review_ref=None,
                    content=content, content_hash=digest(content), mode='simulation', provenance='simulation',
                    format='image_text', pillar='搭配清单', traffic='organic', status='SIMULATED', url=None,
                    created_at=now(), approved_at=None, published_at=published.isoformat()))
                state['metrics'].append(dict(id=str(uuid4()), publication_id=identity, platform='xiaohongshu',
                    account=account['name'], account_id=account['id'], window='24h', source_type='simulation', revision=1,
                    observed_at=(published+timedelta(hours=24)).isoformat(),
                    values=dict(views=1000, likes=30+i*3, saves=[8,10,12,24][i], comments=5, shares=3)))
            return
        if action == 'post_metadata':
            require(set(data) == {'id','format','pillar','traffic'}, 'INVALID_INPUT', '作品分类字段无效')
            pub = item(state['publications'], data['id'])
            require(data['format'] in ('image_text','video') and data['traffic'] in ('organic','paid','unknown'), 'INVALID_INPUT', '内容形式或流量类型无效')
            pillar = validate_text(data['pillar'], '栏目', 80)
            for window in ('24h','72h','7d'):
                invalidate(state, pub['id'], window)
            pub.update(format=data['format'], pillar=pillar, traffic=data['traffic'])
            return
        if action == 'create_plan':
            make_plan(state, data, now()); return
        if action == 'plan_status':
            update_plan(state, data); return
        if action == 'plan_task':
            update_task(state, data); return
        if action == 'analyze':
            require(set(data) == {'id'}, 'INVALID_INPUT', '分析字段无效')
            metric = item(state['metrics'], data['id'])
            require(not any(a['metric_id'] == metric['id'] and a['status'] != 'superseded' for a in state['analyses']), 'DUPLICATE', '该快照已有分析')
            report = AnalyticsAgent().run(state, metric, now())
            state['analyses'].insert(0, report)
            pub = item(state['publications'], metric['publication_id'])
            if report['status'] == 'descriptive':
                state['memories'].insert(0, dict(id=str(uuid4()), account_id=pub['account_id'],
                    platform=pub['platform'], account=pub['account'], publication_id=pub['id'],
                    metric_id=metric['id'], metric_refs=report['metric_refs'], analysis_id=report['id'],
                    window=metric['window'], source_type=metric['source_type'], status='proposed',
                    created_at=now(), sample_size=max(v['sample_size'] for v in report['comparisons'].values())+1,
                    observation='；'.join(report['observations']), text=report['experiment'],
                    limitation='描述性比较，仅建议下一次实验，不证明因果或稳定规律'))
            return
        if action == 'recommend_experiment':
            require(set(data) == {'account_id','source_type','window'}, 'INVALID_INPUT', '实验推荐字段无效')
            state['experiments'].insert(0, recommend(state, data['account_id'], data['source_type'], data['window'], now()))
            return
        if action == 'experiment_status':
            require(set(data) == {'id','status'}, 'INVALID_INPUT', '实验状态字段无效')
            experiment = item(state['experiments'], data['id'])
            require(data['status'] in ('accepted','rejected','revoked'), 'INVALID_INPUT', '实验状态无效')
            require((experiment['status'] == 'proposed' and data['status'] in ('accepted','rejected')) or
                    (experiment['status'] == 'accepted' and data['status'] == 'revoked'), 'INVALID_TRANSITION', '当前实验建议不能执行此操作')
            experiment['status'] = data['status']; experiment['updated_at'] = now()
            return
        if action == 'save_account':
            save_account(state, data)
            return
        if action == 'import_post':
            self.import_post(state, data)
            return
        if action == 'add_competitor':
            require(set(data) == {'account_id','name','url','observation','observed_at'}, 'INVALID_INPUT', '竞品观察字段无效')
            account = find_account(state, data['account_id'])
            state['competitors'].append(dict(id=str(uuid4()), account_id=account['id'],
                name=validate_text(data['name'], '同类账号', 80), url=url(data['url']),
                observation=validate_text(data['observation'], '观察内容', 1500),
                observed_at=timestamp(data['observed_at']), source_type='manual',
                limitation='用户记录的公开观察，未抓取核验；不推断曝光、转化或因果'))
            return
        fields = {
            'add_trend': {'title','platform','category','angle','source_url','observed_at'},
            'prepare': {'run_id','draft_ref'}, 'approve': {'id'},
            'simulate': {'id'}, 'record': {'id','url','published_at'},
            'metrics': {'id','window','views','likes','saves','comments','shares','observed_at'},
            'learn': {'id'}, 'memory': {'id','status'},
        }
        require(isinstance(action,str) and action in fields, 'INVALID_INPUT', '未知运营操作')
        extra_metrics = {'impressions','new_followers','profile_visits','completed_plays','negative_feedback'}
        require((fields[action] <= set(data) <= fields[action] | extra_metrics) if action == 'metrics' else set(data) == fields[action], 'INVALID_INPUT', '操作参数字段无效')
        if action == 'add_trend':
            require(data['platform'] in PLATFORMS, 'INVALID_INPUT', '平台无效')
            source = url(data['source_url']); observed = timestamp(data['observed_at'])
            title = validate_text(data['title'], '选题', 100)
            require(not any(t['source_url'] == source and t['title'] == title for t in state['trends']), 'DUPLICATE', '此来源选题已存在')
            state['trends'].insert(0, dict(id=str(uuid4()), title=title, platform=data['platform'],
                category=validate_text(data['category'],'分类',30), angle=validate_text(data['angle'],'创作角度',500),
                source_type='manual', source_url=source, observed_at=observed, created_at=now(),
                reason='用户导入来源，内容与热度未联网核验。'))
        elif action == 'prepare':
            run = self.store._get(db, data['run_id'], owner)
            require(run.run_status == 'SUCCEEDED' and run.accepted_ref == data['draft_ref'], 'INVALID_TRANSITION', '只有已确认的准确版本可进入发布中心')
            require(not any(p['run_id'] == run.run_id and p['draft_ref'] == run.accepted_ref for p in state['publications']), 'DUPLICATE', '该确认稿已经进入发布中心')
            op = run.context.get('operations', {})
            platform = op.get('platform', 'xiaohongshu'); name = op.get('account', '我的账号')
            identity = op.get('account_id') or account_id(owner, platform, name)
            account = next((a for a in state['accounts'] if a['id'] == identity or (a['platform'] == platform and name in a['aliases'])), None)
            if account is None:
                account = new_account(identity, name, platform); state['accounts'].append(account)
            state['publications'].insert(0, dict(id=str(uuid4()), run_id=run.run_id, draft_ref=run.accepted_ref,
                review_ref=run.review['ref'], content=copy.deepcopy(run.drafts[-1]['content']),
                content_hash=digest(run.drafts[-1]['content']), platform=op.get('platform','xiaohongshu'),
                account=account['name'], account_id=account['id'], mode=run.context.get('mode','simulation'),
                provenance='simulation' if run.context.get('mode','simulation') == 'simulation' else 'manual',
                format='video' if platform == 'douyin' else 'image_text', pillar='未分类', traffic='unknown',
                status='AWAITING_APPROVAL', created_at=now(), approved_at=None, url=None, published_at=None))
        elif action in ('approve','simulate','record'):
            pub = item(state['publications'], data['id'])
            if action == 'approve':
                require(pub['status'] == 'AWAITING_APPROVAL', 'INVALID_TRANSITION', '当前不能重复批准')
                run = self.store._get(db, pub['run_id'], owner)
                require(run.accepted_ref == pub['draft_ref'] and run.review['ref'] == pub['review_ref']
                        and digest(run.drafts[-1]['content']) == pub['content_hash'], 'VERSION_CONFLICT', '确认版本已变化')
                pub.update(status='APPROVED', approved_at=now())
            else:
                require(pub['status'] == 'APPROVED', 'INVALID_TRANSITION', '请先批准准确版本与目标账号')
                if action == 'simulate':
                    require(pub['mode'] == 'simulation', 'INVALID_TRANSITION', '仅模拟创作可演练发布')
                    pub.update(status='SIMULATED', published_at=now())
                else:
                    require(pub['mode'] == 'live', 'INVALID_TRANSITION', '模拟稿不能记录为真实发布')
                    pub.update(status='MANUAL_REPORTED', url=url(data['url'],pub['platform']), published_at=timestamp(data['published_at']))
        elif action == 'metrics':
            pub = item(state['publications'], data['id'])
            require(pub['status'] in ('SIMULATED','MANUAL_REPORTED'), 'INVALID_TRANSITION', '请先完成发布演练或回填真实发布记录')
            require(data['window'] in ('24h','72h','7d'), 'INVALID_INPUT', '统计窗口无效')
            observed = timestamp(data['observed_at'])
            require(datetime.fromisoformat(observed.replace('Z','+00:00')) >= datetime.fromisoformat(pub['published_at'].replace('Z','+00:00')), 'INVALID_INPUT', '观察时间不能早于发布时间')
            values = {}
            for name in ('views','likes','saves','comments','shares','impressions','new_followers','profile_visits','completed_plays','negative_feedback'):
                value = data.get(name)
                require(value is None or (type(value) is int and 0 <= value <= 10000000000), 'INVALID_INPUT', '指标须为非负整数，未知请留空')
                values[name] = value
            require(values['completed_plays'] is None or (pub['format'] == 'video' and (values['views'] is None or values['completed_plays'] <= values['views'])), 'INVALID_INPUT', '完整播放指标仅用于视频，且不能大于播放数')
            require(any(v is not None for v in values.values()), 'INVALID_INPUT', '至少录入一个已知指标')
            source = 'simulation' if pub['mode'] == 'simulation' else 'manual'
            prior = [m for m in state['metrics'] if m['publication_id'] == pub['id'] and m['window'] == data['window']]
            metric = dict(id=str(uuid4()), publication_id=pub['id'], platform=pub['platform'], account=pub['account'], account_id=pub['account_id'],
                window=data['window'], observed_at=observed, source_type=source, values=values, revision=len(prior)+1)
            require(not prior or prior[-1]['values'] != values or prior[-1]['observed_at'] != observed, 'DUPLICATE','同一快照已录入')
            state['metrics'].append(metric)
            invalidate(state, pub['id'], data['window'])
            # Corrections invalidate derived lessons, including previously accepted lessons.
            for memory in state['memories']:
                if memory['publication_id'] == pub['id'] and memory['window'] == data['window']:
                    memory['status'] = 'superseded'
        elif action == 'learn':
            metric = item(state['metrics'], data['id'])
            latest = [m for m in state['metrics'] if m['publication_id'] == metric['publication_id'] and m['window'] == metric['window']][-1]
            require(latest['id'] == metric['id'], 'INVALID_TRANSITION', '只能从最新指标快照复盘')
            require(not any(m['metric_id'] == metric['id'] for m in state['memories']), 'DUPLICATE', '该快照已生成复盘')
            pub = item(state['publications'], metric['publication_id']); values = metric['values']
            rate = round(sum(values[k] for k in ('likes','saves','comments','shares')) / values['views'] * 100, 2) if values['views'] and all(values[k] is not None for k in ('likes','saves','comments','shares')) else None
            observation = '互动/阅读或播放比为 '+str(rate)+'%' if rate is not None else '指标不完整，暂不计算互动比'
            suggestion = '下次围绕「'+pub['content']['selected_title'][:55]+'」保留一个相近选题，单独改变开头表达，记录同一窗口表现后再比较。'
            state['memories'].insert(0, dict(id=str(uuid4()), publication_id=pub['id'], metric_id=metric['id'],
                platform=pub['platform'], account=pub['account'], account_id=pub['account_id'], window=metric['window'], source_type=metric['source_type'],
                status='proposed', created_at=now(), sample_size=1, observation=observation,
                text=suggestion, limitation='单篇描述性复盘，不代表因果或稳定规律；需更多同口径样本。'))
        elif action == 'memory':
            memory = item(state['memories'], data['id'])
            require(data['status'] in ('accepted','rejected','revoked'), 'INVALID_INPUT','经验状态无效')
            require((memory['status'] == 'proposed' and data['status'] in ('accepted','rejected')) or
                    (memory['status'] == 'accepted' and data['status'] == 'revoked'), 'INVALID_TRANSITION','当前经验不能执行此操作')
            memory['status'] = data['status']; memory['updated_at'] = now()
            refresh_plans(state)


    def import_post(self, state, data):
        required = {'account_id','title','body','url','published_at','format','pillar','traffic'}
        require(set(data) == required, 'INVALID_INPUT', '历史作品字段无效')
        account = find_account(state, data['account_id'])
        link = url(data['url'], account['platform'])
        require(not any(p['url'] == link for p in state['publications']), 'DUPLICATE', '此作品链接已经导入')
        require(data['format'] in ('image_text','video'), 'INVALID_INPUT', '内容形式无效')
        require(data['traffic'] in ('organic','paid','unknown'), 'INVALID_INPUT', '流量类型无效')
        content = dict(selected_title=validate_text(data['title'], '作品标题', 200),
            body=validate_text(data['body'], '正文或脚本', 6000, True), cta='', tags=[])
        state['publications'].insert(0, dict(id=str(uuid4()), account_id=account['id'], account=account['name'],
            platform=account['platform'], run_id=None, draft_ref='imported-'+str(uuid4()), review_ref=None,
            content=content, content_hash=digest(content), mode='imported', provenance='manual',
            status='MANUAL_REPORTED', created_at=now(), approved_at=None, url=link,
            published_at=timestamp(data['published_at']), format=data['format'],
            pillar=validate_text(data['pillar'], '栏目', 80), traffic=data['traffic'],
            limitation='用户导入已发布作品，未经过本系统创作审核，平台状态尚未独立核实'))
