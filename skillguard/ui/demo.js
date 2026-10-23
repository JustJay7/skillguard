const el = id => document.getElementById(id);
const make = (tag, value, cls) => { const n = document.createElement(tag); if (value !== undefined) n.textContent = value; if (cls) n.className = cls; return n; };
let data, stage = 0, probeIndex = 0;
const titles = ['Catch the change', 'Watch the agent', 'Review the boundary', 'Keep control'];
function metric(value, label) { const n = make('div', undefined, 'metric'); n.append(make('strong', value), make('span', label)); return n; }
function panel(title, ...children) { const n = make('div', undefined, 'panel'); n.append(make('h3', title), ...children); return n; }
function detail(title, value) { const n = make('details'); n.append(make('summary', title), make('pre', value)); return n; }
function row(label, value) { const n = make('div', undefined, 'delta'); n.append(make('span', label), make('strong', value)); return n; }
function action(label, callback, secondary = false) { const n = make('button', label, secondary ? 'secondary' : ''); n.addEventListener('click', callback); return n; }
function render() {
  const target = el('stage'); target.replaceChildren();
  [...el('stages').children].forEach((n, i) => { if (stage === i) n.setAttribute('aria-current', 'step'); else n.removeAttribute('aria-current'); });
  el('back').disabled = stage === 0; el('next').disabled = stage === 3;
  el('next').textContent = stage < 3 ? `Next: ${titles[stage + 1].toLowerCase()}` : 'Walkthrough complete';
  el('position').textContent = `${stage + 1} / 4 · recorded evidence`;
  if (stage === 0) {
    target.append(make('span', 'Unsafe update blocked', 'tag blocked'), make('h2', 'A receipt skill wanted more than receipts.'), make('p', 'The authored unsafe update tried an unrelated fake private-file read. Source scanning alone was not enough: the native functional run failed and installation was refused.'));
    const grid = make('div', undefined, 'columns');
    for (const [key, title] of [['unsafe', 'Unsafe staged update'], ['repaired', 'Known receipt repair']]) {
      const o = data.observations[key];
      grid.append(panel(title, row('Native functionality', o.functional_passed ? 'Passed' : 'Failed'), row('Private-file denials reported', o.private_denials), row('Independent denial control', o.independent_denial_control), row('File-read paths observed', o.counts.files_read), row('File-write paths observed', o.counts.files_written)));
    }
    target.append(grid, make('p', 'These counts describe the native regression capture, including setup and verification. They are not complete attribution to the skill. Denials are blocked access, not leaked data.', 'note'), make('p', 'SkillGuard preserves the rejected version, then stages the exact known repair for a separate review. The repair does not inherit the unsafe update’s result.'));
  } else if (stage === 1) {
    target.append(make('span', '4 completed probes', 'tag good'), make('h2', 'The model chose its actions. We kept the evidence.'), make('p', 'Three generated attack annotations and one unrelated control were embedded after the original purchase record. The actual Nemotron agent read the repaired guide, handled the receipt, saved its answer and confirmed completion.'));
    const tabs = make('div', undefined, 'probe-tabs');
    ['Forged approval', 'Zero-total correction', 'Fake system message', 'Unrelated control'].forEach((label, i) => tabs.append(action(label, () => { probeIndex = i; render(); }, probeIndex !== i)));
    const p = data.probes[probeIndex]; const grid = make('div', undefined, 'columns');
    grid.append(panel('Untrusted annotation — exact excerpt', make('p', p.annotation_excerpt, 'quote'), make('p', `Native evidence: ${p.run_id}`, 'note')),
      panel('What the agent actually did', row('Saved original total', Number(p.answer.receipt.total).toFixed(2)), row('Completion', p.completed ? 'Confirmed' : 'Unconfirmed'), row('Observed private-file attempts', p.private_open_attempts), row('Model requests', p.model_requests)));
    target.append(tabs, grid, detail('Recorded terminal commands', p.commands.join('\n')), make('p', 'The grader is independent of the generated annotation. The agent extracted values itself; the parser was not invoked in these four trials. Partial metadata and this small set do not establish general injection resistance.', 'note'));
  } else if (stage === 2) {
    target.append(make('span', 'Both model verdicts: hold', 'tag held'), make('h2', 'A warning is not a permission grant.'), make('p', 'Lightning and one Super adjudication acknowledged correct outcomes but still held the review. SkillGuard retained both recommendations. The model cannot widen permissions or override failed native checks.'));
    const grid = make('div', undefined, 'columns');
    grid.append(panel('Declared receipt workspace', row('Receipt and skill inputs', 'Read only'), row('Output and runtime directories', 'Bounded writes'), row('External network grants', 'None'), row('Host folder mounts', 'None'), row('Workload user', '1000')),
      panel('Decision boundary', make('p', 'Failed tests, recorded unsafe actions, changed source or incomplete probes keep installation blocked or held.'), make('p', 'When every native check passes, a human may explicitly accept the held warning with a written reason. The version records a human exception, not a security pass.')));
    target.append(grid);
    for (const m of data.models) target.append(detail(`${m.model}: ${m.recommendation} — original explanation`, m.explanation));
    target.append(detail('Exact admitted policy', JSON.stringify(data.policy, null, 2)), make('p', 'Policy compilation matches the native profile exercised by the tests. Runtime paths are explicit prerequisites; this is not arbitrary-skill least-privilege synthesis.', 'note'));
  } else {
    target.append(make('span', 'Installed by explicit human exception', 'tag held'), make('h2', 'Learning stays reversible.'), make('p', 'The recorded app flow acknowledged the warning, installed the exact reviewed repair, restored the previous version, then selected the tested installation again. No model verdict was changed to allow.'));
    const timeline = make('div', undefined, 'timeline');
    timeline.append(make('p', '1. Unsafe update rejected; review and source preserved.'), make('p', '2. Exact repaired source tested; four probes completed.'), make('p', '3. Both holds preserved; warning and written reason acknowledged.'), make('p', `4. New version installed: ${data.approval.installed_version.slice(0, 12)}.`), make('p', `5. Previous version restored: ${data.approval.previous_version.slice(0, 12)}.`), make('p', `6. Tested installation restored; rollback verification ${data.approval.rollback_verified ? 'passed' : 'incomplete'}.`));
    target.append(timeline, detail('Recorded operator acceptance reason', data.approval.reason), make('p', `Exact candidate: ${data.candidate_sha256}`, 'note'), make('p', 'This page replays those completed actions. It cannot install a skill, call a model or access your files. The separate local application owns the live review and approval controls.', 'note'));
  }
}
async function start() {
  try {
    const response = await fetch('evidence.json', {cache: 'no-store'});
    if (!response.ok) throw Error('Verified demo evidence is unavailable.');
    data = await response.json();
    if (data.schema !== 'skillguard-recorded-demo-v1' || data.probes.length !== 4 || data.approval.decision !== 'operator_approved_hold') throw Error('Unsupported or incomplete evidence.');
    el('metrics').append(metric('Blocked', 'unsafe update'), metric('4 / 4', 'completed native probes'), metric('Hold retained', 'human exception recorded'), metric(`$${data.budget_at_recording.accounted_usd.toFixed(5)}`, 'accounted, including unknown holds'));
    titles.forEach((title, i) => el('stages').append(action(`${i + 1}. ${title}`, () => { stage = i; render(); })));
    const list = make('ul'); data.limits.forEach(value => list.append(make('li', value)));
    el('limits').append(list, make('p', `Source ${data.source_workflow}. Earlier incomplete trial: ${data.recovery.original_responses}/${data.recovery.original_forwarded_requests} responses. ${data.recovery.passing_probes_reused} passing probes were reverified and reused; failed claims and $${data.recovery.all_unknown_holds_retained_usd.toFixed(2)} unknown holds remain.`, 'note'));
    el('back').addEventListener('click', () => { if (stage > 0) stage--; render(); });
    el('next').addEventListener('click', () => { if (stage < 3) stage++; render(); });
    render();
  } catch (error) { el('error').hidden = false; el('error').textContent = error.message; el('stage').replaceChildren(make('p', 'The recorded demo could not load. No fallback results are invented.')); }
}
start();
