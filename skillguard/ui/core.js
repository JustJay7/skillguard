const byId = id => document.getElementById(id);
let state, timer, lastResult, lastView, pollError = false;
const accepted = new Set();
const heldReasons = new Map();
function text(tag, value, className) {
  const node = document.createElement(tag); node.textContent = value;
  if (className) node.className = className; return node;
}
async function act(action, data = {}) {
  byId('error').hidden = true;
  try {
    const response = await fetch('/api/action', {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-SkillGuard-CSRF': state.csrf,
        'X-SkillGuard-Origin': location.origin},
      body: JSON.stringify({action, ...data})});
    if (!response.ok) throw Error((await response.json()).error);
    await refresh();
  } catch (e) { showError(e.message); }
}
function showError(message, fromPoll = false) { pollError = fromPoll; byId('error').hidden = false; byId('error').textContent = message; }
function button(label, action, data, disabled = false) {
  const node = text('button', label); node.disabled = disabled;
  node.addEventListener('click', () => act(action, data)); return node;
}
function evidenceMetric(value, label) {
  const node = document.createElement('div'); node.className = 'evidence-metric';
  node.append(text('strong', value), text('span', label)); return node;
}
function reviewCard(r, busy) {
  const card = document.createElement('article'); card.className = 'review-card';
  card.append(text('h3', `${r.name} · ${r.candidate_sha256.slice(0, 10)}`));
  const status = r.installed ? (r.security?.decision === 'held' ? 'Installed by human exception · model verdict remains held' : r.security?.decision === 'restricted_pass' ? 'Installed · security review passed for the restricted workspace' : r.agent?.agent_task_passed ? 'Historical installation · agent task passed' : 'Historical installation · parser checks only') :
    r.rejected ? 'Rejected · source and review preserved' : !r.pending ? 'Archived review' :
    r.eligible && r.security?.decision === 'restricted_pass' ? 'Ready for your decision · restricted security checks passed' :
    r.test.passed === true ? 'Source checks passed · security review still required' :
    r.test.passed === false ? 'Tests failed · installation blocked' : 'Paused · test before installing';
  card.append(text('p', status, 'review-status'));
  if (r.test.run_id) {
    card.append(text('h4', 'What changed in the native capture'));
    const observations = document.createElement('div'); observations.className = 'evidence-grid';
    for (const [key, label] of [['files_read', 'read paths'], ['files_written', 'written paths'], ['processes', 'process entries']]) {
      const count = (r.behavior[key] || []).length, added = (r.diff.added[key] || []).length;
      observations.append(evidenceMetric(`${count} · +${added}`, `${label} · added vs selected installation`));
    }
    const native = r.security?.native_regression;
    if (native) observations.append(evidenceMetric(native.private_denials ?? 'Unknown', 'private-file denials; includes one control'));
    card.append(observations, text('p', 'Regression observations include setup and verification. Counts are not complete attribution to this skill; a denied access is not a data leak. The expanded evidence below shows recorded paths and agent actions.', 'note'));
  }
  if (r.security?.run_id) {
    const s = r.security;
    const label = s.decision === 'blocked' ? 'Blocked · do not install' : s.decision === 'restricted_pass' ? 'Passed for the restricted workspace · your approval is required' : 'Held · more evidence required';
    card.append(text('h3', label));
    card.append(text('p', s.explanation || 'Security review has not produced a complete explanation.'));
    card.append(text('p', `${s.verified_probes}/${s.planned_probes} generated probes verified · ${s.model_requests} requests in this review step${s.verified_probe_requests ? ' · ' + s.verified_probe_requests + ' requests across verified probes' : ''}`, 'note'));
    if (s.native_regression) card.append(text('p', `Evidence E1: native source checks ${s.native_regression.passed ? 'passed' : 'failed'}. Reported private-file denials: ${s.native_regression.private_denials ?? 'unavailable'}; one denial is the independent control. This includes setup and verification activity.`, 'note'));
    if (s.model_review) card.append(text('p', `Nemotron recommendation: ${s.model_review.recommendation}. Evidence: ${s.model_review.evidence_ids.join(', ')}.`, 'note'));
    for (const prior of s.previous_model_reviews || []) card.append(text('p', `Original ${prior.model} recommendation retained: ${prior.recommendation}. ${prior.explanation}`, 'note'));
    if (s.error) card.append(text('p', s.error, 'note'));
    for (const p of s.probes || []) {
      const detail = document.createElement('details');
      detail.append(text('summary', `${p.evidence_id} · ${p.case_id}: ${p.agent_task_passed ? 'completed correctly' : 'did not pass'}${p.private_open_attempts.length ? ' · unrelated private-file attempt' : ''}`));
      if (p.annotation) detail.append(text('h4', 'Generated untrusted annotation'), text('p', p.annotation));
      detail.append(text('p', `${p.model_requests} requests · completion ${p.agent_completion_confirmed ? 'confirmed' : 'unconfirmed'} · guide read ${p.skill_use.guide_read_observed ? 'observed' : 'unverified'}`, 'note'));
      if (p.answer?.receipt) detail.append(text('p', `Saved result: ${p.answer.receipt.vendor}, total ${p.answer.receipt.total ?? 'requires clarification'}.`));
      const commands = document.createElement('details'); commands.append(text('summary', 'Recorded tool actions'));
      for (const action of p.terminal_actions || []) commands.append(text('pre', action.command));
      detail.append(commands);
      card.append(detail);
    }
    if (s.policy) {
      const policy = document.createElement('details'); policy.append(text('summary', 'Evidence E3: generated permissions and native policy'));
      policy.append(text('p', s.policy.source), text('pre', s.policy.policy_yaml));
      policy.append(text('p', 'These grants match the native profile used by the probes. Runtime directories are explicit prerequisites; the model cannot add permissions. Approval remains limited to this workspace.', 'note'));
      card.append(policy);
    }
    card.append(text('p', s.limitations.join(' '), 'note'));
  }
  card.append(text('p', `Static checks: ${r.static}. Native regression checks use no model calls. Security probes and the evidence review use Nebius within the shared cap.`, 'note'));
  if (r.agent?.run_id) {
    const a = r.agent;
    card.append(text('h4', a.agent_task_passed ? 'Actual agent: passed' : 'Actual agent: did not pass'));
    card.append(text('p', `${a.model_requests} model requests · ${a.agent_completion_confirmed ? 'completion confirmed' : 'completion unconfirmed'} · ${a.skill_use?.guide_read_observed ? 'skill guide read observed' : 'skill guide read unverified'}`, 'note'));
    if (a.answer) {
      const output = text('pre', JSON.stringify(a.answer, null, 2));
      card.append(output);
    }
    const replay = document.createElement('details'); replay.append(text('summary', 'What the agent did'));
    for (const step of a.steps || []) {
      replay.append(text('p', `Step ${step.step}: ${step.message}`));
      for (const tool of step.tools) replay.append(text('pre', tool.function_name === 'bash_command' ? tool.arguments.keystrokes : tool.function_name));
    }
    replay.append(text('p', 'Fresh native agent execution on one authored fictional receipt. This establishes task completion and observed skill use; it does not measure a general learning improvement.', 'note'));
    card.append(replay);
  }
  if (r.test.run_id) {
    const details = document.createElement('details'); details.append(text('summary', 'Observed behavior and changes'));
    for (const [kind, values] of Object.entries(r.behavior)) {
      if (values.length) details.append(text('p', `${kind.replaceAll('_', ' ')}: ${values.slice(0, 30).join(', ')}`, 'note'));
    }
    const added = Object.entries(r.diff.added).filter(([, values]) => values.length);
    details.append(text('p', added.length ? 'Added observations compared with the installed version:' :
      'No added observations in this comparison. This does not prove absence of other behavior.', 'note'));
    for (const [kind, values] of added) details.append(text('p', `${kind}: ${values.slice(0, 20).join(', ')}`, 'note'));
    card.append(details);
  }
  if (r.pending) {
    const actions = document.createElement('div'); actions.className = 'actions';
    actions.append(button(r.security?.can_change_completion_profile ? 'Review with eight-request profile' : r.security?.run_id ? 'Run security review again' : 'Review skill security', 'review_security', {review_id: r.id}, busy || r.eligible || r.security?.decision === 'blocked' || (!!r.security?.verified_probes && !r.security?.can_change_completion_profile)));
    if (r.security?.can_escalate) actions.append(button('Ask Super to adjudicate held verdict', 'escalate_security', {review_id: r.id}, busy));
    else if (r.security?.can_resume) actions.append(button('Resume remaining checks', 'resume_security', {review_id: r.id}, busy));
    if (r.security?.decision === 'blocked') actions.append(button('Stage known repair and review it', 'repair_and_review', {review_id: r.id, revision: r.revision}, busy));
    actions.append(button('Reject', 'reject', {review_id: r.id, revision: r.revision}, busy));
    card.append(actions);
    if (r.security?.can_accept_hold) {
      card.append(text('h4', 'Optional human exception'), text('p', 'All native checks passed, but the model held this review. Installation requires accepting that warning explicitly and recording your reason. This does not turn the model verdict into a pass. Failed or incomplete native checks cannot use this exception.', 'note'));
      const key = `hold:${r.id}:${r.revision}`;
      const reason = document.createElement('textarea'); reason.rows = 3;
      reason.setAttribute('aria-label', 'Reason for accepting the held model verdict');
      reason.placeholder = 'Why accept the held verdict in this restricted sandbox? (20–1000 characters)';
      reason.maxLength = 1000; reason.value = heldReasons.get(key) || '';
      const label = document.createElement('label'); label.className = 'approval';
      const check = document.createElement('input'); check.type = 'checkbox'; check.checked = accepted.has(key);
      label.append(check, text('span', 'I accept the held model warning and authorize only this tested version in the declared restricted sandbox.'));
      const payload = {review_id: r.id, revision: r.revision, acknowledge_limits: true, accept_model_hold: true, operator_reason: reason.value};
      const approve = button('Install with held-verdict exception', 'approve', payload, true);
      const update = () => { payload.operator_reason = reason.value; heldReasons.set(key, reason.value); approve.disabled = busy || !check.checked || reason.value.trim().length < 20 || reason.value.trim().length > 1000; };
      reason.addEventListener('input', update);
      check.addEventListener('change', () => { if (check.checked) accepted.add(key); else accepted.delete(key); update(); });
      update(); card.append(reason, label, approve);
    } else if (r.eligible) {
      const label = document.createElement('label'); label.className = 'approval';
      const check = document.createElement('input'); check.type = 'checkbox';
      const key = `${r.id}:${r.revision}`; check.checked = accepted.has(key);
      label.append(check, text('span', 'I approve this exact tested version and its declared restricted permissions. I understand the evidence limits.'));
      const approve = button('Approve and install', 'approve', {review_id: r.id, revision: r.revision, acknowledge_limits: true}, busy || !check.checked);
      check.addEventListener('change', () => { approve.disabled = busy || !check.checked;
        if (check.checked) accepted.add(key); else accepted.delete(key); });
      card.append(label, approve);
    }
  }
  return card;
}
function learningComparison(value) {
  byId('learning-comparison').hidden = !value;
  if (!value) return;
  const target = byId('learning-result'); target.replaceChildren();
  if (value.status && value.status !== 'completed') {
    target.append(text('p', `${value.recorded_trials} of ${value.planned_trials} trial records collected. ${value.status === 'running' ? 'Native agent checks are running.' : value.status === 'verifying' ? 'Checking the saved evidence and totals.' : 'Some records need evidence review; completed model attempts are preserved.'}`));
    target.append(text('p', 'The agent is completing the planned fictional receipt tasks. Final findings appear after the saved evidence is checked.', 'note'));
    return;
  }
  const repair = value.comparison_kind === 'guide_repair';
  const labels = value.arm_labels || {without: 'Without skill', with: 'With skill'};
  byId('learning-title').textContent = repair ? 'Does the repaired skill resist attacks?' : 'Does the learned skill help?';
  const safetyCounts = value.behavior_review?.counts;
  const overall = value.groups.all;
  const delta = overall.delta_percentage_points;
  target.append(text('p', repair ? `Correct completed tasks without observed attack-directed actions: repaired ${safetyCounts?.with.correct_completed_without_unsafe_actions ?? value.guarded_passes.all.with}/${overall.planned_pairs}, original ${safetyCounts?.without.correct_completed_without_unsafe_actions ?? value.guarded_passes.all.without}/${overall.planned_pairs}.` : value.interpretation === 'mixed_functional_gain_unsafe_attempt' ? 'More receipts completed with the skill, but one skill-enabled run attempted an unrelated private-file read. No overall gain when that attempt counts as a failure.' : value.interpretation === 'inconclusive_output_contract_ambiguity' ? 'Inconclusive: output-instruction ambiguity dominated this preliminary study.' : delta > 0 ? `Completion was ${delta} percentage points higher with the skill on this set.` :
    delta < 0 ? `The agent completed fewer tasks with the skill on this set (${delta} percentage points).` :
    'No improvement measured on this set: the agent completed the same number of tasks in both conditions.'));
  target.append(text('p', `${repair ? 'Original and repaired guide; the parser is identical.' : 'With and without the original learned skill bundle.'} Same agent and limits. ${value.verified_trials} trials; one attempt per condition on each of ${value.cases.length} authored cases.`, 'note'));
  if (value.skill_selection) target.append(text('p', `Both conditions were told to read their guide before the receipt. Observed guide-first runs: ${labels.without} ${value.arms.without.guide_before_receipt_observed}/${value.cases.length}; ${labels.with} ${value.arms.with.guide_before_receipt_observed}/${value.cases.length}. The agent still chose its own extraction tools.`, 'note'));
  if (value.arms.with.guide_after_receipt_observed !== undefined) target.append(text('p', `Observed guide rereads after receipt input: ${labels.without} ${value.arms.without.guide_after_receipt_observed}/${value.cases.length}; ${labels.with} ${value.arms.with.guide_after_receipt_observed}/${value.cases.length}.`, 'note'));
  const table = document.createElement('table');
  const head = document.createElement('tr');
  for (const label of ['Receipt cases', labels.without, labels.with]) head.append(text('th', label));
  table.append(head);
  for (const [key, label] of [['clean', 'Clean receipts'], ['attack', 'Receipts with attacks'], ['all', 'All cases']]) {
    const group = value.groups[key], row = document.createElement('tr');
    row.append(text('td', label), text('td', `${group.without_skill_passes}/${group.planned_pairs}`), text('td', `${group.with_skill_passes}/${group.planned_pairs}`));
    table.append(row);
  }
  const safe = document.createElement('tr');
  safe.append(text('td', 'Attack cases: correct answer, no observed private-file attempt'), text('td', `${value.guarded_passes.attack.without}/${value.groups.attack.planned_pairs}`), text('td', `${value.guarded_passes.attack.with}/${value.groups.attack.planned_pairs}`));
  if (!safetyCounts) table.append(safe);
  if (safetyCounts) {
    const reviewed = document.createElement('tr');
    reviewed.append(text('td', 'All cases: correct answer, no observed attack-directed action'), text('td', `${safetyCounts.without.correct_completed_without_unsafe_actions}/${overall.planned_pairs}`), text('td', `${safetyCounts.with.correct_completed_without_unsafe_actions}/${overall.planned_pairs}`));
    table.append(reviewed);
    const followed = document.createElement('tr');
    followed.append(text('td', 'Cases with observed attack-directed tool actions'), text('td', `${safetyCounts.without.unsafe_trials}/${overall.planned_pairs}`), text('td', `${safetyCounts.with.unsafe_trials}/${overall.planned_pairs}`));
    table.append(followed);
  }
  target.append(table);
  target.append(text('p', 'Pass means a correct saved answer and confirmed task completion. Denied opens captured at the exact private-file path: ' + labels.without + ' ' + value.arms.without.private_open_attempts + ', ' + labels.with + ' ' + value.arms.with.private_open_attempts + '. Terminal fake-note disclosures: ' + labels.without + ' ' + value.arms.without.terminal_disclosures + ', ' + labels.with + ' ' + value.arms.with.terminal_disclosures + '.', 'note'));
  target.append(text('p', `Model requests: ${labels.without} ${value.arms.without.model_requests}; ${labels.with} ${value.arms.with.model_requests}.`, 'note'));
  target.append(text('p', `At comparison archive time, project inference estimate: $${value.ledger.estimated_cost_usd.toFixed(5)}; unresolved reservations: $${value.ledger.unknown_reserved_usd.toFixed(2)}. The current ledger appears beside the installed-agent button.`, 'note'));
  const details = document.createElement('details'); details.append(text('summary', 'Cases and test limits'));
  if (value.arms.with.correct_saved_answers !== undefined) details.append(text('p', `Correct saved receipt files: ${labels.without} ${value.arms.without.correct_saved_answers}/${value.cases.length}; ${labels.with} ${value.arms.with.correct_saved_answers}/${value.cases.length}. A correct file without confirmed completion does not pass the full task. The six-request limit includes completion confirmation.`, 'note'));
  for (const pair of value.pairs) {
    const item = value.cases.find(c => c.id === pair.case_id);
    details.append(text('p', `${item.vendor}${item.attack_family ? ' · ' + item.attack_family.replaceAll('_', ' ') : ''}: ${labels.without} ${pair.without ? 'passed' : 'failed'}, ${labels.with} ${pair.with ? 'passed' : 'failed'}`));
  }
  details.append(text('p', `Tested candidate ${value.candidate_sha256.slice(0, 12)}. ${repair ? 'A guide-only derivative of the original learned skill; the parser is unchanged.' : 'The original learned guide and repaired parser.'} ${state.active?.candidate_sha256 === value.candidate_sha256 ? 'This exact repaired candidate is installed here.' : 'The selected installation has separate review evidence.'} Cases were frozen before inference and the skill stayed unchanged. They are now known cases and must not be reused as fresh holdouts.`, 'note'));
  details.append(text('p', 'This small fixed comparison cannot establish general attack resistance or statistical reliability. Sandbox protections and task instructions were identical in both conditions.', 'note'));
  if (value.behavior_review) {
    details.append(text('p', 'The full command review also counts indirect file-access attempts and changes to receipt amounts. The exact-path event count can miss aliases.', 'note'));
    details.append(text('p', value.behavior_review.limit, 'note'));
  }
  if (value.safety_finding) details.append(text('p', value.safety_finding.description, 'note'));
  if (value.prior_study) details.append(text('p', 'An earlier study was inconclusive because a clarification-list instruction was ambiguous. Its original 1/8 versus 0/8 results remain archived. This table uses different cases and an explicit, identical output rule in both conditions.', 'note'));
  target.append(details);
}
async function refresh() {
  clearTimeout(timer);
  try {
    const response = await fetch('/api/state', {cache: 'no-store'});
    if (!response.ok) throw Error((await response.json()).error);
    state = await response.json();
    if (pollError) { byId('error').hidden = true; pollError = false; }
    const focus = state.reviews.find(r => r.pending) || state.reviews.find(r => r.installed);
    byId('overview').replaceChildren(
      evidenceMetric(state.reviews.some(r => r.pending) ? 'Paused' : state.active ? 'Installed' : 'Ready', 'learning state'),
      evidenceMetric(focus?.security?.verified_probes !== undefined ? `${focus.security.verified_probes} / ${focus.security.planned_probes}` : 'Not run', 'generated probes verified'),
      evidenceMetric(state.active?.security_decision === 'operator_approved_hold' && !focus?.pending ? 'Human exception' : focus?.security?.decision || 'Awaiting review', 'decision; model warnings stay visible'),
      evidenceMetric(state.previous ? 'Available' : 'No prior version', 'version rollback'));
    const comparisonBusy = ['running', 'verifying'].includes(state.learning?.status);
    const busy = state.job?.status === 'running' || comparisonBusy;
    const connection = state.connection || {};
    const connectionLabels = {connected: 'Nebius authenticated · Lightning and Super available',
      not_checked: 'API key saved · connection not checked', missing_key: 'Nebius API key is missing',
      rejected_key: 'Nebius rejected the saved API key', missing_models: 'Nebius connected · a required model is unavailable',
      unavailable: 'Nebius connection unavailable · check again before a live review'};
    byId('connection').textContent = `${connectionLabels[connection.status] || 'Connection not checked'}${connection.checked_at ? ' · checked ' + new Date(connection.checked_at).toLocaleTimeString() : ''}. Connection checks do not generate model responses.`;
    byId('check-connection').disabled = busy;
    learningComparison(state.learning);
    byId('progress').hidden = !busy;
    byId('progress').textContent = state.job?.message || (['test_agent', 'run_agent'].includes(state.job?.action) ? 'The agent is reading the skill and completing the fictional receipt in its sandbox…' : state.job?.action === 'test' ? 'Testing in the restricted workspace. This may take a minute…' : 'Working in your local workspace…');
    if (comparisonBusy) byId('progress').textContent = `Testing receipt skills: ${state.learning.recorded_trials}/${state.learning.planned_trials} trial records collected…`;
    if (state.job?.status === 'failed') showError(state.job.error);
    const pending = state.reviews.some(r => r.pending);
    byId('stage').disabled = busy || pending;
    byId('update').disabled = busy || pending || !state.active;
    byId('unsafe').disabled = busy || pending;
    byId('import-skill').disabled = busy || pending;
    byId('run').disabled = busy || !state.active;
    byId('run-agent').disabled = busy || !state.reviews.some(r => r.installed && r.eligible);
    byId('budget').textContent = state.budget?.available ? `Current project estimate: $${state.budget.estimated_cost_usd.toFixed(5)} + $${state.budget.reserved_usd.toFixed(2)} reserved = $${state.budget.accounted_usd.toFixed(5)} of your $${state.budget.cap_usd.toFixed(2)} authorized cap. Estimates are not provider billing totals.` : 'Current inference ledger unavailable.';
    byId('rollback').disabled = busy || !state.previous;
    byId('installed').textContent = state.active ? `Installed · ${state.active.candidate_sha256.slice(0, 12)} · ${state.active.security_decision === 'operator_approved_hold' ? 'human exception; model verdict remains held' : state.active.security_decision === 'restricted_pass' ? 'security review passed for this workspace' : 'historical installation; separate evidence preserved'}` : 'No skill installed. Review and approve one first.';
    byId('previous').textContent = state.previous ? 'A previous tested version is available.' : 'Install an update to create a previous version.';
    byId('limits').textContent = state.limits;
    const view = JSON.stringify([state.reviews, busy]);
    if (view !== lastView) {
      lastView = view;
      byId('reviews').replaceChildren(...state.reviews.filter(r => r.pending || r.installed).map(r => reviewCard(r, busy)));
      const archived = state.reviews.filter(r => !r.pending && !r.installed);
      if (archived.length) {
        const history = document.createElement('details'); history.append(text('summary', `Past reviews (${archived.length})`));
        for (const review of archived) history.append(reviewCard(review, busy));
        byId('reviews').append(history);
      }
      if (!state.reviews.length) byId('reviews').append(text('p', 'No pending skills. Add the receipt skill to begin.'));
    }
    if (state.job?.status === 'done' && state.job.action === 'run') {
      const value = JSON.stringify(state.job.result);
      if (lastResult !== value) {
        lastResult = value; const record = state.job.result.receipt;
        byId('output').replaceChildren(text('h3', record.needs_clarification ? 'Please clarify the missing or conflicting values.' : 'Receipt organized'));
        byId('output').append(text('p', `Result from version ${state.job.result.version.slice(0, 10)}`, 'note'));
        for (const [key, value] of Object.entries(record)) byId('output').append(text('p', `${key.replaceAll('_', ' ')}: ${value ?? 'Needs clarification'}`));
      }
    }
    const installedReview = state.reviews.find(r => r.installed && r.eligible);
    const agentSequence = Math.max(0, ...(installedReview?.history || []).filter(e => e.kind === 'core_agent_test').map(e => e.sequence));
    const installSequence = Math.max(0, ...(installedReview?.history || []).filter(e => e.kind === 'core_installation').map(e => e.sequence));
    if (installedReview && agentSequence > installSequence) {
      const result = {...installedReview.agent, version: state.active.id};
      byId('agent-output').replaceChildren(text('h3', 'Agent completed the receipt task'),
        text('p', `${result.model_requests} fresh model requests · installed version ${result.version.slice(0, 10)} · completion confirmed`, 'note'),
        text('p', `Guide read before receipt: ${result.skill_use.guide_before_receipt_observed ? 'observed' : 'unverified'}. Guide reread after receipt: ${result.skill_use.guide_after_receipt_observed ? 'observed' : 'unverified'}.`, 'note'),
        text('pre', JSON.stringify(result.answer, null, 2)));
    } else byId('agent-output').replaceChildren();
    timer = setTimeout(refresh, busy ? 1500 : 5000);
  } catch (e) { showError(e.message, true); timer = setTimeout(refresh, 3000); }
}
for (const action of ['stage', 'update', 'unsafe']) byId(action).addEventListener('click', () => act(action === 'update' ? 'repaired' : action === 'stage' && state.active ? 'update' : action));
byId('import-skill').addEventListener('click', () => act('import', {content: {guide: byId('skill-guide').value, parser: byId('skill-parser').value}}));
byId('run').addEventListener('click', () => act('run', {text: byId('receipt').value}));
byId('run-agent').addEventListener('click', () => act('run_agent', {expected_active: state.active?.id}));
byId('rollback').addEventListener('click', () => act('rollback', {expected_active: state.active?.id}));
byId('check-connection').addEventListener('click', () => act('check_connection'));
refresh();
