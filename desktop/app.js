/* LinkedIn Content Copilot — desktop console.
 *
 * Talks to the same /api/v1 the phone uses. It runs on the same machine as the
 * backend, so it gets its token from the loopback-only desktop-session
 * endpoint instead of asking the user to type a pairing code.
 *
 * Rules kept from the phone app, deliberately:
 *  - every approval sends the hash of the exact text on screen, so the server
 *    can refuse it if the draft changed underneath;
 *  - a metric that was never collected renders as an em dash, never 0.
 */

const API = '';                    // same origin
let TOKEN = null;
let STATE = {
  route: 'dashboard',
  briefing: null,
  drafts: [],
  calendar: [],
  connections: [],
  analytics: null,
  status: null,
  settings: null,
  draft: null,          // open draft detail
  queueIndex: 0,
};

const PAGES = [
  { id: 'dashboard', label: 'Dashboard', icon: '◆' },
  { id: 'approvals', label: 'Approvals', icon: '✓', countKey: 'pending_approvals' },
  { id: 'calendar',  label: 'Calendar',  icon: '▤' },
  { id: 'network',   label: 'Network',   icon: '◎', countKey: 'connections_to_review' },
  { id: 'analytics', label: 'Analytics', icon: '▦' },
  { id: 'profile',   label: 'Profile',   icon: '☰' },
  { id: 'settings',  label: 'Settings',  icon: '⚙' },
];

// ---------------------------------------------------------------- utils ----
const $ = (sel, root = document) => root.querySelector(sel);
const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (v) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString();

function toast(msg, bad = false) {
  const node = el(`<div class="toast ${bad ? 'bad' : ''}">${esc(msg)}</div>`);
  $('#toasts').appendChild(node);
  setTimeout(() => { node.style.opacity = '0'; setTimeout(() => node.remove(), 250); }, bad ? 6500 : 3800);
}

function busy(on) { $('#busy').style.display = on ? '' : 'none'; }

function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  if (isNaN(d)) return '—';
  return d.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

