/* Email Hub module — JAIDE ATS */
(function () {
  "use strict";

  const NYLAS_DISMISSED_KEY = "jaide_nylas_banner_dismissed";

  /* ------------------------------------------------------------------ */
  /* State                                                                */
  /* ------------------------------------------------------------------ */
  let _currentPage = 1;
  let _currentFilters = { q: "", job_id: "", days: "", status: "" };
  let _totalPages = 1;
  const PER_PAGE = 25;

  /* ------------------------------------------------------------------ */
  /* Entry-point: show Email Hub view                                     */
  /* ------------------------------------------------------------------ */
  function showEmailHub() {
    // Pure data initializer — navigation to #view-email is handled by navigateTo("email")
    _currentPage = 1;
    _currentFilters = { q: "", job_id: "", days: "", status: "" };
    _initBanner();
    _bindFilterBar();
    _loadHub(1);
  }

  /* ------------------------------------------------------------------ */
  /* Nylas banner                                                         */
  /* ------------------------------------------------------------------ */
  function _initBanner() {
    const banner = document.getElementById("nylas-banner");
    if (!banner) return;
    if (localStorage.getItem(NYLAS_DISMISSED_KEY) === "1") {
      banner.style.display = "none";
      return;
    }
    banner.style.display = "flex";
    const btn = document.getElementById("nylas-banner-dismiss");
    if (btn) {
      btn.onclick = function () {
        localStorage.setItem(NYLAS_DISMISSED_KEY, "1");
        banner.style.display = "none";
      };
    }
  }

  /* ------------------------------------------------------------------ */
  /* Filter bar binding                                                   */
  /* ------------------------------------------------------------------ */
  function _bindFilterBar() {
    const q = document.getElementById("hub-filter-q");
    const job = document.getElementById("hub-filter-job");
    const days = document.getElementById("hub-filter-days");
    const status = document.getElementById("hub-filter-status");

    function applyFilters() {
      _currentFilters.q = (q ? q.value : "").trim();
      _currentFilters.job_id = (job ? job.value : "");
      _currentFilters.days = (days ? days.value : "");
      _currentFilters.status = (status ? status.value : "");
      _currentPage = 1;
      _loadHub(1);
    }

    if (q) { q.oninput = _debounce(applyFilters, 350); }
    if (job) { job.onchange = applyFilters; }
    if (days) { days.onchange = applyFilters; }
    if (status) { status.onchange = applyFilters; }

    // Status tabs
    document.querySelectorAll(".hub-tab").forEach(tab => {
      tab.onclick = function () {
        document.querySelectorAll(".hub-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        _currentFilters.status = tab.dataset.status || "";
        _currentPage = 1;
        _loadHub(1);
      };
    });
  }

  /* ------------------------------------------------------------------ */
  /* Load hub data                                                        */
  /* ------------------------------------------------------------------ */
  function _loadHub(page) {
    _currentPage = page;
    const tableArea = document.getElementById("hub-table-area");
    if (tableArea) tableArea.innerHTML = '<div class="hub-loading">Loading…</div>';

    const params = new URLSearchParams({
      page,
      per_page: PER_PAGE,
      q: _currentFilters.q,
      job_id: _currentFilters.job_id,
      days: _currentFilters.days,
      status: _currentFilters.status,
    });

    fetch("/api/email/hub?" + params.toString())
      .then(r => r.json())
      .then(data => {
        _renderStats(data.stats || {});
        _renderTable(data.emails || [], data.total || 0, page, data.stats);
        _totalPages = Math.ceil((data.total || 0) / PER_PAGE);
      })
      .catch(err => {
        if (tableArea) tableArea.innerHTML = '<div class="hub-empty">Failed to load email data.</div>';
        console.error("Email hub load error:", err);
      });
  }

  /* ------------------------------------------------------------------ */
  /* Render stats bar                                                     */
  /* ------------------------------------------------------------------ */
  function _renderStats(stats) {
    const bar = document.getElementById("hub-stats-bar");
    if (!bar) return;
    const sent = stats.total_sent || 0;
    const opened = stats.total_opened || 0;
    const clicked = stats.total_clicked || 0;
    const replied = stats.total_replied || 0;
    // Open/click rates show "—" when no Nylas data (all zeros = not tracked yet)
    const openRateStr = opened > 0 ? Math.round((opened / sent) * 100) + "%" : "—";
    const clickRateStr = clicked > 0 ? Math.round((clicked / sent) * 100) + "%" : "—";
    bar.innerHTML = `
      <div class="hub-stat-chip"><span class="hub-stat-val">${sent.toLocaleString()}</span><span class="hub-stat-label">Sent</span></div>
      <div class="hub-stat-chip nylas-gated"><span class="hub-stat-val">${openRateStr}</span><span class="hub-stat-label">Open Rate</span></div>
      <div class="hub-stat-chip nylas-gated"><span class="hub-stat-val">${clickRateStr}</span><span class="hub-stat-label">Click Rate</span></div>
      <div class="hub-stat-chip nylas-gated"><span class="hub-stat-val">${replied > 0 ? replied : "—"}</span><span class="hub-stat-label">Replies</span></div>
    `;
  }

  /* ------------------------------------------------------------------ */
  /* Render email table                                                   */
  /* ------------------------------------------------------------------ */
  function _renderTable(emails, total, page) {
    const area = document.getElementById("hub-table-area");
    if (!area) return;

    if (!emails.length) {
      area.innerHTML = `<div class="hub-empty">No emails found. Send some outreach to get started.</div>`;
      return;
    }

    const rows = emails.map(_renderRow).join("");
    const pagination = _renderPagination(total, page);

    area.innerHTML = `
      <div class="hub-count-bar">Showing ${((page - 1) * PER_PAGE) + 1}–${Math.min(page * PER_PAGE, total)} of ${total.toLocaleString()} emails</div>
      <table class="hub-email-table">
        <thead>
          <tr>
            <th>Subject</th>
            <th>Recipients</th>
            <th>Job / Context</th>
            <th>Delivered</th>
            <th>Open Rate</th>
            <th>Sent Date</th>
            <th>Sent By</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      ${pagination}
    `;

    // Bind row clicks
    area.querySelectorAll(".hub-row-clickable").forEach(row => {
      row.onclick = function () {
        _showDetail(row.dataset.groupId);
      };
    });

    // Bind pagination
    area.querySelectorAll(".hub-page-btn").forEach(btn => {
      btn.onclick = function () {
        const p = parseInt(btn.dataset.page);
        if (!isNaN(p)) _loadHub(p);
      };
    });
  }

  function _renderRow(email) {
    const groupId = email.group_id || email.id;
    const recipients = email.recipient_count || 1;
    const recipLabel = recipients > 1
      ? `<span class="hub-badge-bulk">${recipients} recipients</span>`
      : _esc(email.candidate_name || email.recipient_email || "—");
    const jobLabel = email.job_title ? `<span class="hub-job-tag">${_esc(email.job_title)}</span>` : "—";
    // For grouped rows: use delivered/failed counts; for individual rows: use status field
    const totalRecip = email.recipient_count || 1;
    const delivered = email.recipient_count > 1
      ? (email.failed > 0
        ? `<span class="hub-status-badge failed">${email.failed} failed</span>`
        : `<span class="hub-status-badge sent">${email.delivered || totalRecip} sent</span>`)
      : _statusBadge(email.status);
    const openRate = (email.opened > 0 && totalRecip > 0)
      ? Math.round((email.opened / totalRecip) * 100) + "%"
      : "<span class='hub-na'>—</span>";
    const sentDate = email.sent_at ? _fmtDate(email.sent_at) : "—";
    const sentBy = email.sent_by || "Admin";

    return `
      <tr class="hub-row-clickable" data-group-id="${_esc(groupId)}">
        <td class="hub-subject">${_esc(email.subject || "(no subject)")}</td>
        <td class="hub-recipients">${recipLabel}</td>
        <td>${jobLabel}</td>
        <td>${delivered}</td>
        <td class="hub-na-cell">${openRate}</td>
        <td>${sentDate}</td>
        <td>${_esc(sentBy)}</td>
      </tr>
    `;
  }

  function _statusBadge(status) {
    const map = {
      sent: '<span class="hub-status-badge sent">Sent</span>',
      failed: '<span class="hub-status-badge failed">Failed</span>',
      skipped: '<span class="hub-status-badge skipped">Skipped</span>',
      opened: '<span class="hub-status-badge opened">Opened</span>',
    };
    return map[status] || `<span class="hub-status-badge">${_esc(status || "—")}</span>`;
  }

  function _renderPagination(total, page) {
    if (total <= PER_PAGE) return "";
    const pages = Math.ceil(total / PER_PAGE);
    let btns = "";
    for (let i = 1; i <= pages; i++) {
      if (i === page) {
        btns += `<button class="hub-page-btn active" data-page="${i}">${i}</button>`;
      } else if (i === 1 || i === pages || Math.abs(i - page) <= 2) {
        btns += `<button class="hub-page-btn" data-page="${i}">${i}</button>`;
      } else if (btns.slice(-4) !== "…") {
        btns += `<span class="hub-page-ellipsis">…</span>`;
      }
    }
    return `<div class="hub-pagination">${btns}</div>`;
  }

  /* ------------------------------------------------------------------ */
  /* Detail view                                                          */
  /* ------------------------------------------------------------------ */
  function _showDetail(groupId) {
    const detailArea = document.getElementById("hub-detail-area");
    const tableArea = document.getElementById("hub-table-area");
    const statsBar = document.getElementById("hub-stats-bar");
    const countBar = document.querySelector(".hub-count-bar");
    if (!detailArea) return;

    detailArea.style.display = "block";
    if (tableArea) tableArea.style.display = "none";
    if (statsBar) statsBar.style.display = "none";

    detailArea.innerHTML = '<div class="hub-loading">Loading detail…</div>';

    fetch("/api/email/hub/" + encodeURIComponent(groupId))
      .then(r => r.json())
      .then(data => _renderDetail(data.entries || [], groupId))
      .catch(() => {
        detailArea.innerHTML = '<div class="hub-empty">Failed to load detail.</div>';
      });
  }

  function _renderDetail(entries, groupId) {
    const detailArea = document.getElementById("hub-detail-area");
    if (!detailArea) return;

    const first = entries[0] || {};
    const subject = first.subject || "(no subject)";
    const sentAt = first.sent_at ? _fmtDate(first.sent_at) : "—";
    const sentBy = first.sent_by || "Admin";
    const body = first.body || "";

    const recipRows = entries.map(e => `
      <tr>
        <td>${_esc(e.candidate_name || "—")}</td>
        <td>${_esc(e.recipient_email || "—")}</td>
        <td>${_statusBadge(e.status)}</td>
        <td>${e.opened_at ? _fmtDate(e.opened_at) : '<span class="hub-na">—</span>'}</td>
        <td>${e.clicked_at ? _fmtDate(e.clicked_at) : '<span class="hub-na">—</span>'}</td>
        <td>${e.replied_at ? _fmtDate(e.replied_at) : '<span class="hub-na">—</span>'}</td>
      </tr>
    `).join("");

    detailArea.innerHTML = `
      <div class="hub-detail-header">
        <button class="hub-back-btn" id="hub-back-btn">← Back to list</button>
        <div class="hub-detail-meta">
          <span class="hub-detail-subject">${_esc(subject)}</span>
          <span class="hub-detail-info">Sent ${sentAt} · by ${_esc(sentBy)} · ${entries.length} recipient${entries.length !== 1 ? "s" : ""}</span>
        </div>
      </div>
      ${body ? `
      <div class="hub-detail-body-section">
        <div class="hub-detail-body-label">Email Body</div>
        <div class="hub-detail-body">${_fmtBody(body)}</div>
      </div>` : ""}
      <div class="hub-detail-recipients-label">Recipients</div>
      <table class="hub-email-table hub-detail-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Status</th>
            <th>Opened</th>
            <th>Clicked</th>
            <th>Replied</th>
          </tr>
        </thead>
        <tbody>${recipRows}</tbody>
      </table>
      <div class="nylas-tracking-note">
        Open, click, and reply tracking requires Nylas integration. <a href="#" class="hub-link">Connect Nylas →</a>
      </div>
    `;

    document.getElementById("hub-back-btn").onclick = _backToList;
  }

  function _backToList() {
    const detailArea = document.getElementById("hub-detail-area");
    const tableArea = document.getElementById("hub-table-area");
    const statsBar = document.getElementById("hub-stats-bar");
    if (detailArea) detailArea.style.display = "none";
    if (tableArea) tableArea.style.display = "block";
    if (statsBar) statsBar.style.display = "flex";
  }

  /* ------------------------------------------------------------------ */
  /* Helpers                                                              */
  /* ------------------------------------------------------------------ */
  function _esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function _fmtDate(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    } catch { return iso; }
  }

  function _fmtBody(body) {
    if (!body) return "";
    // Convert newlines to <br> and escape HTML
    return _esc(body).replace(/\n/g, "<br>");
  }

  function _debounce(fn, ms) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  /* ------------------------------------------------------------------ */
  /* Export                                                               */
  /* ------------------------------------------------------------------ */
  window.JAIDE = window.JAIDE || {};
  window.JAIDE.showEmailHub = showEmailHub;
})();
