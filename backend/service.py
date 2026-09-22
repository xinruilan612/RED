"""Application boundary shared by the production API and domain tests."""
from uuid import uuid4
from backend.contracts import require, integer
from backend.demo import validate_brief, validate_edit, actions
from backend.execution import Executor
from backend.operations import Operations
from backend.web import view


class Service:
    def __init__(self, store, config, client=None):
        self.store, self.config = store, config
        from backend.migrations import upgrade
        upgrade(store)
        self.operations = Operations(store)
        self.executor = Executor(store,config,client)
        from backend.knowledge import Knowledge
        self.knowledge = Knowledge(store)
        from backend.jobs import Jobs
        self.jobs=Jobs(store)

    def view(self, run):
        result=view(run,self.executor)
        result['background']=self.jobs.public(run.run_id,run.owner_id)
        result['in_flight']=result.get('in_flight',False) or result['background']['status'] in ('queued','running','pausing')
        return result

    def background(self, owner, run_id, data):
        self.jobs.command(owner,run_id,data)
        return self.view(self.store.get(run_id,owner))

    def create(self, owner, data):
        mode = data.get('mode','simulation')
        workflow = data.get('workflow','professional')
        require(mode in ('simulation','live'), 'INVALID_INPUT', '运行模式无效')
        require(workflow in ('quick','professional'), 'INVALID_INPUT', '创作路径无效')
        require(mode!='live' or self.config.ready, 'KEY_REQUIRED', '请在服务器配置 DeepSeek Key')
        context = validate_brief({k:v for k,v in data.items() if k not in ('mode','workflow','operations','knowledge')})
        context['mode'] = mode
        context['workflow'] = workflow
        context['model_policy'] = self.executor.router.policy()
        if 'operations' in data:
            context['operations'] = self.operations.context(owner,data['operations'],mode)
            promotion = context['operations'].get('promotion')
            if promotion:
                extra = ('推广简报（仅含用户允许公开的信息）：\n' + promotion['material'] +
                         '\n客户问题：' + promotion['customer_problem'] +
                         '\n问题依据：' + promotion['problem_source_label'] +
                         ('\n缺失材料：' + '；'.join(promotion['missing']) if promotion['missing'] else ''))
                merged = (context['material'] + '\n\n' + extra).strip()
                require(len(merged) <= 8000, 'INVALID_INPUT', '推广资料与补充素材合计不能超过 8000 字')
                context['material'] = merged
        selection=data.get('knowledge',{'enabled':False})
        require(isinstance(selection,dict) and set(selection)=={'enabled'} and type(selection['enabled']) is bool,'INVALID_INPUT','资料检索设置无效')
        if selection['enabled']:
            account=context.get('operations',{}).get('account_id')
            require(account,'INVALID_INPUT','请先选择资料所属账号')
            result=self.knowledge.retrieve(owner,account,(context['topic']+' '+context['audience'])[:300])
            context['retrieval']=result
            context['evidence']=result['sources']
        if mode=='live': context['scenario']='standard'
        return self.view(self.store.create(owner,str(uuid4()),context))

    def action(self, owner, run_id, data):
        from backend.schemas import Command, parse
        data = parse(Command, data)
        require(set(data)=={'action','version','key','payload'}, 'INVALID_INPUT', '命令字段无效')
        action, payload = data['action'],data['payload']
        require(isinstance(action,str) and action in ('next','edit','supplement','accept','cancel','recover'), 'INVALID_INPUT', '未知操作')
        integer(data['version'],'version')
        require(isinstance(data['key'],str) and 0<len(data['key'])<=100 and isinstance(payload,dict), 'INVALID_INPUT', '命令参数无效')
        run = self.store.get(run_id,owner)
        if action=='next':
            job=self.jobs.public(run_id,owner)
            require(job['status'] not in ('queued','running','pausing'),'JOB_ACTIVE','任务正在后台执行，请等待或暂停')
            require(job['status']=='idle','INVALID_TRANSITION','此任务使用后台执行，请点击后台继续')
        if action in ('next','cancel','recover'):
            require(not payload,'INVALID_INPUT','此操作无需参数')
        if action=='recover':
            return self.view(self.executor.recover(run_id,owner,data['version']))
        if action=='next' and run.context.get('mode')=='live':
            return self.view(self.executor.step(run_id,owner,data['version'],data['key']))
        command = {'next':'demo_step','supplement':'demo_supplement'}.get(action,action)
        if action=='edit': payload={'content':validate_edit(payload)}
        if action=='supplement': require(set(payload)=={'material','allow_hypothesis'},'INVALID_INPUT','补料字段无效')
        if action=='accept': require(set(payload)=={'draft_ref','review_ref'} and all(isinstance(v,str) for v in payload.values()),'INVALID_INPUT','确认版本无效')
        return self.view(self.store.command(run_id,owner,data['version'],data['key'],command,payload))

    def export(self, owner, run_id):
        run = self.store.get(run_id,owner)
        require('export' in actions(run),'INVALID_TRANSITION','请先确认准确版本')
        c = run.drafts[-1]['content']
        label = 'AI 创作稿（已人工确认；事实仍需核实）' if run.context.get('mode')=='live' else '模拟创作稿（未调用真实 AI）'
        return '# '+label+'\n\n# '+c['selected_title']+'\n\n'+c['body']+'\n\n'+c['cta']+'\n\n'+' '.join('#'+t for t in c['tags'])