function fmtRelativeDay(iso) {
  if (!iso) return '—';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  if (isNaN(d)) return '—';
  const days = Math.round((d.setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000);
  const time = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
    .toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  const prefix = days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : days === -1 ? 'Yesterday'
    : new Date(iso).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  return `${prefix} · ${time}`;
}

function ago(iso) {
  if (!iso) return '';
  const mins = Math.floor((Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z')) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / 1440)}d ago`;
}

const titleCase = (s) => String(s || '').split('_').map(w => w.charAt(0) + w.slice(1).toLowerCase()).join(' ');

const STATUS_LABEL = {
  READY_FOR_REVIEW: 'Needs review', SAVED_FOR_LATER: 'Saved', APPROVED: 'Approved',
  SCHEDULED: 'Scheduled', PUBLISHING: 'Ready to post', PUBLISHED: 'Published',
  REJECTED: 'Rejected', FAILED: 'Failed', CANCELLED: 'Cancelled',
  DRAFT: 'Drafting', QUALITY_CHECK: 'Drafting',
};
const STATUS_CLASS = {
  READY_FOR_REVIEW: 'accent', APPROVED: 'info', SCHEDULED: 'info', PUBLISHING: 'warn',
  PUBLISHED: 'accent', REJECTED: 'danger', FAILED: 'danger', CANCELLED: 'danger',
};

// ------------------------------------------------------------------ api ----
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;
  let res;
  try {
    res = await fetch(API + path, { ...opts, headers });
  } catch (e) {
    setConnected(false, 'Backend unreachable');
    throw new Error('Could not reach the backend. Is it running?');
  }
  if (res.status === 204) return null;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const message = body?.message || `Request failed (${res.status})`;
    const err = new Error(message);
    err.code = body?.code; err.recovery = body?.recovery; err.status = res.status;
    throw err;
  }
  setConnected(true);
  return body;
}

async function connect() {
  const session = await api('/api/v1/auth/desktop-session', { method: 'POST' });
  TOKEN = session.token;
  $('#brand-sub').textContent = session.timezone;
}

function setConnected(ok, text) {
  $('#conn-dot').className = 'dot ' + (ok ? 'ok' : 'bad');
  $('#conn-text').textContent = text || (ok ? 'Backend connected' : 'Backend offline');
}

// --------------------------------------------------------------- render ----
function renderNav() {
  const nav = $('#nav');
  nav.innerHTML = '';
  for (const page of PAGES) {
    const count = page.countKey && STATE.briefing ? STATE.briefing[page.countKey] : 0;
    const btn = el(`
      <button class="${STATE.route === page.id ? 'active' : ''}" data-page="${page.id}">
        <span class="icon">${page.icon}</span>
        <span>${page.label}</span>
        ${count ? `<span class="count">${count}</span>` : ''}
      </button>`);
    btn.onclick = () => go(page.id);
    nav.appendChild(btn);
  }
}

function go(route, param) {
  STATE.route = route;
  if (route !== 'draft') STATE.draft = null;
  $('#page-title').textContent = route === 'draft' ? 'Review post'
    : (PAGES.find(p => p.id === route)?.label || 'Dashboard');
  renderNav();
  render(param);
}

async function render(param) {
  const view = $('#view');
  try {
    busy(true);
    switch (STATE.route) {
      case 'dashboard': await viewDashboard(view); break;
      case 'approvals': await viewApprovals(view); break;
      case 'draft':     await viewDraft(view, param); break;
      case 'calendar':  await viewCalendar(view); break;
      case 'network':   await viewNetwork(view); break;
      case 'analytics': await viewAnalytics(view); break;
      case 'profile':   await viewProfile(view); break;
      case 'settings':  await viewSettings(view); break;
    }
  } catch (e) {
    view.innerHTML = `<div class="banner bad"><strong>${esc(e.message)}</strong>${e.recovery ? `<div class="muted small" style="margin-top:4px">${esc(e.recovery)}</div>` : ''}</div>`;
  } finally {
    busy(false);
  }
}

// ------------------------------------------------------------ dashboard ----
async function viewDashboard(view) {
  const b = STATE.briefing = await api('/api/v1/briefing');
  STATE.status = await api('/api/v1/system/status').catch(() => null);
  renderNav();

  const next = b.next_scheduled_at
    ? `<div class="card"><div class="section-title" style="margin:0 0 6px">Next out</div>
         <div style="font-size:17px;font-weight:600">${esc(fmtRelativeDay(b.next_scheduled_at))}</div>
         <div class="muted small" style="margin-top:3px">${esc(b.next_scheduled_title || '')}</div></div>`
    : '';

  view.innerHTML = `
    <div class="card ${b.pending_approvals ? '' : ''}" style="${b.pending_approvals ? 'border-color:var(--accent-dim);background:rgba(111,211,154,0.06)' : ''}">
      <div class="row between">
        <div>
          <div style="font-size:18px;font-weight:600">
            ${b.pending_approvals
              ? `${b.pending_approvals} draft${b.pending_approvals === 1 ? '' : 's'} waiting for you`
              : 'Nothing waiting on you'}
          </div>
          <div class="muted small" style="margin-top:3px">
            ${b.pending_approvals ? 'Nothing publishes until you approve it.' : 'The copilot will queue drafts here as it writes them.'}
          </div>
        </div>
        ${b.pending_approvals ? `<button class="btn primary" onclick="go('approvals')">Review now</button>` : ''}
      </div>
    </div>

    <div class="grid cols-4" style="margin-top:12px">
      ${statCard('Scheduled', b.scheduled_posts)}
      ${statCard('Published', b.published_total)}
      ${statCard('This week', b.published_this_week)}
      ${statCard('To connect', b.connections_to_review)}
    </div>

    ${next}

    ${b.top_insight ? `
      <div class="section-title">What's working</div>
      <div class="card">${esc(b.top_insight)}</div>` : ''}

    <div class="section-title">Spoken summary</div>
    <div class="card muted" style="line-height:1.65">${esc(b.speech)}</div>

    <div class="section-title">System</div>
    <div class="card">${componentRows(STATE.status)}</div>
  `;
}

function statCard(label, value) {
  const zero = !value;
  return `<div class="card stat"><div class="value ${zero ? 'muted' : ''}">${num(value)}</div><div class="label">${esc(label)}</div></div>`;
}

function componentRows(status) {
  if (!status) return '<span class="muted">Could not read system status.</span>';
  const rows = [
    ['Backend', status.backend], ['Database', status.database], ['Scheduler', status.scheduler],
    ['AI provider', status.ai_provider], ['LinkedIn', status.linkedin],
  ];
  return rows.map(([label, c]) => `
    <div class="row between" style="padding:5px 0">
      <span>${esc(label)}</span>
      <span class="row">
        <span class="tiny faint">${esc(c.detail || '')}</span>
        <span class="pill ${c.status === 'ok' ? 'accent' : c.status === 'error' ? 'danger' : ''}">${esc(c.status.replace('_', ' '))}</span>
      </span>
    </div>`).join('');
}

// ------------------------------------------------------------ approvals ----
async function viewApprovals(view) {
  const res = await api('/api/v1/drafts');
  STATE.drafts = res.items;

  if (!res.items.length) {
    view.innerHTML = emptyState('Nothing to review',
      'When the copilot writes something worth your time it appears here. Weak drafts are rejected before they ever reach this screen.',
      `<button class="btn" onclick="openIdeaDialog()">Write a custom idea</button>`);
    return;
  }

  view.innerHTML = `
    <div class="row between" style="margin-bottom:14px">
      <span class="muted small">${res.total} awaiting your decision</span>
      <button class="btn" onclick="openIdeaDialog()">Write a custom idea</button>
    </div>
    ${res.items.map(draftCard).join('')}
  `;
}

function draftCard(d) {
  const q = d.quality_score;
  const meterClass = q >= 75 ? '' : q >= 60 ? 'warn' : 'bad';
  return `
    <div class="card clickable" onclick="go('draft', ${d.id})">
      <div class="row between">
        <span class="pill info">${esc(titleCase(d.post_type))}</span>
        <span class="pill ${STATUS_CLASS[d.status] || ''}">${esc(STATUS_LABEL[d.status] || d.status)}</span>
      </div>
      <div style="font-weight:600;margin-top:10px;font-size:15px">${esc(d.hook || d.title)}</div>
      <div class="muted small" style="margin-top:5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${esc(d.preview || '')}</div>
      <div class="row" style="margin-top:12px;gap:16px">
        ${q !== null && q !== undefined ? `<span style="min-width:104px;display:inline-block">
          <span class="tiny faint">Quality ${q}</span>
          <span class="meter ${meterClass}"><span style="width:${Math.max(0, Math.min(100, q))}%"></span></span>
        </span>` : ''}
        <span class="tiny faint">${num(d.char_count)} chars</span>
        ${d.version_count > 1 ? `<span class="tiny faint">${d.version_count} versions</span>` : ''}
        <span class="tiny faint">${esc(ago(d.created_at))}</span>
      </div>
    </div>`;
}

// ----------------------------------------------------------- draft view ----
async function viewDraft(view, draftId) {
  const id = draftId ?? STATE.draft?.id;
  const d = STATE.draft = await api(`/api/v1/drafts/${id}`);
  const v = d.current_version;
  const quality = v?.quality || {};
  const issues = quality.issues || [];

  view.innerHTML = `
    <button class="btn ghost sm" onclick="go('approvals')">&larr; Back to queue</button>

    <div class="row wrap" style="margin:14px 0 12px;gap:8px">
      <span class="pill info">${esc(titleCase(d.post_type))}</span>
      <span class="pill ${STATUS_CLASS[d.status] || ''}">${esc(STATUS_LABEL[d.status] || d.status)}</span>
      ${d.has_valid_approval ? '<span class="pill accent">Approved</span>' : ''}
    </div>

    <div id="post-area"></div>

    ${d.versions.length > 1 ? `
      <div class="section-title">Versions</div>
      <div class="row wrap">
        ${d.versions.map(ver => `
          <button class="btn sm ${ver.id === v?.id ? 'primary' : ''}" onclick="selectVersion(${d.id}, ${ver.id})">
            ${esc(ver.label)} · ${ver.char_count}
          </button>`).join('')}
      </div>` : ''}

    <div class="section-title">Why this was written</div>
    <div class="card muted small">${esc(d.generation_reason || 'Added directly by you.')}</div>

    ${Object.keys(quality).length ? `
      <div class="section-title">Quality check</div>
      <div class="card">
        <div class="grid cols-4">
          ${qualityStat('Quality', quality.quality)}
          ${qualityStat('Originality', quality.originality)}
          ${qualityStat('Specificity', quality.specificity)}
          ${qualityStat('AI-slop', quality.ai_slop_probability, true)}
        </div>
        ${issues.length ? `<div style="margin-top:12px">${issues.map(i => `<div class="small" style="color:var(--warn);margin-top:3px">• ${esc(i)}</div>`).join('')}</div>` : ''}
      </div>` : ''}

    ${d.sources?.length ? `
      <div class="section-title">Sources</div>
      <div class="card">${d.sources.map(s => `
        <div style="margin-bottom:6px">
          <div class="small">${esc(s.title || s.url || '')}</div>
          ${s.url ? `<a class="tiny" href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.url)}</a>` : ''}
        </div>`).join('')}</div>` : ''}

    ${d.uncertainty_notes ? `
      <div class="section-title">Not verified</div>
      <div class="card muted small">${esc(d.uncertainty_notes)}</div>` : ''}

    <div class="section-title">Rewrite</div>
    <div class="row wrap">
      ${['shorten', 'expand', 'more_technical', 'more_casual', 'rewrite_hook', 'regenerate']
        .map(op => `<button class="btn sm" onclick="rewrite(${d.id}, '${op}')">${esc(titleCase(op))}</button>`).join('')}
    </div>

    <div class="section-title">Publish time</div>
    <div class="card">
      <div class="row wrap" style="gap:8px">
        <button class="btn sm" id="slot-auto" onclick="setSchedule(null)">Next free slot</button>
        <button class="btn sm" onclick="setSchedule(tomorrowAt(9))">Tomorrow 9 AM</button>
        <button class="btn sm" onclick="setSchedule(tomorrowAt(17))">Tomorrow 5 PM</button>
        <input class="field" type="datetime-local" id="custom-when" style="width:auto" onchange="setSchedule(this.value ? new Date(this.value).toISOString() : null)">
      </div>
      <div class="muted small" style="margin-top:8px" id="schedule-label">Publishing into the next free slot.</div>
    </div>

    <div class="row" style="margin-top:22px;gap:10px">
      <button class="btn primary" id="btn-approve" onclick="approve(${d.id})">Approve &amp; schedule</button>
      <button class="btn" id="btn-edit" onclick="toggleEdit()">Edit</button>
      <div class="spacer" style="flex:1"></div>
      <button class="btn ghost" onclick="saveForLater(${d.id})">Save for later</button>
      <button class="btn danger" onclick="openRejectDialog(${d.id})">Reject</button>
    </div>
  `;
  STATE.editing = false;
  STATE.scheduleAt = null;
  renderPostArea();
}

