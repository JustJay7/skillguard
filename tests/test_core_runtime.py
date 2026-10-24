import json
import subprocess

import pytest

from skillguard import core_runtime


@pytest.mark.parametrize('start_status', [0, 1])
def test_cold_start_is_bounded_and_failure_always_stops_runner(tmp_path, monkeypatch,
                                                              start_status):
    root = tmp_path / 'app'
    (root / 'results/integration').mkdir(parents=True)
    skill = root / 'skill'
    skill.mkdir()
    (skill / 'SKILL.md').write_text('# Test receipt skill\n')
    commands = []

    def prepare(root, folder, skill, cases):
        task = folder / 'task'
        task.mkdir()
        return task

    def command(args, *, root, env, output, timeout):
        commands.append((args, timeout))
        stdout = (json.dumps({'name': 'sgtrace-clean', 'status': 'Stopped'})
                  if args[:2] == ['limactl', 'list'] else '')
        output.write_text(stdout)
        status = start_status if args[:2] == ['limactl', 'start'] else (
            0 if args[:2] in [['limactl', 'stop'], ['limactl', 'list']] else 1)
        return subprocess.CompletedProcess(args, status, stdout, '')

    monkeypatch.setattr(core_runtime, 'prepare_task', prepare)
    monkeypatch.setattr(core_runtime, 'prepare_environment', lambda *_: {})
    monkeypatch.setattr(core_runtime, 'recorded_command', command)
    report = core_runtime.evaluate(root, skill, {})
    assert commands[0] == (['limactl', 'start', '--yes', '--timeout', '180s',
                            'sgtrace-clean'], 210)
    assert report['vm_startup_timeout_sec'] == 180
    assert report['passed'] is False and report['model_requests'] == 0
    assert report['runner_stopped'] is True
    assert report['error'] == ('Native VM startup failed' if start_status else
                               'Native gateway startup failed')
    assert ['limactl', 'stop', 'sgtrace-clean'] in [args for args, _ in commands]
