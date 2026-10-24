// Engine results panel: numbers come from the Python simulator (/api/demo), not simulator.js.
(function () {
  'use strict';
  try {
    var el = document.getElementById('engine-panel');
    if (!el || !window.fetch) return;
    var esc = function (s) {
      return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
      });
    };
    var outcome = function (o) {
      if (!o) return null;
      if (typeof o === 'string') return o;
      var s = o.status || o.outcome || '';
      var r = o.reason || o.failure_reason || '';
      return r ? s + ' (' + String(r).replace(/_/g, ' ') + ')' : s;
    };
    fetch('/api/demo').then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    }).then(function (d) {
      var rows = [];
      var add = function (k, v) { if (v != null && v !== '') rows.push('<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>'); };
      var sc = d.scenario || {};
      var ed = (sc.timetable_edits || []).map(function (e) {
        return e.trip_id + ' ' + (e.shift_minutes > 0 ? '+' : '') + e.shift_minutes + ' min';
      }).join(', ');
      var cmp = d.compare || {};
      add('Resident', d.display_name);
      add('Home island', d.island_name || d.island_id);
      add('Category', String(d.category || '').replace(/_/g, ' '));
      add('Baseline', outcome(d.baseline));
      add('Scenario edit', ed || 'none');
      add('Scenario', outcome(d.scenario_result || d.after));
      if (cmp.gained != null) add('Gained access', cmp.gained);
      if (cmp.lost != null) add('Lost access', cmp.lost);
      el.innerHTML = '<h3>Engine results (Python simulator)</h3><dl>' + rows.join('') +
        '</dl><p class="note">Computed by the Python engine (simulator/). Synthetic resident; modelled access barrier, not observed care.</p>';
      el.hidden = false;
    }).catch(function () { el.hidden = true; });
  } catch (e) {
    try { document.getElementById('engine-panel').hidden = true; } catch (_) {}
  }
})();
