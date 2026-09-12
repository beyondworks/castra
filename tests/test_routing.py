#!/usr/bin/env python3
"""Invocation boundaries and event-based checkpoint restoration."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import castra_runtime as runtime
spec = importlib.util.spec_from_file_location('route', ROOT / 'hooks/castra-route.py')
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)

class Checks(unittest.TestCase):
    def test_explicit_only(self):
        for p, mode in [('castra: run fix bug','run'),('/castra:castra resume','resume'),('/castra review patch','review'),('castra: status','status'),('castra:plain','plain')]:
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
            env=dict(os.environ,CASTRA_HOME=str(ROOT));env.pop('CASTRA_NOTES_DIR',None)
            for sid in ('one','two'):
                subprocess.run([sys.executable,str(ROOT/'scripts/castra_notes.py'),'checkpoint','--session',sid,'--goal',sid+'-goal','--next',sid+'-next'],cwd=tmp,env=env,capture_output=True,check=True)
            proc=subprocess.run([sys.executable,str(ROOT/'hooks/castra-posture.py')],cwd=tmp,env=env,input=json.dumps({'session_id':'one','cwd':tmp,'source':'compact'}),text=True,capture_output=True)
            self.assertIn('one-goal',proc.stdout)
            self.assertIn('one-next',proc.stdout)
            self.assertNotIn('two-goal',proc.stdout)
            self.assertLess(len(proc.stdout.encode()),12000)

    def test_guardian_confirmation_uses_actual_permission_field(self):
        proc=subprocess.run([sys.executable,str(ROOT/'hooks/castra-guardian.py')],input=json.dumps({'tool_name':'Bash','tool_input':{'command':'git reset --hard'},'transcript_path':''}),text=True,capture_output=True)
        self.assertEqual(json.loads(proc.stdout)['hookSpecificOutput']['permissionDecision'],'ask')

if __name__=='__main__':unittest.main()
