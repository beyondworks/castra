#!/usr/bin/env python3
"""Installer isolation, ownership, integrity, and plugin schema regression checks."""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('castra_install', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='castra space ')
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve()
        self.src, self.home, self.cdir = self.base / 'source', self.base / 'home', self.base / 'claude'
        self.cdir.mkdir()
        self.env = patch.dict(os.environ, {'CASTRA_HOME': str(self.home), 'CLAUDE_CONFIG_DIR': str(self.cdir)})
        self.env.start(); self.addCleanup(self.env.stop)
        self.source_patch = patch.object(installer, 'SRC', self.src)
        self.source_patch.start(); self.addCleanup(self.source_patch.stop)
        names = {n for entries in installer.HOOK_SCRIPTS.values() for _, n in entries}
        for name in names:
            self.put(self.src / 'hooks' / name, 'import sys\nsys.stdin.read()\n')
        for name in ('castra-posture.py', 'castra-route.py'):
            self.put(self.src / 'hooks' / name, (ROOT / 'hooks' / name).read_text())
        for relative in installer.REQUIRED_HOME_FILES:
            self.put(self.src / relative, (ROOT / relative).read_text())
        self.put(self.src / 'skills/castra/SKILL.md', 'castra fixture\n')
        self.put(self.src / 'skills/thinking-map/SKILL.md', 'thinking fixture\n')
        self.put(self.src / 'VERSION', '0.7.0\n')

    def put(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def snapshot(self):
        return {str(p.relative_to(self.base)): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}

    def install(self):
        changes, manifest, originals = installer.plan_install()
        with contextlib.redirect_stdout(io.StringIO()):
            installer.apply_changes(changes, originals)
        return manifest

    def test_dry_run_is_read_only(self):
        before = self.snapshot()
        with patch('sys.argv', ['install.py', '--dry-run']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(), 0)
        self.assertEqual(before, self.snapshot())

    def test_invalid_json_before_mutation(self):
        self.put(self.cdir / 'settings.json', '{bad')
        before = self.snapshot()
        with self.assertRaises(ValueError): installer.plan_install()
        self.assertEqual(before, self.snapshot())

    def test_invalid_hook_schema_before_mutation(self):
        self.put(self.cdir / 'settings.json', '{"hooks":{"Stop":{}}}')
        before = self.snapshot()
        with self.assertRaises(ValueError): installer.plan_install()
        self.assertEqual(before, self.snapshot())

    def test_missing_required_dependencies_rejected_before_writes(self):
        for relative in installer.REQUIRED_HOME_FILES:
            with self.subTest(relative=relative):
                path = self.src / relative
                original = path.read_bytes()
                path.unlink()
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, 'source is incomplete'):
                    installer.plan_install()
                self.assertEqual(before, self.snapshot())
                path.write_bytes(original)

    def test_foreign_hooks_environment_permissions_preserved(self):
        foreign = {'type': 'command', 'command': 'echo castra-guardian.py'}
        settings = {'env': {'MY_FLAG': 'kept'}, 'permissions': {'deny': ['Bash(rm *)']},
                    'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [foreign]}]}}
        self.put(self.cdir / 'settings.json', json.dumps(settings))
        self.install()
        actual = json.loads((self.cdir / 'settings.json').read_text())
        self.assertEqual(settings['env'], actual['env'])
        self.assertEqual(settings['permissions'], actual['permissions'])
        self.assertEqual(actual['hooks']['PreToolUse'][0]['hooks'], [foreign])

    def test_exact_legacy_registration_upgrade(self):
        old = {'type': 'command', 'command': 'python3 ' + __import__('shlex').quote(str(self.cdir / 'hooks/castra-posture.py'))}
        settings = {'hooks': {'SessionStart': [{'hooks': [old]}]}}
        actual = installer.merged_settings(settings, self.cdir / 'hooks')
        self.assertEqual(len(actual['hooks']['SessionStart']), 1)
        self.assertIn('args', actual['hooks']['SessionStart'][0]['hooks'][0])

    def test_spaces_and_idempotent_install(self):
        self.install()
        before = self.snapshot()
        self.install()
        self.assertEqual(before, self.snapshot())
        settings = json.loads((self.cdir / 'settings.json').read_text())
        arg = settings['hooks']['SessionStart'][0]['hooks'][0]['args'][0]
        self.assertEqual(arg, str(self.cdir / 'hooks/castra-posture.py'))

    def test_manifest_covers_skills_hooks_scripts_packs(self):
        manifest = self.install()
        managed = manifest['managed_files']
        for path in (self.cdir / 'skills/castra/SKILL.md', self.cdir / 'hooks/castra-route.py',
                     self.home / 'scripts/castra_notes.py', self.home / 'packs/execution-posture-pack.txt'):
            self.assertEqual(managed[str(path)]['sha256'], installer.digest(path.read_bytes()))

    def test_unknown_thinking_map_preserved(self):
        target = self.cdir / 'skills/thinking-map/SKILL.md'
        self.put(target, 'user-owned version')
        manifest = self.install()
        self.assertEqual(target.read_text(), 'user-owned version')
        self.assertNotIn(str(target), manifest['managed_files'])

    def test_unknown_thinking_map_symlink_preserved(self):
        other = self.base / 'shared-skill'
        self.put(other / 'SKILL.md', 'shared user skill')
        (self.cdir / 'skills').mkdir()
        (self.cdir / 'skills/thinking-map').symlink_to(other, target_is_directory=True)
        self.install()
        self.assertTrue((self.cdir / 'skills/thinking-map').is_symlink())
        self.assertEqual((other / 'SKILL.md').read_text(), 'shared user skill')

    def test_enabled_plugin_prevents_double_registration(self):
        self.put(self.cdir / 'settings.json', '{"enabledPlugins":{"castra@local":true}}')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'plugin is enabled'): installer.plan_install()
        self.assertEqual(before, self.snapshot())

    def test_unknown_castra_collision_rejected(self):
        self.put(self.cdir / 'skills/castra/SKILL.md', 'unowned')
        before = self.snapshot()
        with self.assertRaises(ValueError): installer.plan_install()
        self.assertEqual(before, self.snapshot())

    def test_symlink_destination_rejected(self):
        other = self.base / 'other'; other.mkdir()
        (self.cdir / 'hooks').symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'): installer.plan_install()
        self.assertEqual(list(other.iterdir()), [])

    def test_managed_upgrade_and_timestamp_backup(self):
        self.install()
        self.put(self.src / 'skills/castra/SKILL.md', 'upgraded owned skill')
        self.install()
        self.assertEqual((self.cdir / 'skills/castra/SKILL.md').read_text(), 'upgraded owned skill')
        reports = list((self.home / 'backups').glob('*/rollback.json'))
        self.assertEqual(len(reports), 2)
        report = json.loads(reports[-1].read_text())
        self.assertEqual(report['status'], 'installed')

    def test_tampered_managed_file_refused_and_doctor_detects(self):
        self.install()
        self.put(self.cdir / 'hooks/castra-route.py', 'modified locally')
        with self.assertRaisesRegex(ValueError, 'modified'): installer.check_install()
        with self.assertRaisesRegex(ValueError, 'modified'): installer.plan_install()

    def test_doctor_only_runs_owned_hooks_and_does_not_write_install(self):
        self.install()
        path = self.cdir / 'settings.json'
        settings = json.loads(path.read_text())
        sentinel = self.base / 'foreign-executed'
        settings['hooks']['Stop'].append({'hooks': [{'type': 'command', 'command': f'touch {sentinel}'}]})
        path.write_text(json.dumps(settings))
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()): installer.check_install()
        self.assertEqual(before, self.snapshot())
        self.assertFalse(sentinel.exists())

    def test_doctor_rejects_dependency_omitted_from_manifest(self):
        self.install()
        path = self.home / 'manifest.json'
        manifest = json.loads(path.read_text())
        helper = self.home / 'scripts/castra_contract.py'
        del manifest['managed_files'][str(helper)]
        helper.unlink()
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'required dependency absent'):
            installer.check_install()

    def test_doctor_rejects_missing_installed_contract_helper(self):
        self.install()
        (self.home / 'scripts/castra_contract.py').unlink()
        with self.assertRaisesRegex(ValueError, 'missing or modified'):
            installer.check_install()

    def test_doctor_rejects_hash_matching_activation_failures(self):
        # Matching bytes alone must not turn a broken installer source into PASS.
        self.install()
        for relative, content in (
                ('scripts/castra_contract.py', '# missing contract_context\n'),
                ('packs/execution-posture-pack.txt', 'invalid contract\n')):
            with self.subTest(relative=relative):
                path = self.home / relative
                original = path.read_bytes()
                manifest_path = self.home / 'manifest.json'
                original_manifest = manifest_path.read_bytes()
                path.write_text(content)
                manifest = json.loads(original_manifest)
                manifest['managed_files'][str(path)]['sha256'] = installer.digest(path.read_bytes())
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, 'execution contract activation failed'):
                    installer.check_install()
                path.write_bytes(original)
                manifest_path.write_bytes(original_manifest)

    def test_doctor_rejects_route_diagnostic_or_missing_context(self):
        for output in ('{}', json.dumps({'systemMessage': 'freshness is unverified'})):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, 'activation failed'):
                    installer.validate_activation(output, 'UserPromptSubmit', 'castra-route.py', 'doctor')

    def test_settings_edit_between_plan_and_apply_preserved(self):
        settings_path = self.cdir / 'settings.json'
        self.put(settings_path, '{"env":{"EXISTING":"keep"}}')
        changes, _, originals = installer.plan_install()
        updated = '{"env":{"EXISTING":"keep","ADDED_AFTER_PLAN":"keep too"}}'
        settings_path.write_text(updated)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'changed since preflight'):
            installer.apply_changes(changes, originals)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(settings_path.read_text(), updated)
        self.assertFalse((self.home / 'backups').exists())

    def test_new_file_created_after_plan_preserved(self):
        changes, _, originals = installer.plan_install()
        target = self.cdir / 'hooks/castra-route.py'
        self.put(target, 'concurrent new hook')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'changed since preflight'):
            installer.apply_changes(changes, originals)
        self.assertEqual(self.snapshot(), before)

    def test_failed_write_rolls_back(self):
        changes, _, originals = installer.plan_install()
        real_write = installer.atomic_write
        victim = self.home / 'packs/execution-posture-pack.txt'
        def fail_once(path, data):
            if path == victim: raise OSError('injected failure')
            real_write(path, data)
        with patch.object(installer, 'atomic_write', fail_once), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(OSError): installer.apply_changes(changes, originals)
        self.assertFalse((self.home / 'scripts/castra_notes.py').exists())
        self.assertFalse((self.cdir / 'settings.json').exists())
        report = json.loads(next((self.home / 'backups').glob('*/rollback.json')).read_text())
        self.assertEqual(report['status'], 'rolled_back')

    def test_rollback_preserves_concurrent_edit(self):
        first, second = self.home / 'first.txt', self.home / 'second.txt'
        real_write = installer.atomic_write
        def concurrent_failure(path, data):
            if path == second:
                first.write_text('concurrent user edit')
                raise OSError('injected failure after concurrent edit')
            real_write(path, data)
        with patch.object(installer, 'atomic_write', concurrent_failure), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(OSError): installer.apply_changes({first: b'installer content', second: b'new'}, {first: None, second: None})
        self.assertEqual(first.read_text(), 'concurrent user edit')
        report = json.loads(next((self.home / 'backups').glob('*/rollback.json')).read_text())
        self.assertEqual(report['status'], 'rollback_conflict')
        self.assertEqual(report['preserved_concurrent_changes'], [str(first)])

    def test_doctor_validates_hook_event_and_permission_schema(self):
        wrong_event = {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': 'hello'}}
        with self.assertRaisesRegex(ValueError, 'event schema'):
            installer.validate_output(json.dumps(wrong_event), 'PostToolUse', 'castra-budget.py')
        wrong_decision = {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'confirmed'}}
        with self.assertRaisesRegex(ValueError, 'permissionDecision'):
            installer.validate_output(json.dumps(wrong_decision), 'PreToolUse', 'castra-guardian.py')

    def test_plugin_manifest_and_hook_contract(self):
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'castra')
        self.assertEqual(manifest['version'], (ROOT / 'VERSION').read_text().strip())
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text())['hooks']
        self.assertEqual(set(hooks), set(installer.HOOK_SCRIPTS))
        for event, entries in installer.HOOK_SCRIPTS.items():
            self.assertEqual(len(entries), len(hooks[event]))
            for (matcher, name), group in zip(entries, hooks[event]):
                self.assertEqual(group.get('matcher'), matcher)
                self.assertEqual(group['hooks'], [{'type': 'command', 'command': 'python3',
                                                  'args': ['${CLAUDE_PLUGIN_ROOT}/hooks/' + name]}])


if __name__ == '__main__':
    unittest.main()