function qualityStat(label, value, isProbability) {
  if (value === undefined || value === null) return `<div class="stat"><div class="value muted">—</div><div class="label">${esc(label)}</div></div>`;
  const shown = isProbability ? value.toFixed(2) : value;
  return `<div class="stat"><div class="value" style="font-size:20px">${shown}</div><div class="label">${esc(label)}</div></div>`;
}

function renderPostArea() {
  const v = STATE.draft?.current_version;
  const area = $('#post-area');
  if (!area || !v) return;
  area.innerHTML = STATE.editing
    ? `<textarea class="post-edit" id="editor">${esc(v.content)}</textarea>
       <div class="row between" style="margin-top:6px">
         <span class="tiny faint" id="char-count">${v.content.length} characters</span>
         <span class="tiny faint">Your edits are kept — nothing overwrites them unless you regenerate.</span>
       </div>`
    : `<div class="post-body">${esc(v.content)}</div>
       <div class="tiny faint" style="margin-top:6px">${v.char_count} characters</div>`;
  if (STATE.editing) {
    const ed = $('#editor');
    ed.addEventListener('input', () => { $('#char-count').textContent = `${ed.value.length} characters`; });
    ed.focus();
  }
}

function toggleEdit() {
  STATE.editing = !STATE.editing;
  $('#btn-edit').textContent = STATE.editing ? 'Cancel edit' : 'Edit';
  $('#btn-approve').textContent = STATE.editing ? 'Approve edited version' : 'Approve & schedule';
  renderPostArea();
}

