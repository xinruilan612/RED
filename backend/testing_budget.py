"""Persistent, owner-scoped experiment spending guidance with explicit persistent hard-limit opt-in. Integer micro-CNY accounting.

Pricing: DeepSeek flash peak input 2 CNY / million, output 8 CNY / million.
No cache discount is assumed. Missing usage stays conservatively charged.
"""
from decimal import Decimal
import time
from backend.contracts import require, PARAMETERS

PRICING = 'deepseek-flash peak CNY: input 2/output 8 per million; no cache discount'


def _cost(row):
    actual, reserved, inp, out, provider, model, state, held = row
    require(provider == 'deepseek' and model == 'deepseek-flash',
            'TEST_BUDGET_MODEL', '本轮实验预算仅核准 deepseek-flash，其他模型未调用')
    if type(actual) is int and type(inp) is int and type(out) is int and min(inp,out)>=0 and inp+out==actual:
        return inp*2+out*8
    if actual is None and state == 'calling' and held is not None:
        return held
    return (actual if type(actual) is int and actual>=0 else reserved)*8


def _usage(db, owner):
    rows = db.execute('''SELECT c.actual,c.reserved,a.input_tokens,a.output_tokens,
        a.provider,a.model,c.state,h.reserved_micro FROM live_calls c
        JOIN live_lineage l ON l.run_id=c.run_id
        JOIN testing_budget_roots r ON r.root=l.budget_id AND r.owner=?
        LEFT JOIN model_audit a ON a.call_id=c.id
        LEFT JOIN testing_budget_reservations h ON h.call_id=c.id''',(owner,)).fetchall()
    hard=bool(db.execute('SELECT 1 FROM testing_budget_limits WHERE owner=?',(owner,)).fetchone())
    # Opt-in can include older advisory reservations: revalue unfinished calls at
    # the full all-token ceiling before authorizing any new hard-limit spending.
    return sum(max(_cost(row),row[1]*8) if hard and row[0] is None else _cost(row) for row in rows)


def initialize(store, owner, cap_cny, max_runs=3, existing_run_ids=(), *, hard_limit=False):
    """Explicit administrative opt-in; idempotent and never clears prior charges."""
    require(type(hard_limit) is bool, 'INVALID_INPUT', 'hard_limit 必须是布尔值')
    amount=Decimal(str(cap_cny))*1000000
    require(amount.is_finite() and amount>0 and amount==amount.to_integral_value() and type(max_runs) is int and max_runs>0,
            'INVALID_INPUT','实验预算金额或轮数无效')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT cap_micro,max_runs FROM testing_budgets WHERE owner=?',(owner,)).fetchone()
        require(old is None or tuple(old)==(int(amount),max_runs),'VERSION_CONFLICT','已存在实验预算，不能覆盖或清零')
        db.execute('INSERT INTO testing_budgets VALUES(?,?,?,?) ON CONFLICT(owner) DO NOTHING',(owner,int(amount),max_runs,time.time()))
        if hard_limit:
            db.execute('INSERT INTO testing_budget_limits VALUES(?) ON CONFLICT(owner) DO NOTHING',(owner,))
        for run_id in existing_run_ids:
            run=store._get(db,run_id,owner)
            require(run.workflow_type=='creation' and run.context.get('mode')=='live','INVALID_INPUT','仅可纳入当前真实创作任务')
            db.execute('INSERT INTO live_lineage VALUES(?,?) ON CONFLICT(run_id) DO NOTHING',(run_id,run_id))
            root=db.execute('SELECT budget_id FROM live_lineage WHERE run_id=?',(run_id,)).fetchone()[0]
            db.execute('INSERT INTO testing_budget_roots VALUES(?,?) ON CONFLICT(owner,root) DO NOTHING',(owner,root))
        _usage(db,owner)  # Validate historical model pricing before opting in.
    return public(store,owner)


def reserve(db, run, root, route, messages, call_id):
    budget=db.execute('SELECT cap_micro,max_runs FROM testing_budgets WHERE owner=?',(run.owner_id,)).fetchone()
    if budget is None:return
    require(route.provider=='deepseek' and route.model=='deepseek-flash','TEST_BUDGET_MODEL','本轮实验预算仅核准 deepseek-flash，其他模型未调用')
    require(run.workflow_type=='creation' or (run.workflow_type in ('operations','windtunnel') and run.context.get('paid_scope_confirmed') is True),
            'TEST_BUDGET_SCOPE','此付费功能尚未明确确认；实验费用记录保留')
    held=(sum(len(m['content'].encode()) for m in messages)+256)*2+PARAMETERS['output_tokens_max']*8
    db.execute('INSERT INTO testing_budget_roots VALUES(?,?) ON CONFLICT(owner,root) DO NOTHING',(run.owner_id,root))
    if db.execute('SELECT 1 FROM testing_budget_limits WHERE owner=?',(run.owner_id,)).fetchone():
        # All tokens at the highest rate also covers absent/invalid split usage.
        # Calls invokes this inside BEGIN IMMEDIATE (PG transaction advisory lock).
        held=(sum(len(m['content'].encode()) for m in messages)+256+PARAMETERS['output_tokens_max'])*8
        unknown=db.execute('''SELECT 1 FROM live_calls c
            JOIN live_lineage l ON l.run_id=c.run_id
            JOIN testing_budget_roots r ON r.root=l.budget_id AND r.owner=?
            WHERE c.actual IS NULL AND c.state<>'calling' LIMIT 1''',(run.owner_id,)).fetchone()
        require(not unknown,'USAGE_UNKNOWN','本轮存在用量未知的失败调用；保留全部预留，停止新的收费调用')
        used=_usage(db,run.owner_id)
        require(used+held<=budget[0],'TEST_BUDGET_EXCEEDED',
                f'本轮人民币硬上限 {budget[0]/1e6:.2f} 元，已计入 {used/1e6:.6f} 元，下一步保守预留 {held/1e6:.6f} 元；未发起调用')
    db.execute('INSERT INTO testing_budget_reservations VALUES(?,?)',(call_id,held))


def public(store, owner):
    with store.connect() as db:
        budget=db.execute('SELECT cap_micro,max_runs FROM testing_budgets WHERE owner=?',(owner,)).fetchone()
        if budget is None:return None
        hard=bool(db.execute('SELECT 1 FROM testing_budget_limits WHERE owner=?',(owner,)).fetchone())
        used=_usage(db,owner)
        count=db.execute('SELECT COUNT(*) FROM testing_budget_roots WHERE owner=?',(owner,)).fetchone()[0]
        over_target=used>budget[0] or count>budget[1]
        warning=(f'实验参考目标约 {budget[0]/1e6:.2f} 元 / {budget[1]} 轮，当前保守计入 {used/1e6:.6f} 元、{count} 轮；已超参考目标，仍可继续。' if over_target else (f'已接近 {budget[0]/1e6:.2f} 元参考预算，后续调用可能超出，仍可继续。' if used>=budget[0]*.8 else ''))
        if hard:
            warning=f'人民币硬上限 {budget[0]/1e6:.2f} 元；下一步预留不足或失败调用用量未知时停止调用。'
        return {'hard_limit':hard,'target_cny':budget[0]/1e6,'target_runs':budget[1],
                'over_target':over_target,'warning':warning,'estimated_cost_cny':used/1e6,
                'active':True,'budget_cny':budget[0]/1e6,'spent_cny':used/1e6,
                'remaining_cny':max(0,budget[0]-used)/1e6,'run_limit':budget[1],
                'run_count':count,'remaining_runs':max(0,budget[1]-count),
                'pricing':PRICING,'scope':'persistent_owner_experiment'}
