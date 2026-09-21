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
        self.operations = Operations(store)
        self.executor = Executor(store,config,client)
        from backend.knowledge import Knowledge
        self.knowledge = Knowledge(store)

    def create(self, owner, data):
        mode = data.get('mode','simulation')
        require(mode in ('simulation','live'), 'INVALID_INPUT', '运行模式无效')
        require(mode!='live' or self.config.ready, 'KEY_REQUIRED', '请在服务器配置 DeepSeek Key')
        context = validate_brief({k:v for k,v in data.items() if k not in ('mode','operations','knowledge')})
        context['mode'] = mode
        if 'operations' in data:
            context['operations'] = self.operations.context(owner,data['operations'],mode)
        selection=data.get('knowledge',{'enabled':False})
        require(isinstance(selection,dict) and set(selection)=={'enabled'} and type(selection['enabled']) is bool,'INVALID_INPUT','资料检索设置无效')
        if selection['enabled']:
            account=context.get('operations',{}).get('account_id')
            require(account,'INVALID_INPUT','请先选择资料所属账号')
            result=self.knowledge.retrieve(owner,account,(context['topic']+' '+context['audience'])[:300])
            context['retrieval']=result
            context['evidence']=result['sources']
        if mode=='live': context['scenario']='standard'
        return view(self.store.create(owner,str(uuid4()),context),self.executor)

    def action(self, owner, run_id, data):
        require(set(data)=={'action','version','key','payload'}, 'INVALID_INPUT', '命令字段无效')
        action, payload = data['action'],data['payload']
        require(isinstance(action,str) and action in ('next','edit','supplement','accept','cancel','recover'), 'INVALID_INPUT', '未知操作')
        integer(data['version'],'version')
        require(isinstance(data['key'],str) and 0<len(data['key'])<=100 and isinstance(payload,dict), 'INVALID_INPUT', '命令参数无效')
        run = self.store.get(run_id,owner)
        if action in ('next','cancel','recover'):
            require(not payload,'INVALID_INPUT','此操作无需参数')
        if action=='recover':
            return view(self.executor.recover(run_id,owner,data['version']),self.executor)
        if action=='next' and run.context.get('mode')=='live':
            return view(self.executor.step(run_id,owner,data['version'],data['key']),self.executor)
        command = {'next':'demo_step','supplement':'demo_supplement'}.get(action,action)
        if action=='edit': payload={'content':validate_edit(payload)}
        if action=='supplement': require(set(payload)=={'material','allow_hypothesis'},'INVALID_INPUT','补料字段无效')
        if action=='accept': require(set(payload)=={'draft_ref','review_ref'} and all(isinstance(v,str) for v in payload.values()),'INVALID_INPUT','确认版本无效')
        return view(self.store.command(run_id,owner,data['version'],data['key'],command,payload),self.executor)

    def export(self, owner, run_id):
        run = self.store.get(run_id,owner)
        require('export' in actions(run),'INVALID_TRANSITION','请先确认准确版本')
        c = run.drafts[-1]['content']
        label = 'AI 创作稿（已人工确认；事实仍需核实）' if run.context.get('mode')=='live' else '模拟创作稿（未调用真实 AI）'
        return '# '+label+'\n\n# '+c['selected_title']+'\n\n'+c['body']+'\n\n'+c['cta']+'\n\n'+' '.join('#'+t for t in c['tags'])
