"""Deterministic acceptance accounting. Evidence is reviewed, never inferred from CI."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SHA = re.compile(r'^[0-9a-f]{40}$')
LEVELS = ('epic', 'story', 'task', 'subtask')

def validate(backlog):
    if backlog['repository_id'] != 1411435489 or backlog['repository'] != 'richardyoann/saas-directeur-editorial':
        raise ValueError('wrong repository')
    items = backlog['items']
    by_id = {i['id']:i for i in items}
    if len(by_id) != len(items):
        raise ValueError('duplicate IDs')
    for i in items:
        level = LEVELS.index(i['kind'])
        if level == 0 and i['parent'] is not None:
            raise ValueError('epic has parent')
        if level and (i['parent'] not in by_id or by_id[i['parent']]['kind'] != LEVELS[level-1]):
            raise ValueError('invalid parent')
        if any(d not in by_id or d == i['id'] for d in i['dependencies']):
            raise ValueError('invalid dependency')
    def visit(key, path):
        if key in path:
            raise ValueError('dependency cycle')
        for dep in by_id[key]['dependencies']:
            visit(dep,path | {key})
    for key in by_id:
        visit(key,set())
    return by_id

def accepted(criterion, evidence, target_sha, now=None):
    if not criterion.get('verified'):
        return False
    e = evidence.get(criterion.get('evidence'))
    if not e or e.get('result') != 'passed' or e.get('commit') != target_sha or not SHA.fullmatch(target_sha):
        return False
    if criterion['id'] not in e.get('criteria',[]) or not e.get('reviewer') or not e.get('url','').startswith('https://github.com/richardyoann/saas-directeur-editorial/'):
        return False
    allowed = ('real','user') if criterion.get('requires_real') else ('automated','real','user')
    if e.get('mode') not in allowed:
        return False
    try:
        stamp=datetime.fromisoformat(e['at'].replace('Z','+00:00'))
        return stamp.tzinfo is not None and stamp <= (now or datetime.now(timezone.utc)) and e.get('superseded') is not True
    except (ValueError,KeyError,TypeError):
        return False

def report(backlog, evidence, sha):
    by_id = validate(backlog)
    # Stories only: never count the same acceptance again at task/subtask level.
    story_results={}
    for i in by_id.values():
        if i['kind']=='story':
            flags=[accepted(c,evidence,sha) for c in i['criteria']]
            story_results[i['id']]={'accepted':sum(flags),'total':len(flags),'complete':bool(flags) and all(flags)}
    accepted_count=sum(v['accepted'] for v in story_results.values())
    total=sum(v['total'] for v in story_results.values())
    def complete(key):
        return story_results[key]['complete'] and all(complete(d) for d in by_id[key]['dependencies'] if d in story_results)
    completion={key:complete(key) for key in story_results}
    for key in story_results:
        story_results[key]['complete']=completion[key]
    blocked={i['id']:[d for d in i['dependencies'] if not story_results.get(d,{}).get('complete',False)] for i in by_id.values() if i['kind']=='story'}
    return dict(commit=sha,accepted=accepted_count,total=total,percent=round(100*accepted_count/total,2) if total else None,stories=story_results,blocked={k:v for k,v in blocked.items() if v},note='Acceptations vérifiées; ne mesure pas la quantité de code existant.')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--backlog',default='pilotage/github-backlog.json')
    p.add_argument('--evidence',default='pilotage/evidence.json')
    p.add_argument('--sha',required=True)
    args=p.parse_args()
    print(json.dumps(report(json.loads(Path(args.backlog).read_text(encoding='utf-8')),json.loads(Path(args.evidence).read_text(encoding='utf-8')),args.sha),ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