function tomorrowAt(hour) {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
}

function setSchedule(iso) {
  STATE.scheduleAt = iso;
  $('#schedule-label').textContent = iso
    ? `Publishing ${fmtRelativeDay(iso)}.`
    : 'Publishing into the next free slot.';
}

async function approve(id) {
  const v = STATE.draft.current_version;
  const edited = STATE.editing ? $('#editor').value : null;
  try {
    busy(true);
    const body = {
      draft_id: id, action: 'APPROVE',
      expected_content_hash: v.content_hash,
      client_action_id: crypto.randomUUID(),
    };
    if (edited !== null && edited !== v.content) body.edited_content = edited;
    if (STATE.scheduleAt) body.scheduled_at = STATE.scheduleAt;
    const res = await api('/api/v1/approvals', { method: 'POST', body: JSON.stringify(body) });
    toast(res.scheduled_at ? `Approved — publishing ${fmtRelativeDay(res.scheduled_at)}.` : res.message);
    go('approvals');
  } catch (e) {
    toast(e.message + (e.recovery ? ` ${e.recovery}` : ''), true);
    if (e.code === 'content_changed') render();
  } finally { busy(false); }
}

async function saveForLater(id) {
  try {
    await api('/api/v1/approvals', {
      method: 'POST',
      body: JSON.stringify({
        draft_id: id, action: 'SAVE_FOR_LATER',
        expected_content_hash: STATE.draft.current_version.content_hash,
        client_action_id: crypto.randomUUID(),
      }),
    });
    toast('Saved for later.');
    go('approvals');
  } catch (e) { toast(e.message, true); }
}

async function selectVersion(draftId, versionId) {
  try {
    busy(true);
    STATE.draft = await api(`/api/v1/drafts/${draftId}/versions/${versionId}/select`, { method: 'POST' });
    render(draftId);
  } catch (e) { toast(e.message, true); } finally { busy(false); }
}

async function rewrite(draftId, operation) {
  try {
    busy(true);
    toast(`Rewriting (${titleCase(operation)})…`);
    STATE.draft = await api(`/api/v1/drafts/${draftId}/rewrite`, {
      method: 'POST', body: JSON.stringify({ operation }),
    });
    render(draftId);
    toast('Rewritten. Re-read it before approving.');
  } catch (e) { toast(e.message, true); } finally { busy(false); }
}

const REJECTION_REASONS = [
  ['TOO_GENERIC', 'Too generic'], ['SOUNDS_AI_GENERATED', 'Sounds AI-generated'],
  ['BAD_HOOK', 'Bad hook'], ['INCORRECT', 'Incorrect'], ['TOO_LONG', 'Too long'],
  ['NOT_INTERESTING', 'Not interesting'], ['TOO_CRINGE', 'Too cringe'],
  ['ALREADY_POSTED_SIMILAR', 'Already posted similar'], ['OTHER', 'Other'],
];

function openRejectDialog(id) {
  showModal(`
    <h3>Why are you rejecting it?</h3>
    <p class="muted small" style="margin-top:-8px">This is the signal the writer learns from, so it is worth a click.</p>
    <div class="row wrap" id="reason-row" style="margin:12px 0">
      ${REJECTION_REASONS.map(([v, l], i) =>
        `<button class="btn sm ${i === 0 ? 'primary' : ''}" data-reason="${v}">${esc(l)}</button>`).join('')}
    </div>
    <textarea class="field" id="reject-note" rows="3" placeholder="Optional note"></textarea>
    <div class="row" style="margin-top:14px;justify-content:flex-end;gap:8px">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn danger" id="confirm-reject">Reject draft</button>
    </div>
  `, (root) => {
    let reason = REJECTION_REASONS[0][0];
    root.querySelectorAll('[data-reason]').forEach(btn => {
      btn.onclick = () => {
        reason = btn.dataset.reason;
        root.querySelectorAll('[data-reason]').forEach(b => b.classList.remove('primary'));
        btn.classList.add('primary');
      };
    });
    $('#confirm-reject', root).onclick = async () => {
      try {
        await api('/api/v1/approvals', {
          method: 'POST',
          body: JSON.stringify({
            draft_id: id, action: 'REJECT',
            expected_content_hash: STATE.draft.current_version.content_hash,
            rejection_reason: reason,
            note: $('#reject-note', root).value || null,
            client_action_id: crypto.randomUUID(),
          }),
        });
        closeModal(); toast('Rejected. The writer will learn from it.'); go('approvals');
      } catch (e) { toast(e.message, true); }
    };
  });
}

