"""Bind native Harbor terminal commands and completion markers to provider replies."""
from __future__ import annotations


def step_signature(step: dict) -> tuple[list, bool]:
    commands, markers = [], 0
    for call in step.get('tool_calls') or []:
        kind = call.get('function_name')
        if kind == 'bash_command':
            commands.append(call['arguments'])
        elif kind == 'mark_task_complete' and call.get('arguments') == {}:
            markers += 1
        else:
            raise ValueError('Unknown or malformed native tool call')
    if markers > 1:
        raise ValueError('Duplicate native completion marker')
    return commands, bool(markers)


def reply_signature(reply: dict) -> tuple[list, bool]:
    complete = reply.get('task_complete', False)
    if type(complete) is not bool or not isinstance(reply.get('commands'), list):
        raise ValueError('Provider terminal/completion settings differ')
    return reply['commands'], complete
