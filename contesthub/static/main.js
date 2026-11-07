/* ==================== 收藏 ==================== */
function fav(id, btn) {
  fetch(`/fav/${id}`, { method: 'POST' })
    .then((r) => r.json())
    .then((d) => {
      if (!d.ok) return;
      btn.classList.toggle('on');
      btn.textContent = btn.classList.contains('on') ? '⭐ 已收藏' : '☆ 收藏';
    })
    .catch(() => {});
}

/* ==================== 侧边栏 ==================== */
function applySidebar(hidden) {
  document.body.classList.toggle('hide-aside', hidden);
  var showBtn = document.getElementById('show-sidebar');
  if (showBtn) showBtn.textContent = hidden ? '⟩ 侧栏' : '⟩';
}

function toggleSidebar() {
  var hidden = !document.body.classList.contains('hide-aside');
  applySidebar(hidden);
  try { localStorage.setItem('contesthub.hideAside', hidden ? '1' : '0'); } catch (e) {}
}

/* ==================== 同步（异步 + 轮询） ==================== */
var _syncPoll = null;

function _setSyncHint(text, isErr) {
  var hint = document.getElementById('sync-hint');
  if (!hint) return;
  hint.textContent = text;
  hint.classList.toggle('err', !!isErr);
}

function _renderSyncRows(sources) {
  var box = document.querySelector('.sync-status');
  if (!box || !sources || !sources.length) return;
  box.innerHTML = sources.map(function (r) {
    var detail = r.ok
      ? '+' + r.added + '/~' + r.updated + ' · ' + r.count + ' 条'
      : (r.error || '不可用');
    return '<div class="sync-row" title="' + (r.error || '').replace(/"/g, '') + '">' +
      '<span class="sync-dot ' + (r.ok ? 'ok' : 'bad') + '"></span>' +
      '<span class="sync-name">' + r.label + '</span>' +
      '<span class="muted small ' + (r.ok ? '' : 'err') + '">' + detail + '</span>' +
      '<span class="muted small">' + (r.ran_at || '').slice(5, 16) + '</span>' +
      '</div>';
  }).join('');
}

function _finishSync(result) {
  if (!result || !result.length) {
    _setSyncHint('同步结束（无结果）', true);
    return;
  }
  var added = result.reduce(function (s, r) { return s + (r.added || 0); }, 0);
  var updated = result.reduce(function (s, r) { return s + (r.updated || 0); }, 0);
  var failed = result.filter(function (r) { return !r.ok; });
  var text = '✅ 同步完成：新增 ' + added + ' 场，更新 ' + updated + ' 场';
  if (failed.length) {
    text += '；' + failed.length + ' 个来源失败（' +
      failed.map(function (r) { return r.label; }).join('、') + '）';
  }
  _setSyncHint(text, failed.length > 0);
  // 结果有变化时刷新页面，让卡片/时间轴同步更新
  setTimeout(function () { window.location.reload(); }, 1200);
}

function _pollSync() {
  if (_syncPoll) clearInterval(_syncPoll);
  _syncPoll = setInterval(function () {
    fetch('/api/sync/status').then(function (r) { return r.json(); }).then(function (d) {
      _renderSyncRows(d.sources);
      if (d.running) {
        _setSyncHint('⏳ 正在同步中…（各来源并行抓取，通常 10–40 秒）');
        return;
      }
      clearInterval(_syncPoll);
      _syncPoll = null;
      _finishSync(d.result);
    }).catch(function () {
      clearInterval(_syncPoll);
      _syncPoll = null;
      _setSyncHint('同步状态查询失败，请刷新页面查看', true);
    });
  }, 1500);
}

function syncNow(src, btn) {
  if (btn) { btn.disabled = true; setTimeout(function () { btn.disabled = false; }, 3000); }
  _setSyncHint('⏳ 正在提交同步任务…');
  fetch('/api/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'src=' + encodeURIComponent(src || 'all'),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) {
      _setSyncHint('⏳ ' + (d.message || '已有同步任务在进行中'));
      _pollSync();
      return;
    }
    _pollSync();
  }).catch(function () {
    _setSyncHint('提交同步失败，请检查服务是否在运行', true);
  });
}

/* ==================== 实时诊断（不写库） ==================== */
function probeSources(btn, probeOnly) {
  if (!probeOnly) { syncNow('all', btn); return; }
  var box = document.getElementById('probe-result');
  if (btn) btn.disabled = true;
  if (box) box.textContent = '⏳ 正在逐个抓取来源（约 10–60 秒）…';
  fetch('/api/probe').then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) { if (box) box.textContent = '诊断失败'; return; }
    var lines = d.results.map(function (r) {
      var icon = r.ok ? '✅' : '❌';
      var detail = r.ok ? r.detail : ((r.error || '') + (r.detail ? '｜' + r.detail : ''));
      return icon + ' ' + r.label + '：' + detail + '（' + r.elapsed + 's）';
    });
    if (box) box.innerHTML = lines.map(function (l) {
      return '<div>' + l.replace(/</g, '&lt;') + '</div>';
    }).join('');
  }).catch(function () {
    if (box) box.textContent = '诊断请求失败，请检查服务状态';
  }).then(function () { if (btn) btn.disabled = false; });
}

/* ==================== 初始化 ==================== */
document.addEventListener('DOMContentLoaded', function () {
  var saved = '0';
  try { saved = localStorage.getItem('contesthub.hideAside') || '0'; } catch (e) {}
  applySidebar(saved === '1');
  // 进入页面时若后台正在同步，自动接上进度轮询
  fetch('/api/sync/status').then(function (r) { return r.json(); }).then(function (d) {
    if (d && d.running) {
      _renderSyncRows(d.sources);
      _pollSync();
    }
  }).catch(function () {});
});
