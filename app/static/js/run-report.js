var currentRunId = null;
var runEventSource = null;

function connectRunLogs(runId, onDone) {
  if (runEventSource) {
    runEventSource.close();
  }

  var panel = document.getElementById('run-logs-panel');
  var logsDiv = document.getElementById('run-logs');
  var badge = document.getElementById('run-status-badge');
  if (panel) panel.style.display = 'block';

  currentRunId = runId;

  runEventSource = new EventSource('/api/reports/run-now/events/' + runId);

  runEventSource.onmessage = function (event) {
    try {
      var data = JSON.parse(event.data);

      if (data.type === 'done' || data.type === 'final') {
        runEventSource.close();
        runEventSource = null;
        currentRunId = null;
        if (badge) {
          badge.className = 'badge ' + (data.status === 'success' ? 'badge-success' : 'badge-danger');
          badge.textContent = data.status ? data.status.replace('_', ' ').toUpperCase() : 'DONE';
        }
        if (onDone) onDone(data.status);
        return;
      }

      if (data.type === 'final') return;

      if (logsDiv) {
        var entry = document.createElement('div');
        entry.className = 'run-log-entry run-log-' + data.type;
        var ts = data.timestamp ? data.timestamp.slice(11, 19) : '';
        var icon = data.type === 'info' ? 'ℹ️' : data.type === 'warning' ? '⚠️' : data.type === 'error' ? '❌' : data.type === 'success' ? '✅' : '•';
        entry.innerHTML = '<span class="run-log-time">' + ts + '</span><span class="run-log-icon">' + icon + '</span><span class="run-log-msg">' + escapeHtml(data.message) + '</span>';
        logsDiv.appendChild(entry);
        logsDiv.scrollTop = logsDiv.scrollHeight;
      }

      if (badge && data.progress) {
        badge.textContent = data.progress + '%';
      }
    } catch (e) {
      // ignore parse errors
    }
  };

  runEventSource.onerror = function () {
    if (runEventSource) {
      runEventSource.close();
      runEventSource = null;
    }
  };
}

function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function startSseRun(force) {
  force = force || false;
  var btn = event && event.target ? event.target : document.querySelector('.run-report-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Running...'; }

  var url = '/api/reports/run-now' + (force ? '?force=true' : '');

  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    .then(function (resp) { return resp.json().then(function (data) { return { status: resp.status, data: data }; }); })
    .then(function (result) {
      if (result.status === 409) {
        showToast(result.data.detail || 'A report is already running', 'warning');
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Run Manual Report'; }
        return;
      }

      if (result.data.run_id) {
        connectRunLogs(result.data.run_id, function (status) {
          showToast('Report ' + status.replace('_', ' '), status === 'success' ? 'success' : 'error');
          if (btn) { btn.disabled = false; btn.textContent = '🔄 Run Manual Report'; }
          setTimeout(function () { location.reload(); }, 2000);
        });
        showToast('Report generation started', 'info');
      } else {
        if (result.data.status === 'skipped') {
          showToast(result.data.message, 'warning');
        } else {
          showToast('Status: ' + (result.data.status || 'unknown'), 'info');
        }
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Run Manual Report'; }
        setTimeout(function () { location.reload(); }, 1500);
      }
    })
    .catch(function (err) {
      showToast('Error: ' + err.message, 'error');
      if (btn) { btn.disabled = false; btn.textContent = '🔄 Run Manual Report'; }
    });
}
