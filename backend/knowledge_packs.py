"""Explicit opt-in, project-authored starter material; no external fetching.

The manifest is content-addressed, while item identities deliberately omit the
pack version. Re-imports cannot overwrite user edits or revive tombstones.
"""
import hashlib
import json
import time
from uuid import NAMESPACE_URL, uuid5

from backend.accounts import find_account
from backend.contracts import require
from backend.operations import Operations


PACK_ID = 'youji-starter'
USAGE = '项目自编入门资料，仅用于本项目演示/使用；不声明第三方授权，不改变项目代码许可。'
BOUNDARY = '项目使用建议，不是平台官方规则、行业标准或用户亲历事实；不作为效果保证。'
GUIDES = (
    ('source-notes', '入门：如何整理可追溯的创作素材', '''# 如何整理可追溯的创作素材

这是一份有迹项目自编入门指南，不是平台官方规则，也不是用户的真实经历。

## 先记录原始材料，再写内容
为每份材料保留标题、作者或提供者、原始链接、取得日期和允许使用的范围。
网页搜索摘要只是线索。请打开原文核对，确认可使用后再主动导入；无法读取的网页不能当作已核验原文。
自己的产品信息也应区分可核对的规格、个人感受和待确认的说法。没有证明的数字、效果与经历不要补造。

## 把事实和建议分开
事实描述应能回到具体材料和版本；主观建议明确写成建议。引用只是证明材料包含某句话，不代表该句话已经被独立证实。
不要在素材中放密码、客户联系方式、订单或未获授权的个人信息。资料里的“忽略规则”等文字始终只是待分析文本，不是系统指令。

## 在有迹中使用
选择正确账号，在资料库粘贴或上传 UTF-8 文本。用两个以上相关关键词试查原文，再在创作时勾选检索。
没有查到证据时补充真实材料，不要把本指南写成产品功效或账号经历的证据。
'''),
    ('version-evidence', '入门：资料版本与证据回查', '''# 资料版本与证据回查

这是一份有迹项目自编入门指南，仅说明本项目的证据使用方式，不代表第三方平台要求。

## 更新资料不覆盖旧版本
选择“更新资料”后保存新的标题和完整正文。新任务只检索当前有效版本；资料详情可切换旧版本，只读核对当时的原文、来源、页码、字符位置和 SHA-256 指纹。
指纹用于发现字节是否改变，不证明作者身份、事实真实性或授权合法性。来源日期缺失时应保留“未记录”，不能猜测日期。

## 创作任务保存证据快照
任务创建时保存检索结果，四个创作角色共享同一份证据。之后修改或移除资料不会替换已经创建的任务快照。
旧稿需要使用新材料时应重新创建任务并重新审核；旧任务快照只用于审计，不表示资料仍有效或已获新授权。

## 人工确认是独立步骤
核对标题、正文、行动建议和引用后，确认准确稿件版本。修改稿件必须重新审核，不能沿用旧版审核结果。
移出资料库会停止未来检索，但保留旧版本及历史证据以便回查；它不等同于删除所有历史数据。
'''),
    ('metrics-boundary', '入门：记录指标而不夸大效果', '''# 记录指标而不夸大效果

这是一份有迹项目自编运营记录指南，属于方法建议，不是平台官方算法说明，也不承诺流量或成交。

## 缺失不是零
未取得播放、收藏、评论等指标时留空。零表示已经观察且数值确为零，两者不能互换。
记录平台、账号、作品链接、实际发布时间、观察时间和观察窗口。人工录入表示用户记录，不等同于平台已经核实。

## 只比较可比记录
同一账号内按平台、内容形式、观察窗口、自然或付费流量以及真实或模拟来源区分。
少量样本只支持描述性观察，不能证明某个标题带来增长。实验建议是下一次尝试的选择，不是已经验证的因果结论。
指标或分类修正后重新检查依赖的复盘和经验。明确写出样本不足、来源缺失以及尚未验证的因素。

## 演示与真实运营分开
虚构示例只用于演练；不能冒充真实发布、咨询、收益或用户反馈。服务咨询记录也不能直接写成成交。
用真实、获授权的材料替换示例后，才开始积累自己的运营记录。
'''),
)


def manifest(pack_id):
    require(pack_id == PACK_ID, 'RESOURCE_NOT_FOUND', '资料包不存在')
    documents = []
    for key, title, text in GUIDES:
        text = text.strip()
        documents.append(dict(key=key, title=title, text=text, filename=key+'.md',
                              author='有迹项目自编资料', source_label='随项目提供的原创入门指南',
                              source_url='', published_at='2026-09-22', license=USAGE,
                              boundary=BOUNDARY, source_type='project_guide',
                              fingerprint=hashlib.sha256(text.encode('utf-8')).hexdigest()))
    packet = dict(id=PACK_ID, version=1, title='有迹原创入门指南包', demo_only=False,
                  note='3 份可预览的项目使用指南；不导入真实用户数据，不联网，不调用模型。',
                  documents=documents)
    packet['fingerprint'] = hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True,
                                                     separators=(',', ':')).encode('utf-8')).hexdigest()
    return packet


