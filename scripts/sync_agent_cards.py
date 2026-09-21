"""Generate merged cards and registry from independent role specifications."""
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
MARKER = '**以下为四份独立 Agent Card 的完整合并内容。**'

def outputs():
    folder = ROOT / 'docs/agents'
    cards = [p.read_text(encoding='utf-8').strip() for p in sorted(folder.glob('0[1-4]*.md'))]
    overview = folder / '00_overview_and_all_agents.md'
    merged = overview.read_text(encoding='utf-8').split(MARKER)[0] + MARKER + '\n\n---\n\n' + '\n\n---\n\n'.join(cards) + '\n'
    rows, skills = [], []
    for card in cards:
        role = re.search(r'Agent ID.*?`([^`]+)`', card).group(1)
        part = card.split('## 5. 允许的 Tools')[1].split('## 6.')[0]
        for name, behavior, limit in re.findall(r'^\| `([^`]+)` \| (.*?) \| (.*?) \|$', part, re.M):
            rows.append(f'| {role} | `{name}` | {behavior} | {limit} |')
        part = card.split('## 6. 允许的 Skills')[1].split('## 7.')[0]
        for name, method in re.findall(r'^- `([^`]+)`：(.*)$', part, re.M):
            skills.append(f'| {role} | `{name}` | {method} |')
    registry = '# Tool / Skill 注册表\n\n由 scripts/sync_agent_cards.py 从独立角色卡生成，请勿直接编辑。所有接口均为设计，尚未实现。权限另由 design_contract.json 校验。\n\n## Tools\n\n| 角色 | ID | 行为 | 限制 |\n| --- | --- | --- | --- |\n'+'\n'.join(rows)+'\n\nexport_bundle 仅允许 Orchestrator 服务身份，在有效审核及用户确认后调用；不属于 Agent 权限。公开搜索/抓取默认禁用，启用条件见 [执行协议](AGENT_PROTOCOL.md)。\n\n## Skills\n\n| 角色 | ID | 方法 |\n| --- | --- | --- |\n'+'\n'.join(skills)+'\n'
    return {overview: merged, ROOT/'docs/design/AGENT_REGISTRY.md': registry}

if __name__ == '__main__':
    for path, content in outputs().items():
        path.write_text(content, encoding='utf-8')
