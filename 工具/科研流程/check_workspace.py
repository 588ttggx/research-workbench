"""Preview change-based checks, or run the selected builds and tests."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = {'workflow.py', 'research_store.py', 'dashboard.py', 'local_secrets.py',
        'structured_response.py', 'skill_registry.py', 'research_prompts.py',
        'material_roles.py', 'material_scope.py', 'job_policy.py',
        'index.html', 'workspace-app.js', 'workspace.css',
        'workspace_runtime.py', 'model_gateway.py'}
DEPENDENCIES = {'pyproject.toml', 'uv.lock', 'requirements.txt', 'package.json', 'package-lock.json',
                'document-parser-requirements.in', 'document-parser-requirements.lock',
                'document-vllm-requirements.in', 'document-vllm-requirements.lock'}
RETIRED_CHECKS = {
    'tests/独立验收/隔离验收.py', 'tests/独立验收/检查.py',
    'tests/独立验收/修复复验.py', 'tests/独立验收/中文预览补验.py',
    'tests/验收项目知识.py',
}
CURRENT_CHECK_ENTRY = 'check_workspace.py --changed <actual paths>; current browser checks: tests/verify_*_browser.py and tests/验收阶段知识.py'
# This executable map owns test selection. Documentation links here instead of
# maintaining another list of commands for every feature.
AREAS = {
    'literature': {
        'sources': ('scholarly_*.py', 'radar_*.py', 'research_radar.py', 'weekly_brief.py',
                    'workspace-scholarly.js', 'thz_domain.py', 'acquisitions.py',
                    'journal_rank*.py', 'bibliography.py', 'storage_budget.py'),
        'tests': ('test_scholarly_*', 'test_*radar*', 'test_daily_workflow',
                  'test_acquisitions', 'test_attachment_merge', 'test_journal_ranks',
                  'test_rank_public_sources', 'test_thz_domain', 'test_bibliography',
                  'test_paper_retention', 'test_original_pdf_preservation'),
        'js': ('scholarly-results.test.js', 'workspace-maintenance.test.js'),
    },
    'knowledge': {
        'sources': ('knowledge*', 'workspace-knowledge*', 'frontend/src/knowledge-*', 'fulltext_parser.py', 'paper_evidence.py',
                    'paper_notes.py', 'paper_import.py', 'original_files.py', 'pmc_fulltext.py',
                    'material_cleanup.py', 'relation_*.py', 'research_records.py',
                    'document_parser.py', 'document_parser_worker.py', 'document_vlm_host.py', 'start_document_vlm.sh'),
        'tests': ('test_knowledge*', 'test_fulltext_reading', 'test_local_retrieval',
                  'test_paper_notes', 'test_paper_import', 'test_paper_retention',
                  'test_original_pdf_preservation', 'test_pmc_pdf', 'test_relation_discovery',
                  'test_fulltext*', 'test_record_entry', 'test_material_cleanup', 'test_workflow',
                  'test_project_decisions', 'test_document_coverage', 'test_document_parser', 'test_document_vlm_host', 'test_document_service',
                  'test_maintenance_retrieval'),
        'js': ('knowledge*.test.js', 'record-entry.test.js', 'workspace-relations.test.js'),
    },
    'projects': {
        'sources': ('project_*.py', 'canvas_*.py', 'workspace-projects.js', 'workspace-canvas.js',
                    'workspace-questions.js', 'frontend/src/project-*', 'frontend/src/stage-*',
                    'frontend/src/canvas-*', 'frontend/src/attach-project-items.jsx'),
        'tests': ('test_project*', 'test_stage_workspace', 'test_question_progress_records',
                  'test_work_plan_separation', 'test_extension_contracts'),
        'js': ('project*.test.js', 'work-plan-separation.test.js'),
    },
    'maintenance': {
        'sources': ('storage_inventory.py', 'storage_budget.py', 'runtime_logs.py',
                    'check_workspace.py', '启动独立验收.ps1'),
        'tests': ('test_storage_inventory', 'test_storage_budget', 'test_runtime_logs', 'test_check_workspace'),
        'js': (),
    },
    'assistant': {
        'sources': ('model_settings.py', 'deepseek_bridge.py', 'administrator*.py',
                    'ai_updates.py', 'organization.py', 'direction_discovery.py',
                    'research_prompts.py', 'skill_management.py'),
        'tests': ('test_model_settings', 'test_runtime_boundaries', 'test_administrator*',
                  'test_ai_updates', 'test_organization', 'test_skill*', 'test_writing*',
                  'test_document_coverage', 'test_daily_workflow', 'test_extension_contracts',
                  'test_maintenance_state', 'test_maintenance_runtime', 'test_maintenance_lifecycle',
                  'test_maintenance_intake', 'test_maintenance_retrieval'),
        'js': ('workspace-skills.test.js',),
    },
}


def _relative(value):
    value = str(value).replace('\\', '/')
    if '..' in value.split('/'):
        return None
    path = Path(value)
    if path.is_absolute():
        try: value = path.relative_to(ROOT).as_posix()
        except ValueError: return None
    prefix = '工具/科研流程/'
    return value[len(prefix):] if value.startswith(prefix) else value.removeprefix('./')


def _python_command(names=None):
    if names is None:
        return [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q']
    return [sys.executable, '-B', '-m', 'unittest', '-q', *sorted(names)]


def plan(changed, *, full=False):
    paths = sorted(set(_relative(path) for path in changed), key=lambda item: item or '')
    release = full and not paths
    areas = set(); direct_python = set(); direct_js = set(); reasons = []
    documentation = []; retired = []
    for path in paths:
        if path in RETIRED_CHECKS and not (HERE/path).exists():
            retired.append({'path': path, 'replacement': CURRENT_CHECK_ENTRY})
            continue
        if path and Path(path).suffix.lower() in ('.md', '.txt') and Path(path).name not in DEPENDENCIES:
            documentation.append(path)
            continue
        if not path or Path(path).name in DEPENDENCIES or path in CORE:
            full = True; reasons.append('shared contract, dependency or invalid path: '+str(path)); continue
        if path.startswith('tests/'):
            file = HERE/path
            if file.is_file() and file.name.startswith('test_') and file.suffix == '.py':
                direct_python.add(file.stem); continue
            if file.is_file() and file.name.endswith('.test.js'):
                direct_js.add(path); continue
            full = True; reasons.append('test removed or fixture changed: '+path); continue
        matched = {name for name, spec in AREAS.items()
                   if any(fnmatch.fnmatchcase(path, pattern) for pattern in spec['sources'])}
        if matched:
            areas.update(matched)
        else:
            full = True; reasons.append('unmapped change: '+path)
    commands = []
    manual = []
    if full:
        commands.append(_python_command())
        js = sorted(p.relative_to(HERE).as_posix() for p in (HERE/'tests').glob('*.test.js'))
        js += sorted(p.relative_to(HERE).as_posix() for p in (HERE/'frontend/src').glob('*.test.mjs'))
        if js: commands.append(['node', '--test', *js])
        collector = ROOT/'.agents/skills/scholarly-paper-collector/scripts/tests'
        if collector.is_dir():
            commands.append([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(collector), '-q'])
        manual = ['browser: affected create/save/cancel/conflict/narrow-screen flow',
                  'managed reload + repeat startup when runtime code changed',
                  'native adapters and data preservation: record actual conditions; never relabel failures as passed']
        level = 'full'
    elif areas or direct_python or direct_js:
        python = set(direct_python); js = set(direct_js)
        for area in areas:
            spec = AREAS[area]
            python.update(p.stem for p in (HERE/'tests').glob('test_*.py')
                          if any(fnmatch.fnmatchcase(p.stem, pattern) for pattern in spec['tests']))
            js.update(p.relative_to(HERE).as_posix() for p in (HERE/'tests').glob('*.test.js')
                      if any(fnmatch.fnmatchcase(p.name, pattern) for pattern in spec['js']))
        if python: commands.append(_python_command(python))
        if any(path and path.startswith('frontend/src/knowledge-') for path in paths):
            js.update(p.relative_to(HERE).as_posix() for p in (HERE/'frontend/src').glob('knowledge*.test.mjs'))
        if js: commands.append(['node', '--test', *sorted(js)])
        level = 'targeted'
        if areas != {'maintenance'}:
            manual = ['browser: affected flow, cancel/conflict and narrow screen if UI changed',
                      'managed reload and affected formal entry if runtime code changed']
    else:
        level = 'documents'
    # Build selection is independent of test selection. Both bundles consume the
    # same dependency tree, while each script owns its own build.
    builds = []
    frontend_paths = {path for path in paths if path and path.startswith('frontend/')}
    shared_dependencies = bool(frontend_paths & {'frontend/package.json', 'frontend/package-lock.json'})
    knowledge_inputs = ('frontend/src/knowledge-', 'frontend/src/vendor/lucide-animated/', 'frontend/assets/')
    if (release or shared_dependencies or 'frontend/knowledge-build.mjs' in frontend_paths
            or any(path.startswith(knowledge_inputs) for path in frontend_paths)):
        builds.append(['node', str(HERE/'frontend/knowledge-build.mjs')])
    if (release or shared_dependencies or 'frontend/build.mjs' in frontend_paths
            or any(path.startswith('frontend/src/') and not path.startswith(knowledge_inputs)
                   for path in frontend_paths)):
        builds.append(['node', str(HERE/'frontend/build.mjs')])
    return {'level': level, 'changed': paths, 'areas': sorted(areas), 'reasons': reasons,
            'document_checks': documentation, 'retired_checks': retired,
            'commands': builds+commands, 'manual_checks': manual,
            'note': 'Selection is a conservative aid, not proof of coverage; browser/native checks remain separate.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--changed', action='append', default=[], help='changed workspace/module-relative path; repeat as needed')
    parser.add_argument('--full', action='store_true', help='complete integration baseline for a release or shared contract change')
    parser.add_argument('--run', action='store_true', help='execute the printed commands; default only previews')
    args = parser.parse_args(argv)
    if not args.changed and not args.full:
        parser.error('name --changed paths or request --full; no implicit full regression')
    selected = plan(args.changed, full=args.full)
    print(json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    if not args.run:
        return 0
    environment = os.environ.copy()
    environment['PYTHONPATH'] = os.pathsep.join([str(HERE/'tests'), str(HERE), environment.get('PYTHONPATH', '')])
    environment['PYTHONIOENCODING'] = 'utf-8'
    outcomes = []
    for command in selected['commands']:
        started = time.monotonic()
        build_scripts = {str(HERE/'frontend/build.mjs'), str(HERE/'frontend/knowledge-build.mjs')}
        directory = HERE/'frontend' if len(command)>1 and command[1] in build_scripts else HERE
        try: code = subprocess.run(command, cwd=directory, env=environment, check=False).returncode
        except OSError as error:
            print(type(error).__name__+': check could not start', file=sys.stderr); code = 127
        outcomes.append({'command': command, 'exit_code': code, 'seconds': round(time.monotonic()-started, 3)})
    print(json.dumps({'automated_checks': outcomes, 'manual_checks_pending': selected['manual_checks']},
                     ensure_ascii=False, indent=2))
    return int(any(row['exit_code'] for row in outcomes))


if __name__ == '__main__':
    raise SystemExit(main())
