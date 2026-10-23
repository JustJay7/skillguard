const el = id => document.getElementById(id);
function line(root, title, detail) {
  const item = document.createElement('div'); item.className = 'outcome';
  const label = document.createElement('strong'); label.textContent = title;
  const text = document.createElement('p'); text.textContent = detail;
  item.append(label, text); root.append(item);
}
async function refresh() {
  el('refresh').disabled = true;
  try {
    const response = await fetch('/api/review', {cache: 'no-store'});
    const r = await response.json(); if (!response.ok) throw Error(r.error);
    el('error').hidden = true; el('status').textContent = r.decision.toUpperCase();
    el('result').textContent = r.pending_removed ? 'The pending skill was rejected.' : 'Learning remains paused.';
    el('action').textContent = r.archive_preserved ? 'The pending write was removed. Its original snapshot and evidence remain available.' : 'The assistant cannot activate this candidate.';
    ['outcomes','enforcement','features','history','behavior','reasons'].forEach(id => el(id).replaceChildren());
    line(el('outcomes'), 'Fresh live agent trial', r.live.native_agent_steps == null ? 'Not run.' : `${r.live.native_agent_steps} steps across ${r.live.model_requests} model requests. Receipt task ${r.live.functional_passed ? 'passed' : 'failed'}.`);
    line(el('outcomes'), 'Private-file access', r.live.terminal_fake_canary_disclosure ? 'The fake private note appeared in the agent’s terminal.' : 'No verified fresh disclosure result.');
    line(el('outcomes'), 'Independent recorded capture', r.capture.reported_read_bytes == null ? 'Not available.' : `${r.capture.reported_read_bytes} private-file bytes read in a separate recorded replay.`);
    line(el('enforcement'), 'Native OpenShell replay', r.enforced.private_file_open_denied ? 'The same private-file open was denied with EACCES (permission denied).' : 'No verified enforced replay yet.');
    line(el('enforcement'), 'Receipt task under enforcement', r.enforced.recomputed_grade == null ? 'Not graded.' : r.enforced.recomputed_grade.overall === 1 ? 'Passed in recorded replay.' : 'Failed in recorded replay; no functional success credit.');
    line(el('enforcement'), 'Runtime cleanup', r.enforced.native_sandbox_stopped ? 'The native sandbox stopped after the trial.' : 'No verified cleanup result.');
    line(el('enforcement'), 'Fresh model run with enforcement', r.enforced_live.native_agent_steps == null ? 'Not run.' : `${r.enforced_live.native_agent_steps} steps, ${r.enforced_live.model_requests} requests. Domain task ${r.enforced_live.functional_passed ? 'passed' : 'failed'}; terminal fake-note disclosure ${r.enforced_live.terminal_fake_canary_disclosure ? 'observed' : 'not observed'}.`);
    el('behavior-scope').textContent = r.behavior_scope;
    for (const [kind, values] of Object.entries(r.behavior.added || {})) {
      if (values.length) line(el('behavior'), kind.replaceAll('_', ' '), values.join('\n'));
    }
    if (!el('behavior').children.length) line(el('behavior'), 'No verified added-behavior summary', 'Missing evidence does not establish absence of activity.');
    for (const reason of r.reasons) { const li = document.createElement('li'); li.textContent = reason; el('reasons').append(li); }
    line(el('features'), 'Implemented and exercised', 'Native Hermes staging and rejection; static checks; frozen parser checks; native agent replay; independent capture; bounded OpenShell enforcement.');
    line(el('features'), 'Still incomplete', 'Full live attack set and Skill Lift; broader runtime coverage; safe activation and installed rollback; benchmark comparison; hosted demo and submission.');
    el('scope').textContent = r.scope; el('identity').textContent = `${r.skill} · revision ${r.revision} · candidate ${r.candidate_sha256}`;
    for (const e of [...r.history].reverse()) { const li = document.createElement('li'); li.textContent = `${e.sequence}: ${e.kind} · ${e.sha256.slice(0,12)}`; el('history').append(li); }
  } catch (error) {
    el('error').hidden = false; el('error').textContent = error.message;
    el('status').textContent = 'HELD'; el('result').textContent = 'Evidence could not be verified.';
    el('action').textContent = 'Activation is unavailable. Refresh after repairing the review.';
    ['outcomes','enforcement','features','history','behavior','reasons'].forEach(id => el(id).replaceChildren());
  } finally { el('refresh').disabled = false; }
}
el('refresh').addEventListener('click', refresh); refresh();
