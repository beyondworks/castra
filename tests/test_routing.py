#!/usr/bin/env python3
"""Invocation boundaries and event-based checkpoint restoration."""
import importlib.util
import json
import os
import hashlib
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import castra_runtime as runtime
spec = importlib.util.spec_from_file_location('route', ROOT / 'hooks/castra-route.py')
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)

class Checks(unittest.TestCase):
    def use_home(self, home):
        # Session state lives under CASTRA_HOME; hooks and in-process reads must agree.
        env = patch.dict(os.environ, {'CASTRA_HOME': str(home)})
        env.start()
        self.addCleanup(env.stop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.use_home(Path(tmp.name) / 'castra-home')

    def test_explicit_only(self):
        for p, mode in [('castra: run fix bug','run'),('/castra:castra resume','resume'),('/castra review patch','review'),('castra: status','status'),('castra:plain','plain'),('/castra reframe','reframe'),('castra: finish','finish')]:
            self.assertEqual(route.route(p), mode)
        for p in ['explain castra', '```\ncastra: run\n```', 'do not use castra', '/castrax run']:
            self.assertIsNone(route.route(p))

    def test_prompt_resets_only_its_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'a.py';p.write_text('pass\n')
            for sid in ('one','two'):
                runtime.record_edit(tmp,sid,p)
                runtime.stop_decision(tmp,sid,False)
            result=subprocess.run([sys.executable,str(ROOT/'hooks/castra-route.py')],input=json.dumps({'session_id':'one','cwd':tmp,'prompt':'ordinary steering'}),capture_output=True,text=True)
            self.assertEqual(result.returncode,0)
            self.assertEqual(runtime.status(tmp,'one')['stop_blocks'],0)
            self.assertEqual(runtime.status(tmp,'two')['stop_blocks'],1)

    def test_compact_restores_own_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ);env.pop('CASTRA_NOTES_DIR',None)
            for sid in ('one','two'):
                subprocess.run([sys.executable,str(ROOT/'scripts/castra_notes.py'),'checkpoint','--session',sid,'--goal',sid+'-goal','--next',sid+'-next'],cwd=tmp,env=env,capture_output=True,check=True)
            proc=subprocess.run([sys.executable,str(ROOT/'hooks/castra-posture.py')],cwd=tmp,env=env,input=json.dumps({'session_id':'one','cwd':tmp,'source':'compact'}),text=True,capture_output=True)
            self.assertIn('one-goal',proc.stdout)
            self.assertIn('one-next',proc.stdout)
            self.assertNotIn('two-goal',proc.stdout)
            self.assertLess(len(proc.stdout.encode()),12000)

    def isolated_hooks(self, tmp):
        base = Path(tmp) / 'install'
        for directory in ('hooks', 'scripts', 'packs'):
            (base / directory).mkdir(parents=True)
        for relative in ('hooks/castra-route.py', 'hooks/castra-posture.py',
                         'scripts/castra_runtime.py', 'scripts/castra_notes.py',
                         'scripts/castra_contract.py'):
            shutil.copyfile(ROOT / relative, base / relative)
        self.write_pack(base, 'initial')
        self.use_home(base)
        return base

    def write_pack(self, base, text):
        (base / 'packs/execution-posture-pack.txt').write_text(
            '<castra_execution_posture>\n' + text + '\n</castra_execution_posture>')

    def hook(self, base, cwd, session='one', prompt='continue', event='route', source='startup'):
        proc = subprocess.run([sys.executable, str(base / ('hooks/castra-' + event + '.py'))],
            input=json.dumps({'session_id': session, 'cwd': str(cwd), 'prompt': prompt, 'source': source}),
            env=dict(os.environ, CASTRA_HOME=str(base)), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        return proc.stdout

    def test_start_records_emission_and_changed_pack_refreshes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            file = Path(tmp) / 'a.py'; file.write_text('pass\n')
            runtime.record_edit(tmp, 'one', file)
            output = self.hook(base, tmp, event='posture')
            self.assertIn('initial', output)
            state = runtime.status(tmp, 'one')
            self.assertEqual(state['execution_contract_sha256'], hashlib.sha256(
                (base / 'packs/execution-posture-pack.txt').read_bytes()).hexdigest())
            self.assertEqual(state['files'][str(file.resolve())]['status'], 'pending')
            self.assertEqual(self.hook(base, tmp), '')
            self.write_pack(base, 'updated-in-this-turn')
            result = json.loads(self.hook(base, tmp))['hookSpecificOutput']['additionalContext']
            self.assertIn('updated-in-this-turn', result)
            self.assertEqual(result.count('<castra_execution_posture>'), 1)
            self.assertEqual(self.hook(base, tmp), '')
            self.assertEqual(runtime.status(tmp, 'one')['files'], state['files'])

    def test_unemitted_sessions_are_isolated_and_plain_does_not_mark_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            plain = self.hook(base, tmp, prompt='/castra plain')
            self.assertNotIn('<castra_execution_posture>', plain)
            self.assertNotIn('execution_contract_sha256', runtime.status(tmp, 'one'))
            self.assertIn('initial', self.hook(base, tmp))
            self.assertEqual(self.hook(base, tmp), '')
            self.assertIn('initial', self.hook(base, tmp, session='two'))
            self.assertEqual(self.hook(base, tmp, session='two'), '')
            self.write_pack(base, 'new')
            self.hook(base, tmp, session='one')
            self.assertNotEqual(runtime.status(tmp, 'one')['execution_contract_sha256'],
                                runtime.status(tmp, 'two')['execution_contract_sha256'])

    def test_explicit_modes_restore_once_per_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            self.hook(base, tmp)
            for mode in ('run', 'review', 'verify', 'resume', 'status', 'reframe', 'finish'):
                out = json.loads(self.hook(base, tmp, prompt='/castra ' + mode))
                context = out['hookSpecificOutput']['additionalContext']
                self.assertEqual(context.count('<castra_execution_posture>'), 1)
                self.assertEqual(context.count('Castra mode: ' + mode), 1)
            self.assertEqual(self.hook(base, tmp), '')

    def test_startup_first_explicit_prompt_deduplicates_and_later_call_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            for source in ('startup', 'compact', 'resume'):
                output = self.hook(base, tmp, event='posture', source=source)
                self.assertIn('<castra_execution_posture>', output)
                first = self.hook(base, tmp, prompt='/castra run')
                self.assertNotIn('<castra_execution_posture>', first)
                self.assertIn('Castra mode: run', first)
                self.assertEqual(self.hook(base, tmp), '')
                later = self.hook(base, tmp, prompt='/castra reframe')
                self.assertEqual(later.count('<castra_execution_posture>'), 1)
                self.assertEqual(self.hook(base, tmp), '')

    def test_plain_consumes_initial_prompt_without_loading_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            self.hook(base, tmp, event='posture')
            pack = base / 'packs/execution-posture-pack.txt'
            original = pack.read_bytes(); pack.unlink()
            plain = json.loads(self.hook(base, tmp, prompt='/castra plain'))
            self.assertNotIn('systemMessage', plain)
            self.assertNotIn('<castra_execution_posture>', str(plain))
            pack.write_bytes(original)
            self.assertIn('<castra_execution_posture>', self.hook(base, tmp, prompt='/castra finish'))

    def test_changed_contract_is_not_suppressed_on_initial_explicit_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            self.hook(base, tmp, event='posture')
            self.write_pack(base, 'changed-after-startup')
            output = self.hook(base, tmp, prompt='/castra run')
            self.assertIn('changed-after-startup', output)
            self.assertEqual(output.count('<castra_execution_posture>'), 1)
            self.assertEqual(self.hook(base, tmp), '')

    def test_invalid_pack_never_records_success_and_recovers_after_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            pack = base / 'packs/execution-posture-pack.txt'
            for content in (None, b'', b'invalid boundaries', b'\xff', b'x' * 10241):
                if content is None:
                    pack.unlink(missing_ok=True)
                else:
                    pack.write_bytes(content)
                for event in ('route', 'posture'):
                    output = self.hook(base, tmp, event=event)
                    self.assertIn('freshness is unverified', output)
                    self.assertNotIn('execution_contract_sha256', runtime.status(tmp, 'one'))
            self.write_pack(base, 'repaired')
            self.assertIn('repaired', self.hook(base, tmp))
            self.assertEqual(self.hook(base, tmp), '')

    def test_corrupt_runtime_is_preserved_and_failure_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            directory = base / 'sessions'; directory.mkdir(parents=True)
            path = directory / (hashlib.sha256(b'one').hexdigest() + '.json')
            path.write_text('not-json')
            result = json.loads(self.hook(base, tmp))
            self.assertIn('freshness is unverified', result['systemMessage'])
            self.assertNotIn('hookSpecificOutput', result)
            self.assertEqual(path.read_text(), 'not-json')

    def test_standalone_and_plugin_use_same_pack_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.isolated_hooks(tmp)
            standalone = Path(tmp) / 'claude-hooks'; standalone.mkdir()
            for name in ('castra-route.py', 'castra-posture.py'):
                shutil.copyfile(base / 'hooks' / name, standalone / name)
            env = dict(os.environ, CASTRA_HOME=str(base))
            payload = json.dumps({'session_id':'standalone', 'cwd':tmp, 'prompt':'continue'})
            proc = subprocess.run([sys.executable, str(standalone / 'castra-posture.py')],
                                  input=payload, env=env, text=True, capture_output=True)
            self.assertIn('initial', proc.stdout)
            self.write_pack(base, 'standalone-update')
            proc = subprocess.run([sys.executable, str(standalone / 'castra-route.py')],
                                  input=payload, env=env, text=True, capture_output=True)
            self.assertIn('standalone-update', proc.stdout)
            self.assertEqual(runtime.status(tmp, 'standalone')['execution_contract_sha256'],
                             hashlib.sha256((base / 'packs/execution-posture-pack.txt').read_bytes()).hexdigest())

    def test_guardian_confirmation_uses_actual_permission_field(self):
        proc=subprocess.run([sys.executable,str(ROOT/'hooks/castra-guardian.py')],input=json.dumps({'tool_name':'Bash','tool_input':{'command':'git reset --hard'},'transcript_path':''}),text=True,capture_output=True)
        self.assertEqual(json.loads(proc.stdout)['hookSpecificOutput']['permissionDecision'],'ask')

    def guardian(self, command, mode=None):
        payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'transcript_path': ''}
        if mode:
            payload['permission_mode'] = mode
        proc = subprocess.run([sys.executable, str(ROOT/'hooks/castra-guardian.py')], input=json.dumps(payload),
                              text=True, encoding='utf-8', errors='replace', capture_output=True)
        return json.loads(proc.stdout).get('hookSpecificOutput', {})

    def test_guardian_never_prompts_in_auto_or_bypass(self):
        # Every guardian "ask" in 356 sessions was approved and the command ran
        # unchanged. In modes where the user chose no interruptions, the reason
        # reaches the model as context and no dialog opens.
        for mode in ('auto', 'bypassPermissions'):
            out = self.guardian('git reset --hard', mode)
            self.assertNotIn('permissionDecision', out, mode)
            self.assertIn('not prompted', out.get('additionalContext', ''), mode)
        for mode in ('default', 'acceptEdits', 'dontAsk'):
            self.assertEqual(self.guardian('git reset --hard', mode).get('permissionDecision'), 'ask', mode)

    def test_guardian_hand_off_is_still_denied_in_bypass(self):
        # A deny opens no dialog, so it is not what the user asked to remove.
        for mode in ('auto', 'bypassPermissions', None):
            self.assertEqual(self.guardian('cat .env', mode).get('permissionDecision'), 'deny', mode)

if __name__=='__main__':unittest.main()
