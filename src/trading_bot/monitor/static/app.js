/* Trading Decision Monitor — read-only UI.
 *
 * Rules this file obeys:
 *  - every server string is rendered with textContent (never innerHTML);
 *  - no colour is the only carrier of meaning: every state carries icon + text;
 *  - a state the runtime did not persist is displayed as NOT_RECORDED;
 *  - nothing here can mutate trading state: the only verbs are GET requests.
 */
(() => {
  'use strict';

  const LWC = window.LightweightCharts;

  //: Above this many visible marker buckets, labels are dropped (markers stay).
  const MARKER_LABEL_LIMIT = 80;

  const state = {
    runId: null,
    runs: [],
    assets: null,
    decisions: [],
    counters: {},
    lastStep: null,
    notRecorded: [],
    candles: [],
    candleError: null,
    filters: { symbol: '', timeframe: '5m', strategy: '', status: '' },
    replay: { on: false, index: 0, times: [], timer: null, clock: null },
    cursor: 0,
    eventSource: null,
    chart: null,
    candleSeries: null,
    volumeSeries: null,
    markers: null,
    groupByTime: new Map(),
    selected: null,
  };

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- api ----

  async function api(path) {
    const response = await fetch(path, { headers: { Accept: 'application/json' } });
    let body = null;
    try {
      body = await response.json();
    } catch (err) {
      body = null;
    }
    if (!response.ok) {
      const detail = body && body.error ? body.error : { code: 'HTTP_' + response.status, message: '' };
      const error = new Error(detail.message || detail.code);
      error.code = detail.code;
      throw error;
    }
    return body;
  }

  function notice(message, isError) {
    const el = $('notice');
    if (!message) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.classList.toggle('error', Boolean(isError));
    el.textContent = message;
  }

  // ------------------------------------------------------------ helpers ----

  const STATUS_TONE = {
    NO_TRADE: 'bad',
    SHADOW_OBSERVED: 'warn',
    ACCEPTED_NOT_EXECUTED: 'good',
    EXECUTED_PAPER: 'info-strong',
    EXECUTION_FAILED: 'bad',
    UNDECIDED: 'system',
    SIGNAL_ONLY: 'neutral',
  };

  const STATUS_ICON = {
    NO_TRADE: '✕',
    SHADOW_OBSERVED: '◐',
    ACCEPTED_NOT_EXECUTED: '✓',
    EXECUTED_PAPER: '●',
    EXECUTION_FAILED: '⊘',
    UNDECIDED: '⚠',
    SIGNAL_ONLY: '◆',
  };

  const PRIORITY = { EXECUTED_PAPER: 6, EXECUTION_FAILED: 5, ACCEPTED_NOT_EXECUTED: 4, NO_TRADE: 3, SHADOW_OBSERVED: 2, UNDECIDED: 1, SIGNAL_ONLY: 0 };

  function fmtUtc(iso) {
    if (!iso) return '—';
    return iso.replace('T', ' ').replace('Z', '');
  }

  function fmtMs(value) {
    if (value === null || value === undefined) return 'NOT_RECORDED';
    if (value < 1000) return value + ' ms';
    if (value < 60000) return (value / 1000).toFixed(1) + ' s';
    if (value < 3600000) return Math.round(value / 60000) + ' min';
    return (value / 3600000).toFixed(1) + ' h';
  }

  function num(value) {
    if (value === null || value === undefined) return '—';
    if (typeof value !== 'number') return String(value);
    return Math.abs(value) >= 1000 ? value.toLocaleString('es-ES', { maximumFractionDigits: 2 }) : String(Math.round(value * 10000) / 10000);
  }

  function el(tag, opts) {
    const node = document.createElement(tag);
    if (!opts) return node;
    if (opts.class) node.className = opts.class;
    if (opts.text !== undefined) node.textContent = String(opts.text);
    if (opts.title) node.title = opts.title;
    if (opts.attrs) {
      for (const [key, value] of Object.entries(opts.attrs)) {
        if (value !== null && value !== undefined) node.setAttribute(key, String(value));
      }
    }
    return node;
  }

  function stateBadge(status, label) {
    const wrap = el('span', { class: 'state tone-' + (STATUS_TONE[status] || 'neutral') });
    wrap.appendChild(el('span', { class: 'icon', text: STATUS_ICON[status] || '•', attrs: { 'aria-hidden': 'true' } }));
    wrap.appendChild(el('span', { text: label || status }));
    return wrap;
  }

  // --------------------------------------------------------- chart setup ----

  function initChart() {
    if (!LWC) {
      notice('No se pudo cargar la librería de gráficos. El timeline sigue operativo.', true);
      return;
    }
    const container = $('chart');
    state.chart = LWC.createChart(container, {
      layout: { background: { color: '#111827' }, textColor: '#96a6c0', attributionLogo: false },
      grid: { vertLines: { color: '#1a2436' }, horzLines: { color: '#1a2436' } },
      rightPriceScale: { borderColor: '#1f2a3d' },
      timeScale: { borderColor: '#1f2a3d', timeVisible: true, secondsVisible: false },
      crosshair: { mode: LWC.CrosshairMode.Normal },
      autoSize: true,
    });
    state.candleSeries = state.chart.addSeries(LWC.CandlestickSeries, {
      upColor: '#2ea043',
      downColor: '#e5534b',
      borderVisible: false,
      wickUpColor: '#2ea043',
      wickDownColor: '#e5534b',
    });
    state.volumeSeries = state.chart.addSeries(LWC.HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      color: '#2b3a52',
    });
    state.chart.priceScale('').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    state.markers = LWC.createSeriesMarkers(state.candleSeries, []);

    state.chart.subscribeClick((param) => {
      if (!param || param.time === undefined || param.time === null) return;
      const group = state.groupByTime.get(Number(param.time));
      if (!group || !group.length) return;
      if (group.length === 1) {
        openDecision(group[0].decision_id);
      } else {
        openDecisionList(Number(param.time), group);
      }
    });

    window.addEventListener('resize', () => {
      if (state.chart) state.chart.applyOptions({ width: container.clientWidth });
    });
  }

  function normalizeTime(ms) {
    return Math.floor(ms / 1000);
  }

  function candleTimeFor(decisionMs, barSeconds) {
    const width = barSeconds * 1000;
    return Math.floor(Math.floor(decisionMs / width) * width / 1000);
  }

  function visibleDecisions() {
    if (!state.replay.on || state.replay.clock === null) return state.decisions;
    return state.decisions.filter((d) => d.decision_time_ms <= state.replay.clock);
  }

  function visibleCandles() {
    if (!state.replay.on || state.replay.clock === null) return state.candles;
    return state.candles.filter((b) => b.bar_close_time_ms <= state.replay.clock);
  }

  function renderChart() {
    if (!state.chart) return;
    const bars = visibleCandles();
    const seconds = timeframeSeconds(state.filters.timeframe);

    state.candleSeries.setData(
      bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }))
    );
    state.volumeSeries.setData(
      bars.map((b) => ({
        time: b.time,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(46,160,67,.35)' : 'rgba(229,83,75,.35)',
      }))
    );

    const marks = [];
    const groupByTime = new Map();
    if (bars.length) {
      const first = bars[0].time;
      const last = bars[bars.length - 1].time;
      for (const decision of visibleDecisions()) {
        // the chart plots one symbol; another asset's marker would be a lie
        if (decision.symbol !== chartSymbol()) continue;
        const snapped = candleTimeFor(decision.decision_time_ms, seconds);
        if (snapped < first || snapped > last) continue;
        if (!groupByTime.has(snapped)) groupByTime.set(snapped, []);
        groupByTime.get(snapped).push(decision);
      }
      // With thousands of decisions the labels overlap into an unreadable block
      // (found on a 2 232-decision replay). Markers stay; the text label is only
      // drawn when the visible bar window is sparse enough to read it.
      const labelBudget = groupByTime.size <= MARKER_LABEL_LIMIT;
      for (const [time, group] of groupByTime) {
        const top = group.slice().sort((a, b) => (PRIORITY[b.status] || 0) - (PRIORITY[a.status] || 0))[0];
        const extra = group.length > 1 ? ' +' + (group.length - 1) : '';
        const direction = String(top.signal_direction || '').toUpperCase();
        let shape = 'circle';
        let position = 'aboveBar';
        let color = '#8b98ad';
        if (top.status === 'NO_TRADE') {
          shape = direction === 'SHORT' ? 'arrowDown' : 'arrowUp';
          color = '#e5534b';
        } else if (top.status === 'SHADOW_OBSERVED') {
          shape = 'square';
          color = '#d29922';
          position = 'belowBar';
        } else if (top.status === 'ACCEPTED_NOT_EXECUTED') {
          color = '#2ea043';
          shape = 'circle';
        } else if (top.status === 'EXECUTED_PAPER') {
          color = '#6ea8ff';
          position = 'belowBar';
        } else if (top.status === 'EXECUTION_FAILED' || top.status === 'UNDECIDED') {
          shape = 'square';
          color = '#e5534b';
        }
        marks.push({
          time,
          position,
          color,
          shape,
          text: labelBudget ? (top.status_label || top.status) + extra : '',
          size: top.status === 'EXECUTED_PAPER' ? 2 : 1,
        });
      }
    }
    state.groupByTime = groupByTime;
    state.markers.setMarkers(marks);
    if (bars.length) state.chart.timeScale().fitContent();
  }

  function timeframeSeconds(tf) {
    const map = { '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '2h': 7200, '4h': 14400, '1d': 86400 };
    return map[tf] || 300;
  }

  // ---------------------------------------------------------- connection ----

  function renderConnection(payload) {
    if (!payload) return;
    const stateName = payload.connection_state || 'DISCONNECTED';
    const badge = $('connBadge');
    badge.className = 'badge';
    const map = {
      LIVE_DATA: ['badge-live', '●', 'LIVE (PAPER)'],
      DELAYED: ['badge-delayed', '⏱', 'DELAYED'],
      DISCONNECTED: ['badge-disconnected', '✕', 'DESCONECTADO'],
      REPLAY: ['badge-replay', '↺', 'REPLAY'],
      SIMULATED_FIXTURE: ['badge-fixture', '⚗', 'FIXTURE (no live)'],
    };
    const [cls, icon, text] = map[stateName] || ['badge-unknown', '?', stateName];
    badge.classList.add(cls);
    $('connIcon').textContent = icon;
    $('connText').textContent = text;
    badge.title = payload.connection_reason || text;
    $('ageBadge').textContent = 'edad de datos: ' + fmtMs(payload.data_age_ms || 0);
  }

  function setMode(mode) {
    const badge = $('modeBadge');
    badge.textContent = (mode || 'PAPER').toUpperCase();
    badge.className = 'badge badge-mode';
  }

  // --------------------------------------------------------------- funnel ----

  const FUNNEL = [
    ['candles_received', 'Velas recibidas'],
    ['strategies_distinct', 'Estrategias evaluadas'],
    ['signals', 'Señales'],
    ['proposals', 'Propuestas'],
    ['no_trade', 'Rechazadas (NO_TRADE)'],
    ['shadow', 'Shadow (no ejecutadas)'],
    ['accepted_not_executed', 'Aceptadas'],
    ['order_submitted', 'Órdenes enviadas'],
    ['fills', 'Fills PAPER'],
  ];

  function renderFunnel() {
    const grid = $('funnelGrid');
    grid.textContent = '';
    for (const [key, label] of FUNNEL) {
      const value = state.counters[key];
      const card = el('div', { class: 'funnel-card' });
      card.appendChild(el('div', { class: 'k', text: label }));
      if (value === null || value === undefined) {
        card.appendChild(el('div', { class: 'v na', text: 'NOT_RECORDED' }));
      } else {
        card.appendChild(el('div', { class: 'v', text: value }));
      }
      grid.appendChild(card);
    }
    const detail = state.counters.strategy_evaluations
      ? ` · ${state.counters.strategy_evaluations} evaluaciones estrategia/activo`
      : '';
    $('lastStep').textContent = state.lastStep
      ? `Último paso observable: ${state.lastStep.text}${detail}`
      : 'Sin eventos: el runtime no ha persistido ninguna decisión para este run.' + detail;
  }

  // ------------------------------------------------------------- timeline ----

  function renderTimeline() {
    const body = $('timelineBody');
    body.textContent = '';
    const rows = visibleDecisions();
    $('timelineEmpty').hidden = rows.length > 0;

    for (const decision of rows) {
      const tr = el('tr', { attrs: { tabindex: '0', role: 'button', 'aria-label': 'Abrir detalle de ' + decision.decision_id } });
      tr.appendChild(el('td', { text: fmtUtc(decision.decision_time) }));

      const statusCell = el('td');
      statusCell.appendChild(stateBadge(decision.status, decision.status_label));
      tr.appendChild(statusCell);

      const reasonCell = el('td', { class: 'reason' });
      reasonCell.appendChild(el('div', { text: decision.reason_summary }));
      reasonCell.appendChild(el('small', { text: (decision.reason_codes || []).join(' · ') }));
      tr.appendChild(reasonCell);

      tr.appendChild(el('td', { text: decision.strategy_id || '—' }));
      tr.appendChild(el('td', { text: riskText(decision) }));
      tr.appendChild(el('td', { text: decision.price_observed === null || decision.price_observed === undefined ? '—' : num(decision.price_observed) }));
      tr.appendChild(el('td', { text: '›' }));

      tr.addEventListener('click', () => openDecision(decision.decision_id));
      tr.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openDecision(decision.decision_id);
        }
      });
      if (decision.decision_id === state.selected) tr.classList.add('current');
      if (state.replay.on && state.replay.clock !== null && decision.decision_time_ms > state.replay.clock) {
        tr.style.opacity = '0.35';
      }
      body.appendChild(tr);
    }
  }

  function riskText(decision) {
    const gate = decision.risk_gate;
    if (!gate || gate === 'NOT_APPLICABLE') return 'n/a';
    if (gate === 'NOT_EVALUATED') return 'no evaluado';
    if (gate === 'VETO') return 'VETO';
    if (gate === 'ADVISORY_PASS') return 'PASS (advisory)';
    return gate;
  }

  // -------------------------------------------------------------- drawer ----

  function openDecisionList(timeMs, group) {
    const body = $('drawerBody');
    $('drawerTitle').textContent = 'Decisiones en la misma vela';
    body.textContent = '';
    const intro = el('p', { class: 'muted', text: `${group.length} eventos comparten la vela ${fmtUtc(new Date(timeMs * 1000).toISOString())}. Elige uno:` });
    body.appendChild(intro);
    for (const item of group.slice().sort((a, b) => a.decision_time_ms - b.decision_time_ms)) {
      const button = el('button', { text: `${item.decision_id} · ${item.status_label} · ${item.reason_summary}`, attrs: { type: 'button' } });
      button.style.display = 'block';
      button.style.width = '100%';
      button.style.marginBottom = '6px';
      button.addEventListener('click', () => openDecision(item.decision_id));
      body.appendChild(button);
    }
    $('drawer').hidden = false;
  }

  async function openDecision(decisionId) {
    state.selected = decisionId;
    renderTimeline();
    const drawer = $('drawer');
    const body = $('drawerBody');
    drawer.hidden = false;
    $('drawerTitle').textContent = decisionId;
    body.textContent = '';
    body.appendChild(el('p', { class: 'muted', text: 'Cargando DecisionTrace…' }));

    let detail;
    try {
      detail = await api('/api/monitor/decisions/' + encodeURIComponent(decisionId) + '?run_id=' + encodeURIComponent(state.runId));
    } catch (error) {
      body.textContent = '';
      body.appendChild(el('p', { class: 'fail', text: 'No se pudo cargar el detalle: ' + error.message }));
      return;
    }
    body.textContent = '';
    const trace = detail.trace && detail.trace.recorded ? detail.trace.trace : null;
    const replay = detail.trace && detail.trace.recorded ? detail.trace.replay : null;

    // 1 — what happened
    const section1 = el('section');
    section1.appendChild(el('h3', { text: 'Qué ocurrió' }));
    section1.appendChild(
      el('p', {
        text:
          (detail.status_label || detail.terminal_status) +
          ' · ' +
          (trace ? trace.symbol : '—') +
          ' · ' +
          (trace ? trace.mode : '—'),
      })
    );
    const list = el('ol');
    for (const event of detail.events) {
      const li = el('li');
      li.appendChild(stateBadge(event.decision_status, event.decision_status_label));
      li.appendChild(el('span', { text: '  ' + event.event_label + ' — ' + event.reason_summary }));
      list.appendChild(li);
    }
    section1.appendChild(list);
    body.appendChild(section1);

    // 2 — why
    const section2 = el('section');
    section2.appendChild(el('h3', { text: 'Por qué (motivos verificables)' }));
    const table = el('table');
    const head = el('thead');
    const headRow = el('tr');
    for (const label of ['Código', 'Motivo', 'Medido / umbral', 'Componente', 'Sev.', 'Evidencia']) {
      headRow.appendChild(el('th', { text: label }));
    }
    head.appendChild(headRow);
    table.appendChild(head);
    const tbody = el('tbody');
    const allEvents = detail.events || [];
    const seen = new Set();
    for (const event of allEvents) {
      for (const reason of event.reason_codes || []) {
        const key = reason.reason_code + '|' + reason.measured_value + '|' + reason.threshold;
        if (seen.has(key)) continue;
        seen.add(key);
        const tr = el('tr');
        tr.appendChild(el('td', { text: reason.reason_code }));
        tr.appendChild(el('td', { text: reason.short_text }));
        const measured = reason.measured_value === null || reason.measured_value === undefined
          ? 'no registrado'
          : `${num(reason.measured_value)}${reason.unit ? ' ' + reason.unit : ''}` +
            (reason.threshold === null || reason.threshold === undefined ? '' : ` / ${num(reason.threshold)}${reason.unit ? ' ' + reason.unit : ''}`);
        tr.appendChild(el('td', { text: measured }));
        tr.appendChild(el('td', { text: reason.component }));
        tr.appendChild(el('td', { text: reason.severity }));
        tr.appendChild(el('td', { text: reason.evidence_ref || '—' }));
        tbody.appendChild(tr);
      }
    }
    if (!tbody.children.length) {
      const tr = el('tr');
      tr.appendChild(el('td', { text: 'REASON_UNAVAILABLE', attrs: { colspan: '6' } }));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    section2.appendChild(table);
    section2.appendChild(el('p', { class: 'muted', text: 'Texto determinista derivado de reason_codes; no hay explicación generada por LLM.' }));
    body.appendChild(section2);

    // 3 — verification
    const section3 = el('section');
    section3.appendChild(el('h3', { text: 'Verificación independiente' }));
    if (trace && trace.verification) {
      const checks = (trace.verification.checks || []);
      section3.appendChild(el('p', { text: 'Veredicto: ' + (trace.verification.verdict || 'NOT_RUN') }));
      const ul = el('ul', { class: 'checks' });
      for (const check of checks) {
        const li = el('li');
        li.appendChild(el('span', { class: check.passed ? 'pass' : 'fail', text: check.passed ? '✓' : '✕' }));
        li.appendChild(el('span', { text: `${check.name} — ${check.detail || ''}` }));
        ul.appendChild(li);
      }
      if (!checks.length) ul.appendChild(el('li', { text: 'Sin checks registrados.' }));
      section3.appendChild(ul);
    } else {
      section3.appendChild(el('p', { class: 'muted', text: 'NOT_RECORDED' }));
    }
    body.appendChild(section3);

    // 4 — risk
    const section4 = el('section');
    section4.appendChild(el('h3', { text: 'Riesgo determinista' }));
    if (trace && trace.risk) {
      const risk = trace.risk;
      const dl = el('dl', { class: 'kv' });
      addKv(dl, 'Veredicto', risk.verdict || '—');
      addKv(dl, 'Regla', risk.risk_rule || risk.rule || '—');
      addKv(dl, 'Motivo', risk.risk_reason || risk.reason || '—');
      addKv(dl, 'Advisory', risk.advisory ? 'sí (no autoriza ni bloquea)' : 'no (vinculante)');
      addKv(dl, 'Evaluado', risk.risk_evaluated ? 'sí' : 'no');
      addKv(dl, 'Notional', risk.notional_usdt === null || risk.notional_usdt === undefined ? '—' : num(risk.notional_usdt) + ' USDT');
      section4.appendChild(dl);
    } else {
      section4.appendChild(el('p', { class: 'muted', text: 'NOT_RECORDED' }));
    }
    body.appendChild(section4);

    // 5 — proposal
    const section5 = el('section');
    section5.appendChild(el('h3', { text: 'Propuesta' }));
    if (trace && trace.proposal) {
      const p = trace.proposal;
      const dl = el('dl', { class: 'kv' });
      addKv(dl, 'Estrategia', p.strategy_id);
      addKv(dl, 'Dirección', p.direction);
      addKv(dl, 'Entrada (referencia)', num(p.entry_reference));
      addKv(dl, 'Borde bruto', num(p.expected_gross_edge_bps) + ' bps');
      addKv(dl, 'Coste estimado', num(p.expected_cost_bps) + ' bps');
      addKv(dl, 'Borde neto', num(p.expected_net_edge_bps) + ' bps');
      addKv(dl, 'Admisión', trace.proposal.admission_status || '—');
      addKv(dl, 'Confianza', p.confidence === null || p.confidence === undefined ? '—' : num(p.confidence));
      section5.appendChild(dl);
      section5.appendChild(el('p', { class: 'muted', text: 'La confianza no es una probabilidad de beneficio.' }));
    } else {
      section5.appendChild(el('p', { class: 'muted', text: 'Sin propuesta registrada para esta decisión.' }));
    }
    body.appendChild(section5);

    // 6 — replay
    const section6 = el('section');
    section6.appendChild(el('h3', { text: 'Replay (solo desde la traza persistida)' }));
    if (replay && replay.ok !== undefined) {
      section6.appendChild(el('p', { text: `Estado: ${replay.status || '—'} · ok: ${replay.ok ? 'sí' : 'no'} · acceso a datos de mercado: no` }));
      const ul = el('ul', { class: 'checks' });
      for (const check of replay.checks || []) {
        const li = el('li');
        li.appendChild(el('span', { class: check.passed ? 'pass' : 'fail', text: check.passed ? '✓' : '✕' }));
        li.appendChild(el('span', { text: `${check.name} — ${check.detail || ''}` }));
        ul.appendChild(li);
      }
      section6.appendChild(ul);
    } else {
      section6.appendChild(el('p', { class: 'muted', text: 'Replay no disponible: ' + (replay && replay.error ? replay.error : 'NOT_RECORDED') }));
    }
    body.appendChild(section6);

    // 7 — not recorded
    const section7 = el('section');
    section7.appendChild(el('h3', { text: 'No registrado por el runtime' }));
    const ul7 = el('ul', { class: 'checks' });
    for (const item of detail.not_recorded || []) {
      const li = el('li');
      li.appendChild(el('span', { class: 'fail', text: '·' }));
      li.appendChild(el('span', { text: `${item.field}: ${item.status} — ${item.reason}` }));
      ul7.appendChild(li);
    }
    section7.appendChild(ul7);
    body.appendChild(section7);

    if (trace) {
      const details = el('details');
      details.appendChild(el('summary', { text: 'Traza completa (JSON)' }));
      details.appendChild(el('pre', { text: JSON.stringify(trace, null, 2) }));
      body.appendChild(details);
    }
  }

  function addKv(dl, key, value) {
    dl.appendChild(el('dt', { text: key }));
    dl.appendChild(el('dd', { text: value === undefined || value === null || value === '' ? '—' : String(value) }));
  }

  // --------------------------------------------------------------- replay ----

  function replayTimes() {
    const times = Array.from(new Set(state.decisions.map((d) => d.decision_time_ms))).sort((a, b) => a - b);
    return times;
  }

  function setReplay(on) {
    state.replay.on = on;
    const button = $('replayBtn');
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
    button.textContent = on ? 'Salir de replay' : 'Replay';
    if (state.replay.timer) {
      clearInterval(state.replay.timer);
      state.replay.timer = null;
    }
    if (!on) {
      state.replay.clock = null;
      state.replay.index = 0;
      $('modeBadge').textContent = 'PAPER';
      notice('');
      renderChart();
      renderTimeline();
      return;
    }
    state.replay.times = replayTimes();
    state.replay.index = 0;
    state.replay.clock = state.replay.times.length ? state.replay.times[0] : null;
    $('modeBadge').textContent = 'REPLAY';
    noticeReplay();
    startReplayTimer();
    renderChart();
    renderTimeline();
  }

  function noticeReplay() {
    if (state.replay.clock === null) {
      notice('Replay activo: este run no tiene decisiones, no hay reloj que avanzar.', false);
      return;
    }
    notice('Replay activo (reloj de eventos). No se reejecuta el motor ni se envían órdenes. Tiempo: ' + fmtUtc(new Date(state.replay.clock).toISOString()), false);
  }

  function startReplayTimer() {
    state.replay.timer = setInterval(() => {
      state.replay.index += 1;
      if (state.replay.index >= state.replay.times.length) {
        clearInterval(state.replay.timer);
        state.replay.timer = null;
        return;
      }
      state.replay.clock = state.replay.times[state.replay.index];
      noticeReplay();
      renderChart();
      renderTimeline();
    }, 900);
  }

  // --------------------------------------------------------------- loading ----

  async function loadHealth() {
    const health = await api('/api/monitor/health');
    state.runs = health.runs || [];
    $('footerMeta').textContent =
      `API ${health.schema} · v${health.version} · ${health.read_only ? 'solo lectura' : 'ESCRITURA'} · fuente de velas: ${health.candle_source}`;
    if (!state.runs.length) {
      notice('No hay runs PAPER bajo el directorio configurado. Ejecuta el runtime PAPER y vuelve a cargar.', true);
      return null;
    }
    const select = $('runSelect');
    const current = state.runId;
    select.textContent = '';
    for (const run of state.runs) {
      if (run.error) continue;
      const option = el('option', { text: `${run.run_id} · ${run.event_count} eventos · ${run.mode}`, attrs: { value: run.run_id } });
      select.appendChild(option);
    }
    const available = Array.from(select.options).map((o) => o.value);
    state.runId = available.includes(current) ? current : available[0] || null;
    if (state.runId) select.value = state.runId;
    const selected = state.runs.find((r) => r.run_id === state.runId);
    if (selected) {
      setMode(selected.mode);
      renderConnection(selected);
    }
    return health;
  }

  async function loadRunData() {
    if (!state.runId) return;
    const runId = encodeURIComponent(state.runId);

    const trace = await api(`/api/monitor/runs/${runId}/trace`);
    state.counters = trace.counters || {};
    state.lastStep = trace.last_observable_step || null;
    state.notRecorded = trace.not_recorded || [];

    const assets = await api(`/api/monitor/assets?run_id=${runId}`);
    state.assets = assets;
    populateFilters(assets);

    const params = new URLSearchParams({ run_id: state.runId, limit: '500' });
    if (state.filters.symbol) params.set('symbol', state.filters.symbol);
    if (state.filters.status) params.set('status', state.filters.status);
    if (state.filters.strategy) params.set('strategy', state.filters.strategy);
    const decisions = await api('/api/monitor/decisions?' + params.toString());
    state.decisions = decisions.items || [];
    state.cursor = decisions.snapshot_sequence || 0;
    closeDrawerIfFilteredOut();
    renderConnection(decisions);

    await loadCandles();
    renderFunnel();
    renderTimeline();
    renderChart();
    connectStream();
  }

  function populateFilters(assets) {
    const symbolSelect = $('symbolSelect');
    const strategySelect = $('strategySelect');
    const timeframeSelect = $('timeframeSelect');
    const statusSelect = $('statusSelect');

    const keep = state.filters;

    if (!symbolSelect.options.length || symbolSelect.dataset.run !== state.runId) {
      symbolSelect.textContent = '';
      const all = el('option', { text: 'Todos', attrs: { value: '' } });
      symbolSelect.appendChild(all);
      for (const symbol of assets.symbols || []) {
        symbolSelect.appendChild(el('option', { text: symbol, attrs: { value: symbol } }));
      }
      symbolSelect.dataset.run = state.runId;
      // '' means "every symbol". Only drop a *previously chosen* symbol that the
      // run no longer has; never turn "Todos" into the first symbol, which would
      // silently hide every decision of the other assets.
      if (keep.symbol && !(assets.symbols || []).includes(keep.symbol)) keep.symbol = '';
      symbolSelect.value = keep.symbol;

      strategySelect.textContent = '';
      strategySelect.appendChild(el('option', { text: 'Todas', attrs: { value: '' } }));
      for (const strategy of assets.strategies || []) {
        strategySelect.appendChild(el('option', { text: strategy, attrs: { value: strategy } }));
      }
      strategySelect.value = keep.strategy;

      timeframeSelect.textContent = '';
      for (const tf of assets.timeframes || ['5m']) {
        timeframeSelect.appendChild(el('option', { text: tf, attrs: { value: tf } }));
      }
      keep.timeframe = assets.timeframes && assets.timeframes.length ? assets.timeframes[0] : '5m';
      timeframeSelect.value = keep.timeframe;

      statusSelect.textContent = '';
      statusSelect.appendChild(el('option', { text: 'Todos', attrs: { value: '' } }));
      for (const status of assets.statuses || []) {
        const labels = { NO_TRADE: 'NO_TRADE', SHADOW_OBSERVED: 'SHADOW', ACCEPTED_NOT_EXECUTED: 'ACEPTADA (no ejecutada)', EXECUTED_PAPER: 'EJECUTADA PAPER', EXECUTION_FAILED: 'EJECUCIÓN FALLIDA', UNDECIDED: 'SIN DECISIÓN' };
        statusSelect.appendChild(el('option', { text: labels[status] || status, attrs: { value: status } }));
      }
      statusSelect.value = keep.status;
    }
    renderLegend();
  }

  // A drilldown for a decision that the current filters exclude would be a
  // lie about what is on screen: close it instead of leaving stale context.
  function closeDrawerIfFilteredOut() {
    if (!state.selected) return;
    const stillVisible = state.decisions.some((d) => d.decision_id === state.selected);
    if (!stillVisible) {
      state.selected = null;
      document.getElementById('drawer').hidden = true;
    }
  }

  function renderLegend() {
    const legend = $('legend');
    legend.textContent = '';
    const entries = [
      ['◆ Señal', 'neutral'],
      ['✕ NO_TRADE', 'bad'],
      ['◐ SHADOW', 'warn'],
      ['✓ Aceptada', 'good'],
      ['● Fill PAPER', 'info-strong'],
      ['⊘ Fallida', 'bad'],
    ];
    for (const [text, tone] of entries) {
      const span = el('span', { class: 'tone-' + tone, text });
      legend.appendChild(span);
    }
  }

  /** One chart can only plot one asset: with "Todos" the chart pins the first
      available symbol and says so, while the timeline keeps every symbol. */
  function chartSymbol() {
    if (state.filters.symbol) return state.filters.symbol;
    const symbols = (state.assets && state.assets.symbols) || [];
    return symbols[0] || '';
  }

  async function loadCandles() {
    state.candles = [];
    state.candleError = null;
    const overlay = $('chartOverlay');
    const symbol = chartSymbol();
    const timeframe = state.filters.timeframe;
    $('chartTitle').textContent = symbol
      ? `Velas · ${symbol} · ${timeframe}` +
        (state.filters.symbol ? '' : ' · timeline: todos los símbolos')
      : `Velas · sin símbolo · ${timeframe}`;
    if (!symbol) {
      overlay.hidden = false;
      overlay.textContent = 'Sin símbolo seleccionado: no hay velas que mostrar.';
      return;
    }
    const times = state.decisions.map((d) => d.decision_time_ms);
    const asOf = times.length ? Math.max(...times) : null;
    const width = timeframeSeconds(timeframe) * 1000;
    const params = new URLSearchParams({ symbol, timeframe, limit: '500' });
    if (times.length) {
      params.set('from', String(Math.min(...times) - 40 * width));
      params.set('to', String(asOf + width));
      params.set('as_of', String(asOf));
    }
    try {
      const body = await api('/api/monitor/candles?' + params.toString());
      state.candles = body.bars || [];
      if (body.fixture) {
        notice('Velas de FIXTURE (datos de prueba): no representan el mercado real.', false);
      } else {
        notice('');
      }
      overlay.hidden = state.candles.length > 0;
      if (!state.candles.length) {
        overlay.textContent = 'La fuente de velas no devolvió barras para esta ventana.';
      }
    } catch (error) {
      state.candleError = error;
      overlay.hidden = false;
      overlay.textContent =
        error.code === 'CANDLES_UNAVAILABLE'
          ? 'Velas no disponibles: la fuente pública no es accesible desde este host. El timeline y los motivos siguen siendo válidos.'
          : 'Error cargando velas: ' + error.message;
    }
  }

  // ------------------------------------------------------------------ SSE ----

  function connectStream() {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
    if (!state.runId) return;
    const url = `/api/monitor/events/stream?run_id=${encodeURIComponent(state.runId)}&cursor=${state.cursor}`;
    const source = new EventSource(url);
    state.eventSource = source;

    source.addEventListener('snapshot', (event) => {
      try {
        const payload = JSON.parse(event.data);
        renderConnection(payload);
      } catch (err) { /* ignore malformed frame */ }
    });
    source.addEventListener('heartbeat', (event) => {
      try {
        renderConnection(JSON.parse(event.data));
      } catch (err) { /* ignore */ }
    });
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        state.cursor = Math.max(state.cursor, payload.sequence || 0);
        scheduleRefresh();
      } catch (err) { /* ignore malformed frame */ }
    };
    source.onerror = () => {
      renderConnection({ connection_state: 'DISCONNECTED', connection_reason: 'stream interrumpido; reintentando', data_age_ms: 0 });
    };
  }

  let refreshTimer = null;
  function scheduleRefresh() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(async () => {
      refreshTimer = null;
      try {
        await loadRunData();
      } catch (error) {
        notice('No se pudo refrescar: ' + error.message, true);
      }
    }, 600);
  }

  // ---------------------------------------------------------------- wiring ----

  function wire() {
    $('runSelect').addEventListener('change', async (event) => {
      state.runId = event.target.value;
      $('symbolSelect').dataset.run = '';
      state.assets = null;
      state.decisions = [];
      state.selected = null;
      await loadRunData();
    });

    $('symbolSelect').addEventListener('change', async (event) => {
      state.filters.symbol = event.target.value;
      await refreshDecisions();
    });
    $('timeframeSelect').addEventListener('change', async (event) => {
      state.filters.timeframe = event.target.value;
      await loadCandles();
      renderChart();
    });
    $('strategySelect').addEventListener('change', async (event) => {
      state.filters.strategy = event.target.value;
      await refreshDecisions();
    });
    $('statusSelect').addEventListener('change', async (event) => {
      state.filters.status = event.target.value;
      await refreshDecisions();
    });
    $('refreshBtn').addEventListener('click', () => loadRunData().catch((error) => notice(error.message, true)));
    $('replayBtn').addEventListener('click', () => setReplay(!state.replay.on));
    $('drawerClose').addEventListener('click', () => {
      $('drawer').hidden = true;
      state.selected = null;
      renderTimeline();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        $('drawer').hidden = true;
        state.selected = null;
        renderTimeline();
      }
    });

    setInterval(() => {
      const now = new Date();
      $('clockUtc').textContent = now.toISOString().slice(11, 19);
      $('clockLocal').textContent = now.toLocaleTimeString();
    }, 1000);
  }

  async function refreshDecisions() {
    if (!state.runId) return;
    const params = new URLSearchParams({ run_id: state.runId, limit: '500' });
    if (state.filters.symbol) params.set('symbol', state.filters.symbol);
    if (state.filters.status) params.set('status', state.filters.status);
    if (state.filters.strategy) params.set('strategy', state.filters.strategy);
    const body = await api('/api/monitor/decisions?' + params.toString());
    state.decisions = body.items || [];
    state.cursor = body.snapshot_sequence || state.cursor;
    closeDrawerIfFilteredOut();
    renderConnection(body);
    await loadCandles();
    renderTimeline();
    renderChart();
    connectStream();
  }

  async function boot() {
    initChart();
    wire();
    try {
      const health = await loadHealth();
      if (!health) return;
      await loadRunData();
    } catch (error) {
      notice('Error inicial: ' + error.message, true);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