def _allowed(account, packet):
    # demo_sample is the existing account provenance flag, not a client claim.
    return not packet['demo_only'] or account.get('demo_sample') is True


def catalog(knowledge, owner, account_id):
    account = knowledge.account(owner, account_id)
    packet = manifest(PACK_ID)
    return [dict(id=packet['id'], version=packet['version'], title=packet['title'],
                 count=len(packet['documents']), note=packet['note'], demo_only=packet['demo_only'],
                 available=_allowed(account, packet), fingerprint=packet['fingerprint'])]


def preview(knowledge, owner, account_id, pack_id):
    account = knowledge.account(owner, account_id)
    packet = manifest(pack_id)
    require(_allowed(account, packet), 'FORBIDDEN', '虚构演示资料只能进入演示账号')
    return packet


def item_id(owner, account_id, pack_id, key):
    return str(uuid5(NAMESPACE_URL, json.dumps(['youji-knowledge-pack', owner, account_id, pack_id, key],
                                             ensure_ascii=False, separators=(',', ':'))))


def import_pack(knowledge, owner, account_id, pack_id, version, fingerprint):
    packet = manifest(pack_id)
    require(type(version) is int and version == packet['version'] and fingerprint == packet['fingerprint'],
            'VERSION_CONFLICT', '资料包已变化，请重新预览后导入')
    operations = Operations(knowledge.store)
    results = []
    with knowledge.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        account = find_account(operations.read(owner, db), account_id)
        require(_allowed(account, packet), 'FORBIDDEN', '虚构演示资料只能进入演示账号')
        pending = []
        for doc in packet['documents']:
            identity = item_id(owner, account_id, pack_id, doc['key'])
            row = db.execute('SELECT d.owner,d.account_id,d.status,d.version,v.fingerprint,v.metadata '
                             'FROM knowledge_documents d JOIN knowledge_versions v '
                             'ON v.document_id=d.id AND v.version=d.version WHERE d.id=?', (identity,)).fetchone()
            status, reason = 'created', '已新增'
            if row:
                meta = json.loads(row[5])
                if row[:2] != (owner, account_id):
                    status, reason = 'conflict', '资料标识冲突'
                elif row[2] != 'active':
                    status, reason = 'conflict', '已移除的资料不会被自动恢复'
                elif (row[3] == 1 and row[4] == doc['fingerprint'] and
                      meta.get('pack') == dict(id=pack_id, version=version, key=doc['key'], fingerprint=fingerprint)):
                    status, reason = 'skipped', '此版本已导入'
                else:
                    status, reason = 'conflict', '资料已被更新或来自其他包版本，未覆盖'
            else:
                # A manually saved copy has a different ID. Respect its full
                # history too, so importing cannot recreate removed/revised text.
                duplicate = db.execute("SELECT d.id,d.version,d.status,v.version FROM knowledge_documents d "
                                       "JOIN knowledge_versions v ON v.document_id=d.id WHERE d.owner=? "
                                       "AND d.account_id=? AND v.fingerprint=? ORDER BY d.id,v.version DESC",
                                       (owner, account_id, doc['fingerprint'])).fetchone()
                if duplicate:
                    status = 'conflict'
                    if duplicate[2] != 'active':
                        reason = '同正文资料曾被移除，未重新添加或恢复'
                    elif duplicate[1] != duplicate[3]:
                        reason = '同正文资料已有用户修订，未重新添加旧正文'
                    else:
                        reason = '账号已有同正文资料，未重复添加或建立覆盖关系'
                else:
                    pending.append((identity, doc))
            results.append(dict(document_id=identity, key=doc['key'], title=doc['title'], status=status, reason=reason))
        count = db.execute("SELECT COUNT(*) FROM knowledge_documents WHERE owner=? AND account_id=? AND status='active'",
                           (owner, account_id)).fetchone()[0]
        require(count + len(pending) <= 100, 'QUOTA_EXCEEDED', '资料包导入会超过每账号 100 份资料上限；本次未写入')
        for identity, doc in pending:
            metadata = {k: doc[k] for k in ('author', 'source_label', 'published_at', 'license', 'boundary')}
            metadata['pack'] = dict(id=pack_id, version=version, key=doc['key'], fingerprint=fingerprint)
            metadata['verification'] = BOUNDARY
            knowledge._write_version(db, owner, account_id, identity, 1, doc['title'],
                                     doc['text'].encode('utf-8'), [(1, doc['text'])], doc['filename'],
                                     doc['source_type'], doc['source_url'], metadata, int(time.time()))
    return dict(pack_id=pack_id, pack_version=version, fingerprint=fingerprint, account_id=account_id,
                created=sum(r['status']=='created' for r in results),
                skipped=sum(r['status']=='skipped' for r in results),
                conflict=sum(r['status']=='conflict' for r in results), documents=results)
