"""Native Harbor Oracle compatibility for the bounded local receipt workspace."""
from scripts.harbor_openshell_environment import POLICY, ReceiptOpenShellEnvironment

CORE_POLICY = POLICY.replace('/logs, /tests]', '/logs, /tests, /solution]')


class CoreOpenShellEnvironment(ReceiptOpenShellEnvironment):
    def policy_text(self):
        return CORE_POLICY

    def command_args(self, command, cwd, env, timeout_sec, user):
        if command == 'chmod +x /solution/solve.sh' and user == 'root':
            user = '1000:1000'
        return super().command_args(command, cwd, env, timeout_sec, user)

    @staticmethod
    def upload_target(value):
        if value == '/solution':
            return value
        return ReceiptOpenShellEnvironment.upload_target(value)