function openIdeaDialog() {
  const cats = [['BUILD_LOG', 'Build log'], ['TECHNICAL_LESSON', 'Technical lesson'],
                ['AI_OBSERVATION', 'AI observation'], ['MILESTONE', 'Milestone']];
  showModal(`
    <h3>Write from your own note</h3>
    <p class="muted small" style="margin-top:-8px">Your own notes make the best posts — they are first-hand.</p>
    <div class="stack" style="margin-top:14px">
      <div><label class="field-label">Topic</label>
        <input class="field" id="idea-topic" placeholder="what you worked on"></div>
      <div><label class="field-label">What happened (the specifics)</label>
        <textarea class="field" id="idea-notes" rows="5" placeholder="what broke, what you changed, what surprised you"></textarea></div>
      <div><label class="field-label">Category</label>
        <div class="row wrap" id="cat-row">
          ${cats.map(([v, l], i) => `<button class="btn sm ${i === 0 ? 'primary' : ''}" data-cat="${v}">${esc(l)}</button>`).join('')}
        </div></div>
    </div>
    <div class="row" style="margin-top:16px;justify-content:flex-end;gap:8px">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn primary" id="confirm-idea">Write it</button>
    </div>
  `, (root) => {
    let category = 'BUILD_LOG';
    root.querySelectorAll('[data-cat]').forEach(btn => {
      btn.onclick = () => {
        category = btn.dataset.cat;
        root.querySelectorAll('[data-cat]').forEach(b => b.classList.remove('primary'));
        btn.classList.add('primary');
      };
    });
    $('#confirm-idea', root).onclick = async () => {
      const topic = $('#idea-topic', root).value.trim();
      if (topic.length < 3) return toast('Give it a topic first.', true);
      const btn = $('#confirm-idea', root);
      btn.disabled = true; btn.textContent = 'Writing…';
      try {
        const d = await api('/api/v1/drafts/from-idea', {
          method: 'POST',
          body: JSON.stringify({ topic, notes: $('#idea-notes', root).value, category }),
        });
        closeModal();
        if (d.status === 'READY_FOR_REVIEW') { toast('Draft ready.'); go('draft', d.id); }
        else { toast(`Written, but the quality gate held it back (${STATUS_LABEL[d.status] || d.status}).`, true); go('approvals'); }
      } catch (e) { toast(e.message, true); btn.disabled = false; btn.textContent = 'Write it'; }
    };
  });
}

