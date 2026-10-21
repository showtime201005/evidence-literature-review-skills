"""Portable native packaging/rollback controls; no model/provider calls."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SHARED=ROOT/'skills/literature-review/scripts/runtime/litreview_core/skill_installation.py'
ROOT_ENTRY=ROOT/'scripts/install_skills.py'
BUNDLED_ENTRY=ROOT/'skills/literature-review/scripts/install_skills.py'
spec=importlib.util.spec_from_file_location('native_skill_installer',SHARED)
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class NativeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='skill-install-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source'
        for name in installer.NAMES:
            folder=self.source/name
            (folder/'references').mkdir(parents=True)
            (folder/'SKILL.md').write_text(f'---\nname: {name}\ndescription: 測試完整 UTF-8。\n---\n# {name}\n',encoding='utf-8')
            (folder/'references/retained.md').write_bytes('完整參考資料\r\n'.encode('utf-8'))
            (folder/'scripts/runtime/litreview_core').mkdir(parents=True)
            (folder/'scripts/runtime/litreview_core/stale-selected.py').write_text('old selected runtime',encoding='utf-8')
            (folder/'scripts/harness_runner.py').write_text('legacy runner',encoding='utf-8')
            (folder/'scripts/litreview.py').write_text('legacy CLI',encoding='utf-8')
            (folder/'assets').mkdir()
            (folder/'assets/example.md').write_text('EXAMPLE_NEVER_ASSIGNED_TO_NATIVE',encoding='utf-8')
            (folder/'.env').write_text('PRIVATE_SOURCE_ONLY=never_copy',encoding='utf-8')
        scripts=self.source/'literature-review/scripts'
        for name in (*installer.COMMON_ENTRIES,*installer.REVIEW_ENTRIES):
            (scripts/name).write_text('canonical-entry-'+name,encoding='utf-8')
        core=scripts/'runtime/litreview_core'
        for name in installer.REQUIRED_MODULES:
            (core/name).write_text('canonical-runtime-'+name,encoding='utf-8')
        (core/'contracts').mkdir()
        (core/'contracts/__init__.py').write_text('canonical contracts',encoding='utf-8')
        (core/'contracts/contracts.schema.json').write_text('{}',encoding='utf-8')
        (core/'__pycache__').mkdir()
        (core/'__pycache__/cached.pyc').write_bytes(b'not-portable-bytecode')
        self.canonical_scripts=scripts
        self.addCleanup(patch.stopall)
        patch.object(socket,'create_connection',side_effect=AssertionError('No network in installation tests')).start()

    def test_each_single_skill_gets_canonical_runtime_native_doctor_and_task(self):
        for name in installer.NAMES[:-1]:
            with self.subTest(skill=name):
                project=self.root/('project-'+name)
                result=installer.install(self.source,project,'deepagents',[name])
                selected=project/'skills'/name
                self.assertEqual([p.name for p in (project/'skills').iterdir()],[name])
                self.assertEqual((selected/'SKILL.md').read_bytes(),(self.source/name/'SKILL.md').read_bytes())
                self.assertEqual((selected/'references/retained.md').read_bytes(),(self.source/name/'references/retained.md').read_bytes())
                for entry in installer.COMMON_ENTRIES:
                    self.assertEqual((selected/'scripts'/entry).read_bytes(),(self.canonical_scripts/entry).read_bytes())
                for module in installer.REQUIRED_MODULES:
                    self.assertEqual((selected/'scripts/runtime/litreview_core'/module).read_bytes(),
                                     (self.canonical_scripts/'runtime/litreview_core'/module).read_bytes())
                self.assertFalse((selected/'assets').exists())
                self.assertFalse((selected/'.env').exists())
                self.assertFalse((selected/'scripts/harness_runner.py').exists())
                self.assertFalse((selected/'scripts/native_review.py').exists())
                self.assertFalse((selected/'scripts/runtime/litreview_core/__pycache__').exists())
                self.assertEqual(result['profile'],installer.NATIVE_PROFILE)
                self.assertFalse(result['publication_verified'])
                manifest=json.loads((selected/'native-installation.json').read_text(encoding='utf-8'))
                for relative,digest in manifest['files'].items():
                    self.assertEqual(sha256((selected/relative).read_bytes()).hexdigest(),digest)

    def test_coordinator_installs_all_five_with_full_native_entrypoints_and_same_runtime(self):
        project=self.root/'all-project'
        result=installer.install(self.source,project,'deepagents')
        self.assertEqual(result['installed'],installer.NAMES)
        coordinator=project/'skills/literature-review'
        for entry in (*installer.COMMON_ENTRIES,*installer.REVIEW_ENTRIES):
            self.assertTrue((coordinator/'scripts'/entry).is_file())
        self.assertEqual(result['native_runtime_verification'],'not_performed')
        for name in installer.NAMES:
            self.assertFalse((project/'skills'/name/'assets').exists())

    def test_existing_installation_in_any_harness_blocks_entire_selection_without_overwrite(self):
        project=self.root/'existing-project'
        existing=project/'.claude/skills/compare-papers'
        existing.mkdir(parents=True)
        (existing/'user-content.txt').write_text('KEEP EXACTLY',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Duplicate skill installation'):
            installer.install(self.source,project,'deepagents',['analyze-paper','compare-papers'])
        self.assertFalse((project/'skills/analyze-paper').exists())
        self.assertEqual((existing/'user-content.txt').read_text(encoding='utf-8'),'KEEP EXACTLY')

    def test_missing_canonical_native_module_preflight_creates_no_project(self):
        (self.canonical_scripts/'runtime/litreview_core/native_agent.py').unlink()
        project=self.root/'missing-module-project'
        with self.assertRaisesRegex(ValueError,'Missing canonical native runtime module'):
            installer.install(self.source,project,'deepagents',['analyze-paper'])
        self.assertFalse(project.exists())

    def test_missing_entrypoint_preflight_creates_no_project(self):
        (self.canonical_scripts/'native_doctor.py').unlink()
        project=self.root/'missing-doctor-project'
        with self.assertRaisesRegex(ValueError,'Missing canonical native entry'):
            installer.install(self.source,project,'deepagents',['analyze-paper'])
        self.assertFalse(project.exists())

    def test_missing_portable_installer_entry_or_module_creates_no_project(self):
        for relative in ('install_skills.py','runtime/litreview_core/skill_installation.py'):
            with self.subTest(missing=relative):
                path=self.canonical_scripts/relative
                raw=path.read_bytes()
                path.unlink()
                project=self.root/('missing-installer-'+path.stem)
                try:
                    with self.assertRaisesRegex(ValueError,'Missing canonical native'):
                        installer.install(self.source,project,'deepagents',['write-review'])
                    self.assertFalse(project.exists())
                finally:
                    path.write_bytes(raw)

    def test_missing_draft_submission_wire_preflight_creates_no_project(self):
        (self.canonical_scripts/'runtime/litreview_core/draft_submission_wire.py').unlink()
        project=self.root/'missing-draft-wire-project'
        with self.assertRaisesRegex(ValueError,'draft_submission_wire.py'):
            installer.install(self.source,project,'deepagents',['write-review'])
        self.assertFalse(project.exists())

    def test_missing_proof_citation_view_preflight_creates_no_project(self):
        (self.canonical_scripts/'runtime/litreview_core/proof_citation_view.py').unlink()
        project=self.root/'missing-citation-view-project'
        with self.assertRaisesRegex(ValueError,'proof_citation_view.py'):
            installer.install(self.source,project,'deepagents',['verify-citations'])
        self.assertFalse(project.exists())

    def test_missing_provider_routes_preflight_creates_no_project(self):
        (self.canonical_scripts/'runtime/litreview_core/provider_routes.py').unlink()
        for selected in (['literature-review'], ['verify-citations'], installer.NAMES):
            with self.subTest(selected=selected):
                project=self.root/('missing-provider-routes-'+str(len(selected))+'-'+selected[0])
                with self.assertRaisesRegex(ValueError,'provider_routes.py'):
                    installer.install(self.source,project,'deepagents',selected)
                self.assertFalse(project.exists())

    def test_mid_commit_failure_rolls_back_only_this_transaction(self):
        project=self.root/'rollback-project'
        project.mkdir()
        (project/'user-notes.txt').write_text('KEEP USER FILE',encoding='utf-8')
        original=installer._exclusive_copy
        def fail_second(source,destination):
            if 'compare-papers' in destination.parts:
                raise OSError('injected second-skill write failure')
            return original(source,destination)
        with patch.object(installer,'_exclusive_copy',side_effect=fail_second),self.assertRaisesRegex(OSError,'injected'):
            installer.install(self.source,project,'deepagents',['analyze-paper','compare-papers'])
        self.assertFalse((project/'skills/analyze-paper').exists())
        self.assertFalse((project/'skills/compare-papers').exists())
        self.assertEqual((project/'user-notes.txt').read_text(encoding='utf-8'),'KEEP USER FILE')
        self.assertEqual(list(self.root.glob('.lr-stage-*')),[])

    def test_destination_race_does_not_overwrite_or_rollback_foreign_target(self):
        project=self.root/'race-project'
        foreign=project/'skills/compare-papers'
        original=Path.mkdir
        injected=[False]
        def mkdir(path,*args,**kwargs):
            if path==foreign and not injected[0]:
                injected[0]=True
                original(path,parents=True)
                (path/'foreign.txt').write_text('FOREIGN CONTENT',encoding='utf-8')
            return original(path,*args,**kwargs)
        with patch.object(Path,'mkdir',new=mkdir),self.assertRaises(FileExistsError):
            installer.install(self.source,project,'deepagents',['analyze-paper','compare-papers'])
        self.assertFalse((project/'skills/analyze-paper').exists())
        self.assertEqual((foreign/'foreign.txt').read_text(encoding='utf-8'),'FOREIGN CONTENT')

    def test_managed_source_folder_names_resolve_from_utf8_frontmatter(self):
        for index,name in enumerate(installer.NAMES):
            (self.source/name).rename(self.source/('managed-id-'+str(index)))
        project=self.root/'managed-project'
        installer.install(self.source,project,'deepagents',['write-review'])
        self.assertTrue((project/'skills/write-review/scripts/native_task.py').is_file())
        self.assertIn('測試完整 UTF-8',(project/'skills/write-review/SKILL.md').read_text(encoding='utf-8'))

    def test_windows_long_legacy_asset_is_not_copied_but_native_package_completes(self):
        asset=Path('assets/examples/comparison-handoff/corpus/sources')/('f'*64+'.md')
        source=self.source/'analyze-paper'/asset
        source.parent.mkdir(parents=True)
        source.write_text('LEGACY DEEP EXAMPLE',encoding='utf-8')
        project=self.root/('project-'+'x'*max(1,122-len(str(self.root))))
        self.assertGreater(len(str(project/'skills/analyze-paper'/asset)),260)
        installer.install(self.source,project,'deepagents',['analyze-paper'])
        self.assertTrue((project/'skills/analyze-paper/scripts/native_task.py').is_file())
        self.assertFalse((project/'skills/analyze-paper/assets').exists())

    def test_legacy_harnesses_retain_complete_selected_skill_copy(self):
        for harness in ('codex','claude-code','opencode'):
            with self.subTest(harness=harness):
                project=self.root/('legacy-'+harness)
                result=installer.install(self.source,project,harness,['analyze-paper'])
                selected=project/installer.TARGETS[harness]/'analyze-paper'
                self.assertTrue((selected/'assets/example.md').is_file())
                self.assertEqual((selected/'scripts/harness_runner.py').read_text(encoding='utf-8'),'legacy runner')
                self.assertTrue((selected/'scripts/runtime/litreview_core/stale-selected.py').is_file())
                self.assertFalse((selected/'scripts/native_task.py').exists())
                self.assertNotIn('profile',result)

    def test_real_single_install_native_cli_help_from_other_directory_without_key(self):
        if importlib.util.find_spec('deepagents') is None:
            self.skipTest('Native dependencies are not installed; installer itself is stdlib-only')
        project=self.root/'real-project'
        installer.install(ROOT/'skills',project,'deepagents',['write-review'])
        selected=project/'skills/write-review'
        for entry in ('native_task.py','native_doctor.py','install_skills.py'):
            run=subprocess.run([sys.executable,'-X','utf8',str(selected/'scripts'/entry),'--help'],
                cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
        self.assertFalse((project/'skills/literature-review').exists())

    def installer_cli(self,entry,*arguments):
        # -I ignores PYTHONPATH/current-directory imports; -S removes all third
        # party packages. Installer operation therefore proves stdlib-only use.
        return subprocess.run([sys.executable,'-I','-S','-B','-X','utf8',str(entry),*map(str,arguments)],
            cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)

    def test_root_and_bundled_help_are_identical_without_site_packages(self):
        root=self.installer_cli(ROOT_ENTRY,'--help')
        bundled=self.installer_cli(BUNDLED_ENTRY,'--help')
        self.assertEqual(root.returncode,0,root.stderr)
        self.assertEqual(bundled.returncode,0,bundled.stderr)
        self.assertEqual(root.stdout,bundled.stdout)

    def test_root_and_bundled_native_cli_install_same_files_and_reject_duplicate(self):
        results=[]
        manifests=[]
        for index,entry in enumerate((ROOT_ENTRY,BUNDLED_ENTRY)):
            project=self.root/('cli-parity-'+str(index))
            args=('--source',self.source,'--target',project,'--harness','deepagents','--skill','write-review')
            completed=self.installer_cli(entry,*args)
            self.assertEqual(completed.returncode,0,completed.stderr)
            result=json.loads(completed.stdout)
            result.pop('skills_root')
            results.append(result)
            target=project/'skills/write-review'
            manifest=json.loads((target/'native-installation.json').read_text(encoding='utf-8'))
            manifest.pop('transaction_id')
            manifests.append(manifest)
            for relative,digest in manifest['files'].items():
                self.assertEqual(sha256((target/relative).read_bytes()).hexdigest(),digest)
            self.assertFalse((target/'assets').exists())
            before={p.relative_to(target):p.read_bytes() for p in target.rglob('*') if p.is_file()}
            duplicate=self.installer_cli(entry,*args)
            self.assertEqual(duplicate.returncode,2)
            self.assertIn('Duplicate skill installation',duplicate.stderr)
            self.assertEqual(before,{p.relative_to(target):p.read_bytes() for p in target.rglob('*') if p.is_file()})
        self.assertEqual(results[0],results[1])
        self.assertEqual(manifests[0],manifests[1])

    def test_bundled_wrapper_with_own_runtime_works_after_moving_outside_repo(self):
        moved=self.root/'detached-skill/scripts'
        moved.mkdir(parents=True)
        shutil.copy2(BUNDLED_ENTRY,moved/'install_skills.py')
        shutil.copytree(BUNDLED_ENTRY.parent/'runtime',moved/'runtime',
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        project=self.root/'detached-installed'
        result=self.installer_cli(moved/'install_skills.py','--source',self.source,'--target',project,
                                  '--harness','deepagents','--skill','analyze-paper')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['installed'],['analyze-paper'])
        selected=project/'skills/analyze-paper'
        self.assertTrue((selected/'scripts/install_skills.py').is_file())
        self.assertTrue((selected/'scripts/runtime/litreview_core/skill_installation.py').is_file())
        self.assertFalse((selected/'assets').exists())

    def test_installed_single_skill_installer_uses_own_runtime_without_coordinator_sibling(self):
        first=self.root/'real-first-install'
        installer.install(ROOT/'skills',first,'deepagents',['write-review'])
        self.assertFalse((first/'skills/literature-review').exists())
        entry=first/'skills/write-review/scripts/install_skills.py'
        second=self.root/'real-second-install'
        result=self.installer_cli(entry,'--source',ROOT/'skills','--target',second,
                                  '--harness','deepagents','--skill','verify-citations')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['installed'],['verify-citations'])
        selected=second/'skills/verify-citations'
        manifest=json.loads((selected/'native-installation.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['profile'],installer.NATIVE_PROFILE)
        self.assertEqual((selected/'scripts/install_skills.py').read_bytes(),BUNDLED_ENTRY.read_bytes())
        self.assertEqual((selected/'scripts/runtime/litreview_core/skill_installation.py').read_bytes(),SHARED.read_bytes())
        self.assertFalse((second/'skills/literature-review').exists())

    def test_root_and_bundled_legacy_cli_keep_complete_copy_for_each_harness(self):
        for harness in ('codex','claude-code','opencode'):
            for index,entry in enumerate((ROOT_ENTRY,BUNDLED_ENTRY)):
                with self.subTest(harness=harness,entry=index):
                    project=self.root/('cli-legacy-'+harness+'-'+str(index))
                    result=self.installer_cli(entry,'--source',self.source,'--target',project,
                                              '--harness',harness,'--skill','analyze-paper')
                    self.assertEqual(result.returncode,0,result.stderr)
                    target=project/installer.TARGETS[harness]/'analyze-paper'
                    self.assertTrue((target/'assets/example.md').is_file())
                    self.assertEqual((target/'scripts/harness_runner.py').read_text(encoding='utf-8'),'legacy runner')
                    self.assertTrue((target/'scripts/runtime/litreview_core/stale-selected.py').is_file())
                    self.assertNotIn('profile',json.loads(result.stdout))

    def test_real_review_install_exposes_v2_and_all_runtime_dependencies(self):
        if importlib.util.find_spec('deepagents') is None:
            self.skipTest('Native dependencies are not installed')
        project=self.root/'review-project'
        installer.install(ROOT/'skills',project,'deepagents',['literature-review'])
        selected=project/'skills/literature-review'
        for module in installer.REQUIRED_MODULES:
            self.assertEqual((selected/'scripts/runtime/litreview_core'/module).read_bytes(),
                (ROOT/'skills/literature-review/scripts/runtime/litreview_core'/module).read_bytes())
        run=subprocess.run([sys.executable,'-X','utf8',str(selected/'scripts/native_review.py'),'--help'],
            cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('--review-protocol {v1,v2}',run.stdout)
        runtime=str(selected/'scripts/runtime')
        code=('import sys; sys.path.insert(0,sys.argv[1]); '
              'from litreview_core.review_workflow_v2 import ReviewWorkflowV2; '
              'from litreview_core.review_release_v2 import verify_review_release_v2; '
              'from litreview_core.delivery_export_v2 import export_review_v2, save_review_attempt_v2')
        run=subprocess.run([sys.executable,'-X','utf8','-c',code,runtime],cwd=self.root,
            capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':
    unittest.main()
