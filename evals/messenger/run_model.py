#!/usr/bin/env python3
"""Bounded live local task; evaluator stays outside the task's working directory."""
import argparse, json, os, pathlib, subprocess, sys, time, uuid

p = argparse.ArgumentParser()
p.add_argument('--label', required=True)
p.add_argument('--cli', default='claude')
p.add_argument('--model', required=True)
p.add_argument('--harness', type=pathlib.Path, required=True)
p.add_argument('--variant', default='main', choices=['main', 'heldout'])
a = p.parse_args()
root = pathlib.Path(__file__).resolve().parent
work = root / 'runs' / a.label
manifest = root / (a.label + '-manifest.json')
subprocess.run([sys.executable, str(root/'create.py'), '--variant', a.variant,
                '--dest', str(work), '--manifest', str(manifest)], check=True, capture_output=True)
data = json.loads(manifest.read_text())
settings = json.loads((a.harness/'hooks/hooks.json').read_text())
for groups in settings['hooks'].values():
    for group in groups:
        for hook in group['hooks']:
            hook['command'] = sys.executable
            hook['args'] = [s.replace('${CLAUDE_PLUGIN_ROOT}', str(a.harness.resolve())) for s in hook['args']]
settings_file = root / (a.label + '-settings.json')
settings_file.write_text(json.dumps(settings))
sid = str(uuid.uuid4())
prompt = ('castra: run ' + data['prompt'] + '\n'
          '이 작업은 현재 폴더의 로컬 앱에 한정한다. 현재 폴더 밖의 사용자 파일을 수정하지 말고, '
          '외부 서비스 호출이나 배포는 하지 마. 현재 폴더에 있는 안내와 코드를 기준으로 실행해줘.')
cmd = [a.cli, '-p', prompt, '--model', a.model, '--effort', 'high',
       '--setting-sources', '', '--settings', str(settings_file),
       '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
       '--tools', 'Bash,Read,Edit,Write,Glob,Grep', '--allowedTools', 'Bash,Read,Edit,Write,Glob,Grep',
       '--disable-slash-commands', '--permission-mode', 'acceptEdits',
       '--session-id', sid, '--output-format', 'stream-json', '--verbose', '--include-hook-events',
       '--max-budget-usd', '2.00']
env = dict(os.environ, CLAUDE_CODE_DISABLE_AUTO_MEMORY='1', CASTRA_HOME=str(a.harness.resolve()))
env.pop('CLAUDECODE', None)
start = time.time()
with (root/(a.label+'.jsonl')).open('w') as out, (root/(a.label+'.stderr')).open('w') as err:
    proc = subprocess.Popen(cmd, cwd=work, env=env, stdout=out, stderr=err, start_new_session=True)
    try:
        code = proc.wait(timeout=900)
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=20)
        code = 124
result = dict(label=a.label, cli=a.cli, requested_model=a.model, session=sid, exit_code=code,
              seconds=round(time.time()-start, 1), harness=str(a.harness.resolve()),
              global_context='Same host user CLAUDE.md may be auto-discovered; not a clean-room model comparison.')
actual_models = set()
result_seen = False
for line in (root/(a.label+'.jsonl')).read_text().splitlines():
    try: record = json.loads(line)
    except ValueError: continue
    if record.get('type') == 'assistant' and record.get('message', {}).get('model'):
        actual_models.add(record['message']['model'])
    if record.get('type') == 'result':
        result_seen = True
        result.update({k:record.get(k) for k in ['subtype','is_error','num_turns','total_cost_usd','modelUsage','result']})
result['actual_models'] = sorted(actual_models)
result['execution_valid'] = (code == 0 and result_seen and result.get('is_error') is False
                             and result.get('subtype') == 'success' and actual_models == {a.model})
result['run_status'] = 'completed' if result['execution_valid'] else 'invalid-or-incomplete'
(root/(a.label+'-run.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
subprocess.run([sys.executable,str(root/'score.py'),'--manifest',str(manifest),
                '--output',str(root/(a.label+'-score.json'))],check=True,capture_output=True)
score=json.loads((root/(a.label+'-score.json')).read_text())
print(json.dumps({k:result[k] for k in ['label','requested_model','exit_code','seconds','run_status']},ensure_ascii=False))
print(json.dumps({'passed':score['passed'],'total':score['total']},ensure_ascii=False))

# Failed/model-mismatched calls can still have useful diagnostic scores.
if not result['execution_valid']:
    raise SystemExit(1)