// -------------------------------------------------------------- calendar ---
async function viewCalendar(view) {
  const entries = STATE.calendar = await api('/api/v1/schedule/calendar');
  const live = entries.filter(e => e.status !== 'REJECTED' && e.status !== 'CANCELLED');

  if (!live.length) {
    view.innerHTML = emptyState('Nothing on the calendar', 'Approved posts appear here with their scheduled time.');
    return;
  }
  view.innerHTML = `
    <table>
      <thead><tr><th>When</th><th>Post</th><th>Format</th><th>Status</th><th></th></tr></thead>
      <tbody>
        ${live.map(e => `
          <tr class="clickable">
            <td onclick="go('draft', ${e.draft_id})" style="white-space:nowrap">
              ${esc(e.published_at ? fmtDateTime(e.published_at) : e.scheduled_at ? fmtRelativeDay(e.scheduled_at) : 'Not scheduled')}
            </td>
            <td onclick="go('draft', ${e.draft_id})" class="truncate" style="max-width:380px">${esc(e.title)}</td>
            <td onclick="go('draft', ${e.draft_id})" class="muted small">${esc(titleCase(e.post_type))}</td>
            <td><span class="pill ${STATUS_CLASS[e.status] || ''}">${esc(STATUS_LABEL[e.status] || e.status)}</span></td>
            <td class="num">
              ${e.slot_id && e.status === 'SCHEDULED' ? `<button class="btn sm" onclick="openReschedule(${e.slot_id}, '${e.scheduled_at}')">Reschedule</button>` : ''}
              ${e.status === 'PUBLISHING' ? `<button class="btn sm primary" onclick="confirmPublished(${e.slot_id})">Mark posted</button>` : ''}
            </td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

function openReschedule(slotId, currentIso) {
  const local = currentIso ? new Date(currentIso.endsWith('Z') ? currentIso : currentIso + 'Z') : new Date();
  const value = new Date(local.getTime() - local.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  showModal(`
    <h3>Reschedule</h3>
    <input class="field" type="datetime-local" id="new-when" value="${value}">
    <div class="row" style="margin-top:16px;justify-content:flex-end;gap:8px">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn primary" id="confirm-when">Move it</button>
    </div>
  `, (root) => {
    $('#confirm-when', root).onclick = async () => {
      const iso = new Date($('#new-when', root).value).toISOString();
      try {
        await api(`/api/v1/schedule/${slotId}/reschedule?scheduled_at=${encodeURIComponent(iso)}`, { method: 'POST' });
        closeModal(); toast(`Moved to ${fmtRelativeDay(iso)}.`); render();
      } catch (e) { toast(e.message, true); }
    };
  });
}

async function confirmPublished(slotId) {
  try {
    await api(`/api/v1/schedule/${slotId}/confirm-published`, { method: 'POST' });
    toast('Recorded as published.'); render();
  } catch (e) { toast(e.message, true); }
}

// --------------------------------------------------------------- network ---
async function viewNetwork(view) {
  const people = STATE.connections = await api('/api/v1/network');

  const header = `
    <div class="banner">
      <strong>You send every invitation yourself.</strong>
      <div class="muted small" style="margin-top:4px">
        Opening a profile copies your note to the clipboard, so connecting is paste-and-click.
        Automating invitations violates LinkedIn's terms and risks your account, so this tool
        will not do it.
        <a href="https://www.linkedin.com/mynetwork/invitation-manager/" target="_blank" rel="noreferrer">Open pending invitations →</a>
      </div>
    </div>`;

  if (!people.length) {
    view.innerHTML = header + emptyState('No suggestions yet',
      'People worth knowing appear here with a reason and a draft note, pulled from the sources you already follow.');
    return;
  }

  view.innerHTML = header + `
    <div class="row between" style="margin-bottom:10px">
      <span class="muted small">${people.length} to review · <span class="kbd">J</span>/<span class="kbd">K</span> move, <span class="kbd">O</span> open + copy note, <span class="kbd">S</span> skip</span>
    </div>
    <div id="queue">${people.map((p, i) => personCard(p, i)).join('')}</div>`;
  focusQueue(0);
}

function personCard(p, i) {
  return `
    <div class="card queue-card" id="person-${i}" data-index="${i}" style="margin-bottom:10px">
      <div class="row between">
        <div>
          <div style="font-weight:600;font-size:15px">${esc(p.name)}</div>
          <div class="muted small">${esc([p.role, p.company].filter(Boolean).join(' · '))}</div>
        </div>
        <span class="pill ${p.relevance_score >= 0.7 ? 'accent' : ''}">${Math.round(p.relevance_score * 100)}% match</span>
      </div>
      <div class="small" style="margin-top:10px">${esc(p.reason_for_recommendation)}</div>
      ${p.suggested_note ? `
        <div class="section-title" style="margin:14px 0 6px">Your note</div>
        <div class="card" style="background:var(--surface-2);padding:12px">${esc(p.suggested_note)}</div>` : ''}
      <div class="row" style="margin-top:12px;gap:8px">
        <button class="btn primary sm" onclick="openProfile(${i})">Open profile &amp; copy note</button>
        <button class="btn sm" onclick="markConnected(${p.id})">I connected</button>
        <button class="btn ghost sm" onclick="skipPerson(${p.id})">Skip</button>
      </div>
    </div>`;
}

function focusQueue(index) {
  const cards = document.querySelectorAll('.queue-card');
  if (!cards.length) return;
  STATE.queueIndex = Math.max(0, Math.min(cards.length - 1, index));
  cards.forEach(c => c.classList.remove('focused'));
  const card = cards[STATE.queueIndex];
  card.classList.add('focused');
  card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

async function openProfile(index) {
  const p = STATE.connections[index];
  if (!p) return;
  if (p.suggested_note) {
    try { await navigator.clipboard.writeText(p.suggested_note); toast('Note copied — paste it into the invite.'); }
    catch { toast('Opened. (Clipboard blocked — copy the note manually.)', true); }
  }
  window.open(p.profile_url, '_blank', 'noreferrer');
  api(`/api/v1/network/${p.id}/status`, { method: 'POST', body: JSON.stringify({ status: 'OPENED' }) }).catch(() => {});
}

async function markConnected(id) {
  await api(`/api/v1/network/${id}/status`, { method: 'POST', body: JSON.stringify({ status: 'MARKED_CONNECTED' }) });
  toast('Nice. Recorded.'); render();
}
async function skipPerson(id) {
  await api(`/api/v1/network/${id}/status`, { method: 'POST', body: JSON.stringify({ status: 'SKIPPED' }) });
  render();
}

// ------------------------------------------------------------- analytics ---
async function viewAnalytics(view) {
  const a = STATE.analytics = await api('/api/v1/analytics/overview');

  if (!a.published_count) {
    view.innerHTML = emptyState('No analytics yet', a.empty_state || 'Publish your first post to begin learning what works.');
    return;
  }

  view.innerHTML = `
    <div class="grid cols-3">
      ${statCard('Published', a.published_count)}
      ${statCard('With metrics', a.posts_with_metrics)}
      <div class="card stat"><div class="value ${a.best_format ? '' : 'muted'}" style="font-size:18px;padding-top:6px">
        ${a.best_format ? esc(titleCase(a.best_format)) : '—'}</div><div class="label">Best format</div></div>
    </div>

    ${a.empty_state ? `<div class="banner" style="margin-top:14px">${esc(a.empty_state)}</div>` : ''}

    ${a.insights.length ? `
      <div class="section-title">What the data suggests</div>
      ${a.insights.map(i => `
        <div class="card">
          <div>${esc(i.statement)}</div>
          <div class="row" style="margin-top:8px;gap:8px">
            <span class="pill ${i.confidence === 'STRONG_SIGNAL' ? 'accent' : i.confidence === 'MODERATE_CONFIDENCE' ? 'info' : ''}">
              ${esc(i.confidence.replace(/_/g, ' ').toLowerCase())}
            </span>
            <span class="tiny faint">n = ${i.sample_size}</span>
          </div>
        </div>`).join('')}` : ''}

    <div class="section-title">Published posts</div>
    <table>
      <thead><tr><th>Post</th><th>Format</th><th>When</th>
        <th class="num">Views</th><th class="num">Reactions</th><th class="num">Comments</th><th></th></tr></thead>
      <tbody>
        ${a.posts.map(p => `
          <tr>
            <td class="truncate" style="max-width:280px">${esc(p.title)}</td>
            <td class="muted small">${esc(titleCase(p.post_type))}</td>
            <td class="muted small" style="white-space:nowrap">${esc(fmtDateTime(p.published_at))}</td>
            <td class="num ${p.impressions === null ? 'faint' : ''}">${num(p.impressions)}</td>
            <td class="num ${p.reactions === null ? 'faint' : ''}">${num(p.reactions)}</td>
            <td class="num ${p.comments === null ? 'faint' : ''}">${num(p.comments)}</td>
            <td class="num"><button class="btn sm" onclick="openMetrics(${p.published_post_id})">${p.has_data ? 'Update' : 'Add'}</button></td>
          </tr>`).join('')}
      </tbody>
    </table>
    <div class="tiny faint" style="margin-top:10px">
      LinkedIn does not expose post analytics to ordinary integrations, so these are the numbers you enter.
      Anything left blank stays blank rather than counting as zero.
    </div>`;
}

function openMetrics(postId) {
  showModal(`
    <h3>Numbers from LinkedIn</h3>
    <p class="muted small" style="margin-top:-8px">Leave anything you don't have blank.</p>
    <div class="grid cols-3" style="margin-top:14px">
      <div><label class="field-label">Views</label><input class="field" id="m-impressions" type="number" min="0"></div>
      <div><label class="field-label">Reactions</label><input class="field" id="m-reactions" type="number" min="0"></div>
      <div><label class="field-label">Comments</label><input class="field" id="m-comments" type="number" min="0"></div>
      <div><label class="field-label">Reposts</label><input class="field" id="m-reposts" type="number" min="0"></div>
      <div><label class="field-label">Profile visits</label><input class="field" id="m-profile_visits" type="number" min="0"></div>
      <div><label class="field-label">Followers gained</label><input class="field" id="m-followers_gained" type="number" min="0"></div>
    </div>
    <div class="row" style="margin-top:16px;justify-content:flex-end;gap:8px">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn primary" id="save-metrics">Save</button>
    </div>
  `, (root) => {
    $('#save-metrics', root).onclick = async () => {
      const body = {};
      for (const key of ['impressions', 'reactions', 'comments', 'reposts', 'profile_visits', 'followers_gained']) {
        const raw = $(`#m-${key}`, root).value;
        if (raw !== '') body[key] = Number(raw);
      }
      try {
        await api(`/api/v1/analytics/posts/${postId}/metrics`, { method: 'POST', body: JSON.stringify(body) });
        closeModal(); toast('Saved. The learning engine has been updated.'); render();
      } catch (e) { toast(e.message, true); }
    };
  });
}

// --------------------------------------------------------------- profile ---
async function viewProfile(view) {
  const p = await api('/api/v1/profile');
  view.innerHTML = `
    <div class="banner">Positioning guidance, derived from what you actually publish. Nothing here is posted for you.</div>
    <div class="grid cols-3">
      ${statCard('Posts analysed', p.posts_analysed)}
      <div class="card stat"><div class="value" style="font-size:18px;padding-top:6px">${esc(p.dominant_theme ? titleCase(p.dominant_theme) : '—')}</div><div class="label">Dominant theme</div></div>
      <div class="card stat"><div class="value" style="font-size:18px;padding-top:6px">${esc(p.cadence || '—')}</div><div class="label">Cadence</div></div>
    </div>

    <div class="section-title">Suggested headline</div>
    <div class="card">
      <div style="font-size:15px">${esc(p.suggested_headline)}</div>
      <button class="btn sm" style="margin-top:10px" onclick="copyText(${JSON.stringify(p.suggested_headline).replace(/"/g, '&quot;')})">Copy</button>
    </div>

    <div class="section-title">Suggested "About"</div>
    <div class="card"><div class="post-body" style="background:var(--surface-2)">${esc(p.suggested_about)}</div>
      <button class="btn sm" style="margin-top:10px" onclick="copyText(${JSON.stringify(p.suggested_about).replace(/"/g, '&quot;')})">Copy</button>
    </div>

    ${p.recommendations.length ? `
      <div class="section-title">To do</div>
      ${p.recommendations.map(r => `<div class="card small">• ${esc(r)}</div>`).join('')}` : ''}
  `;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied.'); }
  catch { toast('Could not copy.', true); }
}

// -------------------------------------------------------------- settings ---
async function viewSettings(view) {
  const s = STATE.settings = await api('/api/v1/settings');
  const v = s.values;
  const slots = (v.posting_slots || []).map(x => `${x.weekday} ${x.time}`).join(', ');

  view.innerHTML = `
    <div class="section-title">Posting</div>
    <div class="card stack">
      <div><label class="field-label">Posting slots (e.g. MON 10:00, WED 14:00)</label>
        <input class="field" id="s-slots" value="${esc(slots)}"></div>
      <div class="grid cols-2">
        <div><label class="field-label">Timezone</label><input class="field" id="s-tz" value="${esc(v.timezone)}"></div>
        <div><label class="field-label">Min hours between posts</label><input class="field" id="s-gap" type="number" value="${v.min_hours_between_posts}"></div>
      </div>
    </div>

    <div class="section-title">Quality</div>
    <div class="card grid cols-2">
      <div><label class="field-label">Quality threshold (0–100)</label><input class="field" id="s-quality" type="number" value="${v.quality_threshold}"></div>
      <div><label class="field-label">Idea score threshold (0–1)</label><input class="field" id="s-idea" type="number" step="0.05" value="${v.idea_score_threshold}"></div>
    </div>

    <div class="section-title">Spend</div>
    <div class="card grid cols-2">
      <div><label class="field-label">Daily limit (USD)</label><input class="field" id="s-daily" type="number" step="0.5" value="${v.llm_daily_cost_limit_usd}"></div>
      <div><label class="field-label">Monthly limit (USD)</label><input class="field" id="s-monthly" type="number" step="1" value="${v.llm_monthly_cost_limit_usd}"></div>
    </div>

    <div class="row" style="margin-top:18px;gap:10px">
      <button class="btn primary" id="save-settings">Save settings</button>
      <button class="btn" onclick="runJob('discover_topics')">Look for ideas now</button>
      <button class="btn" onclick="runJob('generate_learning_report')">Recompute insights</button>
    </div>
  `;

  $('#save-settings').onclick = async () => {
    const slotText = $('#s-slots').value;
    const parsed = slotText.split(',').map(chunk => {
      const m = chunk.trim().match(/^([A-Za-z]{3})\s+(\d{1,2}:\d{2})$/);
      return m ? { weekday: m[1].toUpperCase(), time: m[2] } : null;
    }).filter(Boolean);
    const values = {
      timezone: $('#s-tz').value.trim(),
      min_hours_between_posts: Number($('#s-gap').value),
      quality_threshold: Number($('#s-quality').value),
      idea_score_threshold: Number($('#s-idea').value),
      llm_daily_cost_limit_usd: Number($('#s-daily').value),
      llm_monthly_cost_limit_usd: Number($('#s-monthly').value),
    };
    if (parsed.length) values.posting_slots = parsed;
    try {
      await api('/api/v1/settings', { method: 'PUT', body: JSON.stringify({ values }) });
      toast('Settings saved.');
    } catch (e) { toast(e.message, true); }
  };
}

async function runJob(type) {
  try { await api(`/api/v1/system/run/${type}`, { method: 'POST' }); toast('Started. Give it a moment.'); }
  catch (e) { toast(e.message, true); }
}

// ----------------------------------------------------------------- misc ----
function emptyState(title, body, actionHtml = '') {
  return `<div class="empty"><h3>${esc(title)}</h3><p>${esc(body)}</p>${actionHtml ? `<div style="margin-top:16px">${actionHtml}</div>` : ''}</div>`;
}

function showModal(html, onMount) {
  const backdrop = el(`<div class="modal-backdrop"><div class="modal">${html}</div></div>`);
  backdrop.onclick = (e) => { if (e.target === backdrop) closeModal(); };
  $('#modal-root').appendChild(backdrop);
  if (onMount) onMount(backdrop);
}
function closeModal() { $('#modal-root').innerHTML = ''; }

function speak() {
  const text = STATE.briefing?.speech;
  if (!text) return toast('Nothing to read yet.');
  if (!window.speechSynthesis) return toast('This browser cannot speak.', true);
  speechSynthesis.cancel();
  speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

document.addEventListener('keydown', (e) => {
  if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
  if (STATE.route === 'network') {
    if (e.key === 'j') { focusQueue(STATE.queueIndex + 1); e.preventDefault(); }
    if (e.key === 'k') { focusQueue(STATE.queueIndex - 1); e.preventDefault(); }
    if (e.key === 'o') { openProfile(STATE.queueIndex); e.preventDefault(); }
    if (e.key === 's') {
      const p = STATE.connections[STATE.queueIndex];
      if (p) skipPerson(p.id);
      e.preventDefault();
    }
  }
  if (e.key === 'Escape') closeModal();
  if (e.key === 'r' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); render(); }
});

// expose handlers used from inline onclick
Object.assign(window, {
  go, approve, saveForLater, selectVersion, rewrite, toggleEdit, setSchedule, tomorrowAt,
  openRejectDialog, openIdeaDialog, openReschedule, confirmPublished, openMetrics,
  openProfile, markConnected, skipPerson, closeModal, runJob, copyText,
});

// ----------------------------------------------------------------- boot ----
(async function boot() {
  $('#btn-refresh').onclick = () => render();
  $('#btn-speak').onclick = speak;
  try {
    await connect();
    const params = new URLSearchParams(location.search);
    go(params.get('view') || 'dashboard');
  } catch (e) {
    setConnected(false);
    $('#view').innerHTML = `<div class="banner bad"><strong>Could not start a session.</strong>
      <div class="muted small" style="margin-top:4px">${esc(e.message)}</div>
      <div class="muted small" style="margin-top:6px">The console must be opened from the machine running the backend.</div></div>`;
  }
})();
