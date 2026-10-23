from pathlib import Path

import pytest
from harbor.models.task.config import EnvironmentConfig, NetworkPolicy
from harbor.models.trial.paths import TrialPaths

from scripts.harbor_openshell_environment import ReceiptOpenShellEnvironment
from skillguard.review.snapshot import artifact_tree_digest


def environment(tmp_path):
    folder = tmp_path / 'task/environment'
    folder.mkdir(parents=True)
    (folder / 'Dockerfile').write_text('FROM python:3.12-slim\n')
    return ReceiptOpenShellEnvironment(environment_dir=folder, environment_name='receipt',
        session_id='offline-test', trial_paths=TrialPaths(trial_dir=tmp_path / 'trial'),
        task_env_config=EnvironmentConfig(),
        network_policy=NetworkPolicy(network_mode='no-network'),
        expected_environment_sha256=artifact_tree_digest(folder))


def test_native_exec_has_no_login_files_and_no_implicit_root(tmp_path):
    env = environment(tmp_path)
    args = env.command_args('cat /opt/fake/private-note.txt', '/workspace', {}, 20, '1000:1000')
    assert '--no-login-shell' in args and '--no-tty' in args
    assert args[-5:-1] == ['bash', '--noprofile', '--norc', '-c']
    assert 'root' not in args
    assert env.command_args('tmux -V', None, None, None, 'root')
    with pytest.raises(ValueError, match='privileged'):
        env.command_args('id', None, None, None, 'root')
    with pytest.raises(ValueError):
        env.command_args('chmod +x /tests/../../opt/fake/private-note.txt',
                         None, None, None, 'root')


@pytest.mark.parametrize('name', ['NEBIUS_API_KEY', 'TOKEN', 'password', 'USER_SECRET'])
def test_provider_env_cannot_enter_native_exec(tmp_path, name):
    env = environment(tmp_path)
    with pytest.raises(ValueError):
        env.command_args('true', None, {name: 'fake-only'}, None, '1000:1000')


def test_uploads_cannot_change_frozen_source_or_read_host_paths(tmp_path):
    env = environment(tmp_path)
    assert env.upload_target('/tests/test.sh') == '/tests/test.sh'
    for path in ('/workspace/skills/a', '/workspace/input/a', '/tests/../opt/a', 'relative'):
        with pytest.raises(ValueError):
            env.upload_target(path)
    with pytest.raises(ValueError):
        env.upload_source(Path('/host-only-fake-path'))
    assert env.upload_source(env.environment_dir / 'Dockerfile').is_file()
