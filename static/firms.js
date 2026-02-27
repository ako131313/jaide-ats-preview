// ============================================================
// JAIDE ATS – Firms Module (CRM Redesign)
// ============================================================
(function () {
    "use strict";

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    function esc(s) {
        if (s == null) return "";
        return String(s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function fmtNum(n) {
        if (!n || n === "" || n === "nan") return "—";
        const num = parseInt(String(n).replace(/[^\d]/g, ""));
        return isNaN(num) ? "—" : num.toLocaleString();
    }

    function fmtPPP(val) {
        if (!val || val === "" || val === "nan") return "—";
        const str = String(val).replace(/[^\d.]/g, "");
        const num = parseFloat(str);
        if (isNaN(num)) return "—";
        if (num >= 1000000) return `$${(num / 1000000).toFixed(1)}M`;
        if (num >= 1000) return `$${(num / 1000).toFixed(0)}K`;
        return `$${num.toLocaleString()}`;
    }

    function relDate(dateStr) {
        if (!dateStr) return null;
        const d = new Date(dateStr);
        if (isNaN(d)) return dateStr;
        const now = new Date();
        const diff = Math.round((now - d) / 86400000);
        if (diff === 0) return "Today";
        if (diff === 1) return "Yesterday";
        if (diff < 7) return `${diff} days ago`;
        if (diff < 30) return `${Math.round(diff / 7)}w ago`;
        if (diff < 365) return `${Math.round(diff / 30)}mo ago`;
        return `${Math.round(diff / 365)}y ago`;
    }

    function daysFromNow(dateStr) {
        if (!dateStr) return null;
        const d = new Date(dateStr);
        if (isNaN(d)) return null;
        const now = new Date();
        now.setHours(0, 0, 0, 0);
        d.setHours(0, 0, 0, 0);
        return Math.round((d - now) / 86400000);
    }

    function statusBadgeHtml(status) {
        const map = {
            "Active Client": "status-badge status-badge-active",
            "Prospect": "status-badge status-badge-prospect",
            "Past Client": "status-badge status-badge-past",
            "Reference Only": "status-badge status-badge-reference",
        };
        const cls = map[status] || "status-badge status-badge-reference";
        return `<span class="${cls}">${esc(status || "Reference Only")}</span>`;
    }

    // ── PIE CHART COLORS ──────────────────────────────────────────────────
    const PIE_COLORS = [
        "#0059FF","#0791FE","#f59e0b","#ef4444","#8b5cf6",
        "#ec4899","#14b8a6","#f97316","#06b6d4","#84cc16",
        "#6366f1","#d946ef","#0ea5e9","#10b981","#e11d48",
        "#a855f7","#eab308","#2563eb","#dc2626","#7c3aed",
        "#059669","#db2777","#ca8a04",
    ];

    // ── STATE ─────────────────────────────────────────────────────────────
    let _firmsCache = [];       // All firms from /api/firms
    let _myClients = [];        // Active Client + Prospect
    let _loaded = false;
    let _myClientsLoaded = false;
    let _aiSearchActive = false;

    // Table state
    let _filtered = [];
    let _page = 1;
    const PAGE_SIZE = 50;
    let _sortCol = "name";
    let _sortDir = "asc";

    // Filter state
    let _fSearch = "";
    let _fStatus = "";
    let _fSize = "";
    let _fPractice = "";
    let _fActivity = "";
    let _fSource = "all";

    // My clients sort
    let _mcSort = "activity";

    // Expose on window.JAIDE
    window.JAIDE = window.JAIDE || {};

    // ── LOAD ──────────────────────────────────────────────────────────────
    function loadFirms() {
        if (_loaded && _firmsCache.length) {
            renderAll();
            return;
        }
        // Load both lists in parallel
        Promise.all([
            fetch("/api/firms").then(r => r.json()),
            fetch("/api/firms/my-clients").then(r => r.json()),
            fetch("/api/firms/recently-viewed").then(r => r.json()),
        ])
        .then(([firmsData, myData, rvData]) => {
            _firmsCache = firmsData.firms || [];
            _myClients = myData.firms || [];
            _loaded = true;
            _myClientsLoaded = true;
            renderAll();
            renderRecentlyViewed(rvData.firms || []);
            populatePracticeFilter();
        })
        .catch(err => {
            console.error("[Firms] load error", err);
            const g = $("#my-clients-loading");
            if (g) g.textContent = "Failed to load firms.";
        });
    }

    window.JAIDE.loadFirms = loadFirms;

    function renderAll() {
        renderMyClients();
        applyFiltersAndRender();
    }

    // ── MY CLIENTS ────────────────────────────────────────────────────────
    function renderMyClients() {
        const container = $("#my-clients-list");
        if (!container) return;
        const countEl = $("#my-clients-count");

        // Sort
        let sorted = [..._myClients];
        if (_mcSort === "name") sorted.sort((a, b) => (a.firm_name || "").localeCompare(b.firm_name || ""));
        else if (_mcSort === "jobs") sorted.sort((a, b) => (b.active_jobs || 0) - (a.active_jobs || 0));
        else if (_mcSort === "pipeline") sorted.sort((a, b) => (b.pipeline_count || 0) - (a.pipeline_count || 0));
        else if (_mcSort === "followup") sorted.sort((a, b) => {
            const da = a.next_task_due || "9999-12-31";
            const db = b.next_task_due || "9999-12-31";
            return da.localeCompare(db);
        });
        else if (_mcSort === "priority") {
            const pOrder = { High: 0, Normal: 1, Low: 2 };
            sorted.sort((a, b) => (pOrder[a.priority] ?? 1) - (pOrder[b.priority] ?? 1));
        }
        else { // activity (default)
            sorted.sort((a, b) => {
                if (a.pinned && !b.pinned) return -1;
                if (!a.pinned && b.pinned) return 1;
                const da = a.last_contact_date || a.updated_at || "1970";
                const db = b.last_contact_date || b.updated_at || "1970";
                return db.localeCompare(da);
            });
        }

        if (countEl) countEl.textContent = sorted.length + " firms";

        if (!sorted.length) {
            container.innerHTML = `
                <div class="my-clients-empty">
                    <div class="my-clients-empty-title">No active clients yet.</div>
                    <div class="my-clients-empty-sub">Mark a firm as "Active Client" to start tracking your relationships here.</div>
                    <button class="btn-secondary btn-sm" onclick="document.getElementById('firms-search').focus()">Browse Firms →</button>
                </div>`;
            return;
        }

        container.innerHTML = sorted.map(f => buildMyClientRow(f)).join("");

        // Wire events
        container.querySelectorAll(".my-client-row-name[data-fpid]").forEach(el => {
            el.addEventListener("click", () => showFirmDetail(el.dataset.fpid));
        });
        container.querySelectorAll(".my-client-row-pin").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                togglePin(btn.dataset.name, btn.dataset.fpid, btn.dataset.pinned === "1");
            });
        });
        container.querySelectorAll(".mcr-view-btn").forEach(btn => {
            btn.addEventListener("click", () => showFirmDetail(btn.dataset.fpid));
        });
        container.querySelectorAll(".mcr-job-btn").forEach(btn => {
            btn.addEventListener("click", () => quickCreateJob(btn.dataset.name));
        });
        container.querySelectorAll(".mcr-task-btn").forEach(btn => {
            btn.addEventListener("click", () => quickCreateTask(btn.dataset.name, btn.dataset.fpid));
        });
        container.querySelectorAll(".mcr-dots").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                openCtxMenu(e, btn.dataset.name, btn.dataset.fpid, btn.dataset.status, "myclient");
            });
        });
    }

    function buildMyClientRow(f) {
        const isPinned = f.pinned;
        const status = f.client_status || "Active Client";
        const priority = f.priority || "Normal";
        const fpId = f.fp_id || f.firm_fp_id || "";

        const lastContact = f.last_contact_date ? relDate(f.last_contact_date) : null;
        const areas = [f.top1, f.top2, f.top3]
            .map(a => a ? a.split(":")[0].trim() : "")
            .filter(Boolean).join(", ");

        const attyStr = f.total_attorneys ? fmtNum(f.total_attorneys) + " attorneys" : "";
        const pppStr = f.ppp ? fmtPPP(f.ppp) + " PPP" : "";
        const metaParts = [attyStr, pppStr, areas].filter(Boolean);

        // Follow-up
        let followupHtml = "";
        if (f.next_task_title) {
            const days = daysFromNow(f.next_task_due);
            const isOverdue = days !== null && days < 0;
            const dueLabel = days === null ? "" :
                days === 0 ? "Today" :
                days > 0 ? `in ${days}d` :
                `${Math.abs(days)}d overdue`;
            followupHtml = `<div class="my-client-row-followup ${isOverdue ? 'overdue' : ''}">
                Next: ${esc(f.next_task_title)}${dueLabel ? ` — ${dueLabel}` : ""}
            </div>`;
        }

        // Pipeline summary
        let pipelineHtml = "";
        if (f.pipeline_count > 0) {
            pipelineHtml = `<div class="my-client-row-pipeline">
                Pipeline: <a class="mcr-pipeline-link" data-name="${esc(f.firm_name)}">${f.pipeline_count} candidate${f.pipeline_count !== 1 ? "s" : ""}</a>
                ${f.interviewing_count > 0 ? `<span style="color:#d97706"> (${f.interviewing_count} interviewing)</span>` : ""}
            </div>`;
        }

        const prioClass = priority === "High" ? "priority-dot priority-dot-high" :
                          priority === "Low" ? "priority-dot priority-dot-low" :
                          "priority-dot priority-dot-normal";

        return `<div class="my-client-row${isPinned ? ' is-pinned' : ''}" data-name="${esc(f.firm_name)}">
            <button class="my-client-row-pin${isPinned ? ' pinned' : ''}"
                data-name="${esc(f.firm_name)}" data-fpid="${esc(fpId)}" data-pinned="${isPinned ? '1' : '0'}"
                title="${isPinned ? 'Unpin' : 'Pin to top'}">★</button>
            <div class="my-client-row-main">
                <div class="my-client-row-name" data-fpid="${esc(fpId)}">
                    <span class="priority-dot ${prioClass}"></span>
                    ${esc(f.firm_name)}
                    ${statusBadgeHtml(status)}
                </div>
                ${metaParts.length ? `<div class="my-client-row-meta">${esc(metaParts.join(" · "))}</div>` : ""}
                ${pipelineHtml}
                ${lastContact ? `<div class="my-client-row-meta" style="margin-top:2px">Last contact: ${lastContact}</div>` : ""}
                ${followupHtml}
            </div>
            <div class="my-client-row-stats">
                <div class="my-client-stat">
                    <div class="my-client-stat-val${f.active_jobs ? '' : ' zero'}">${f.active_jobs || 0}</div>
                    <div class="my-client-stat-label">Active Jobs</div>
                </div>
                <div class="my-client-stat">
                    <div class="my-client-stat-val${f.pipeline_count ? '' : ' zero'}">${f.pipeline_count || 0}</div>
                    <div class="my-client-stat-label">Pipeline</div>
                </div>
            </div>
            <div class="my-client-row-actions">
                <button class="mcr-btn mcr-btn-primary mcr-view-btn" data-fpid="${esc(fpId)}">View</button>
                <button class="mcr-btn mcr-job-btn" data-name="${esc(f.firm_name)}">+ Job</button>
                <button class="mcr-btn mcr-task-btn" data-name="${esc(f.firm_name)}" data-fpid="${esc(fpId)}">+ Task</button>
                <button class="mcr-dots" data-name="${esc(f.firm_name)}" data-fpid="${esc(fpId)}" data-status="${esc(status)}" title="More">⋯</button>
            </div>
        </div>`;
    }

    // ── RECENTLY VIEWED ───────────────────────────────────────────────────
    function renderRecentlyViewed(firms) {
        const bar = $("#recently-viewed-bar");
        const linksEl = $("#recently-viewed-links");
        if (!bar || !linksEl || !firms.length) return;
        linksEl.innerHTML = firms.map((f, i) => {
            const sep = i < firms.length - 1 ? '<span class="rv-sep">·</span>' : "";
            return `<span class="rv-link" data-fpid="${esc(f.firm_fp_id)}">${esc(f.firm_name)}</span>${sep}`;
        }).join(" ");
        bar.style.display = "flex";
        linksEl.querySelectorAll(".rv-link").forEach(el => {
            el.addEventListener("click", () => { if (el.dataset.fpid) showFirmDetail(el.dataset.fpid); });
        });
    }

    // ── FIRM DATABASE TABLE ───────────────────────────────────────────────
    function populatePracticeFilter() {
        const sel = $("#filter-practice");
        if (!sel) return;
        const areas = new Set();
        _firmsCache.forEach(f => {
            [f.top1, f.top2, f.top3].forEach(a => {
                if (a) areas.add(a.split(":")[0].trim());
            });
        });
        const sorted = Array.from(areas).sort();
        sorted.forEach(a => {
            const opt = document.createElement("option");
            opt.value = a;
            opt.textContent = a;
            sel.appendChild(opt);
        });
    }

    function applyFiltersAndRender() {
        let data = [..._firmsCache];

        // Source filter
        if (_fSource !== "all") {
            data = data.filter(f => (f.source || "fp") === _fSource);
        }

        // Text search (debounced via event listeners)
        if (_fSearch) {
            const q = _fSearch.toLowerCase();
            data = data.filter(f =>
                (f.name || "").toLowerCase().includes(q) ||
                (f.offices || f.office_locations || "").toLowerCase().includes(q) ||
                (f.top1 || "").toLowerCase().includes(q) ||
                (f.top2 || "").toLowerCase().includes(q) ||
                (f.top3 || "").toLowerCase().includes(q) ||
                (f.practice_areas || "").toLowerCase().includes(q)
            );
        }

        // Status filter
        if (_fStatus) {
            data = data.filter(f => (f.client_status || "Reference Only") === _fStatus);
        }

        // Size filter
        if (_fSize) {
            data = data.filter(f => {
                const n = parseInt(String(f.total_attorneys).replace(/[^\d]/g, "")) || 0;
                if (_fSize === "1000+") return n >= 1000;
                if (_fSize === "500-999") return n >= 500 && n < 1000;
                if (_fSize === "100-499") return n >= 100 && n < 500;
                if (_fSize === "under100") return n > 0 && n < 100;
                return true;
            });
        }

        // Practice area filter
        if (_fPractice) {
            data = data.filter(f => {
                const areas = [f.top1, f.top2, f.top3, f.practice_areas].join("|").toLowerCase();
                return areas.includes(_fPractice.toLowerCase());
            });
        }

        // Activity filter
        if (_fActivity === "has_jobs" || _fActivity === "active") {
            data = data.filter(f => f.has_activity || f.active_jobs > 0);
        } else if (_fActivity === "has_pipeline") {
            data = data.filter(f => f.pipeline_count > 0 || f.has_activity);
        }

        // Sort
        data.sort((a, b) => {
            let av, bv;
            if (_sortCol === "total_attorneys") {
                av = parseInt(String(a.total_attorneys || 0).replace(/[^\d]/g, "")) || 0;
                bv = parseInt(String(b.total_attorneys || 0).replace(/[^\d]/g, "")) || 0;
            } else if (_sortCol === "ppp") {
                av = parseFloat(String(a.ppp || 0).replace(/[^\d.]/g, "")) || 0;
                bv = parseFloat(String(b.ppp || 0).replace(/[^\d.]/g, "")) || 0;
            } else if (_sortCol === "client_status") {
                const ord = { "Active Client": 0, "Prospect": 1, "Past Client": 2, "Reference Only": 3 };
                av = ord[a.client_status || "Reference Only"] ?? 3;
                bv = ord[b.client_status || "Reference Only"] ?? 3;
            } else if (_sortCol === "active_jobs") {
                av = a.active_jobs || 0; bv = b.active_jobs || 0;
            } else if (_sortCol === "pipeline") {
                av = a.pipeline_count || 0; bv = b.pipeline_count || 0;
            } else {
                av = String(a[_sortCol] || "").toLowerCase();
                bv = String(b[_sortCol] || "").toLowerCase();
            }
            if (av < bv) return _sortDir === "asc" ? -1 : 1;
            if (av > bv) return _sortDir === "asc" ? 1 : -1;
            return 0;
        });

        _filtered = data;
        _page = 1;
        renderTablePage();
        renderPagination();
        updateFilterBadge();

        const countEl = $("#firms-count");
        if (countEl) countEl.textContent = `${data.length.toLocaleString()} firms`;
    }

    function renderTablePage() {
        const tbody = $("#firms-table-body");
        const empty = $("#firms-table-empty");
        if (!tbody) return;

        const start = (_page - 1) * PAGE_SIZE;
        const slice = _filtered.slice(start, start + PAGE_SIZE);

        if (!slice.length) {
            tbody.innerHTML = "";
            if (empty) empty.style.display = "block";
            return;
        }
        if (empty) empty.style.display = "none";

        tbody.innerHTML = slice.map(f => buildTableRow(f)).join("");

        // Wire clicks
        tbody.querySelectorAll(".firms-td-name").forEach(td => {
            td.addEventListener("click", () => showFirmDetail(td.dataset.fpid));
        });
        tbody.querySelectorAll(".ftbl-btn").forEach(btn => {
            btn.addEventListener("click", () => showFirmDetail(btn.dataset.fpid));
        });
        tbody.querySelectorAll(".ftbl-dots").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                openCtxMenu(e, btn.dataset.name, btn.dataset.fpid, btn.dataset.status, "table");
            });
        });
    }

    function buildTableRow(f) {
        const isCustom = f.source === "custom";
        const fpId = isCustom ? `custom_${f.id}` : (f.fp_id || "");
        const status = f.client_status || "Reference Only";
        const isPinned = f.pinned;

        const areas = [];
        if (isCustom && f.practice_areas) {
            f.practice_areas.split(/,|;/).slice(0, 3).forEach(a => { if (a.trim()) areas.push(a.trim()); });
        } else {
            if (f.top1) areas.push(f.top1.split(":")[0].trim());
            if (f.top2) areas.push(f.top2.split(":")[0].trim());
            if (f.top3) areas.push(f.top3.split(":")[0].trim());
        }

        const officeStr = isCustom ? (f.office_locations || "") : (f.offices || "");
        const officeCount = officeStr.split(/;|,/).filter(s => s.trim()).length || (officeStr ? 1 : 0);

        const jobs = f.active_jobs || 0;
        const pipe = f.pipeline_count || 0;

        return `<tr>
            <td class="firms-td firms-td-name" data-fpid="${esc(fpId)}">
                ${isPinned ? '<span class="firms-td-pinstar">★</span>' : ""}
                ${esc(f.name)}
            </td>
            <td class="firms-td">${statusBadgeHtml(status)}</td>
            <td class="firms-td firms-td-num${f.total_attorneys ? ' has-data' : ''}">
                ${fmtNum(f.total_attorneys)}
            </td>
            <td class="firms-td firms-td-ppp">${fmtPPP(f.ppp)}</td>
            <td class="firms-td firms-td-offices">${officeCount || "—"}</td>
            <td class="firms-td firms-td-areas">${areas.join(", ") || "—"}</td>
            <td class="firms-td firms-td-num${jobs ? ' has-data' : ''}">
                ${jobs || "—"}
            </td>
            <td class="firms-td firms-td-num${pipe ? ' has-data' : ''}">
                ${pipe || "—"}
            </td>
            <td class="firms-td firms-td-actions">
                <button class="ftbl-btn" data-fpid="${esc(fpId)}">View</button>
                <button class="ftbl-dots" data-name="${esc(f.name)}" data-fpid="${esc(fpId)}" data-status="${esc(status)}" title="More">⋯</button>
            </td>
        </tr>`;
    }

    function renderPagination() {
        const el = $("#firms-pagination");
        if (!el) return;
        const total = _filtered.length;
        const totalPages = Math.ceil(total / PAGE_SIZE);
        if (totalPages <= 1 && total <= PAGE_SIZE) {
            el.innerHTML = "";
            return;
        }
        const start = (_page - 1) * PAGE_SIZE + 1;
        const end = Math.min(_page * PAGE_SIZE, total);

        // Build page buttons (show window of 5)
        let pageButtons = "";
        const winStart = Math.max(1, _page - 2);
        const winEnd = Math.min(totalPages, winStart + 4);
        for (let p = winStart; p <= winEnd; p++) {
            pageButtons += `<button class="firms-page-btn${p === _page ? ' active' : ''}" data-page="${p}">${p}</button>`;
        }

        el.innerHTML = `
            <span class="firms-page-info">Showing ${start}–${end} of ${total.toLocaleString()} firms</span>
            <div class="firms-page-btns">
                <button class="firms-page-btn" data-page="1" ${_page === 1 ? 'disabled' : ''}>«</button>
                <button class="firms-page-btn" data-page="${_page - 1}" ${_page === 1 ? 'disabled' : ''}>‹</button>
                ${pageButtons}
                <button class="firms-page-btn" data-page="${_page + 1}" ${_page === totalPages ? 'disabled' : ''}>›</button>
                <button class="firms-page-btn" data-page="${totalPages}" ${_page === totalPages ? 'disabled' : ''}>»</button>
            </div>`;

        el.querySelectorAll(".firms-page-btn[data-page]").forEach(btn => {
            btn.addEventListener("click", () => {
                const p = parseInt(btn.dataset.page);
                if (!isNaN(p) && p >= 1 && p <= totalPages) {
                    _page = p;
                    renderTablePage();
                    renderPagination();
                    // Scroll to table
                    const table = $("#firms-db-section");
                    if (table) table.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
        });
    }

    function updateFilterBadge() {
        const resetBtn = $("#firms-filter-reset");
        if (!resetBtn) return;
        const hasFilter = _fStatus || _fSize || _fPractice || _fActivity;
        resetBtn.style.display = hasFilter ? "inline-flex" : "none";
    }

    // ── SORT HEADERS ──────────────────────────────────────────────────────
    function initTableSort() {
        $$(".firms-th[data-col]").forEach(th => {
            th.addEventListener("click", () => {
                const col = th.dataset.col;
                if (_sortCol === col) {
                    _sortDir = _sortDir === "asc" ? "desc" : "asc";
                } else {
                    _sortCol = col;
                    _sortDir = "asc";
                }
                $$(".firms-th").forEach(t => { t.classList.remove("sort-asc", "sort-desc"); });
                th.classList.add(_sortDir === "asc" ? "sort-asc" : "sort-desc");
                applyFiltersAndRender();
            });
        });
    }

    // ── SEARCH + FILTERS (wire events) ───────────────────────────────────
    function initSearchAndFilters() {
        // Text search
        const searchInput = $("#firms-search");
        const clearBtn = $("#firms-search-clear");
        if (searchInput) {
            let debounce;
            searchInput.addEventListener("input", () => {
                clearTimeout(debounce);
                debounce = setTimeout(() => {
                    _fSearch = searchInput.value.trim();
                    if (clearBtn) clearBtn.style.display = _fSearch ? "block" : "none";
                    if (_aiSearchActive) return;
                    applyFiltersAndRender();
                }, 200);
            });
            searchInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter" && _aiSearchActive) {
                    e.preventDefault();
                    if (searchInput.value.trim()) doAiSearch(searchInput.value.trim());
                }
            });
        }
        if (clearBtn) {
            clearBtn.addEventListener("click", () => {
                if (searchInput) searchInput.value = "";
                _fSearch = "";
                clearBtn.style.display = "none";
                applyFiltersAndRender();
            });
        }

        // AI toggle
        const aiBtn = $("#btn-ai-firm-search");
        if (aiBtn) {
            aiBtn.addEventListener("click", () => {
                _aiSearchActive = !_aiSearchActive;
                aiBtn.classList.toggle("active", _aiSearchActive);
                if (searchInput) {
                    searchInput.placeholder = _aiSearchActive
                        ? "Describe the firms you're looking for…"
                        : "Search firms by name, location, or practice area…";
                }
            });
        }

        // Dropdown filters
        const filterMap = [
            ["filter-status", v => _fStatus = v],
            ["filter-size", v => _fSize = v],
            ["filter-practice", v => _fPractice = v],
            ["filter-activity", v => _fActivity = v],
        ];
        filterMap.forEach(([id, setter]) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener("change", () => { setter(el.value); applyFiltersAndRender(); });
        });

        // Reset filters
        const resetBtn = $("#firms-filter-reset");
        if (resetBtn) {
            resetBtn.addEventListener("click", () => {
                _fStatus = _fSize = _fPractice = _fActivity = "";
                ["filter-status","filter-size","filter-practice","filter-activity"].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.value = "";
                });
                applyFiltersAndRender();
            });
        }

        // Source filter
        const sfEl = document.getElementById("firms-source-filter");
        if (sfEl) {
            sfEl.addEventListener("sourceFilterChange", (e) => {
                _fSource = e.detail.source;
                applyFiltersAndRender();
            });
            sfEl.querySelectorAll(".source-filter-btn").forEach(btn => {
                btn.addEventListener("click", () => {
                    sfEl.querySelectorAll(".source-filter-btn").forEach(b => b.classList.remove("active"));
                    btn.classList.add("active");
                    _fSource = btn.dataset.src;
                    applyFiltersAndRender();
                });
            });
        }

        // My clients sort
        const mcSortEl = $("#my-clients-sort");
        if (mcSortEl) {
            mcSortEl.addEventListener("change", () => {
                _mcSort = mcSortEl.value;
                renderMyClients();
            });
        }
    }

    // ── AI SEARCH ─────────────────────────────────────────────────────────
    function doAiSearch(query) {
        const tbody = $("#firms-table-body");
        if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="padding:20px;text-align:center;color:var(--gray)">AI searching…</td></tr>`;
        fetch("/api/firms/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="padding:20px;text-align:center;color:#dc2626">${esc(data.error)}</td></tr>`;
                return;
            }
            _filtered = data.firms || [];
            _page = 1;
            const countEl = $("#firms-count");
            if (countEl) countEl.textContent = `${_filtered.length} firms found`;
            renderTablePage();
            renderPagination();
        })
        .catch(() => {
            if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="padding:20px;text-align:center;color:#dc2626">AI search failed.</td></tr>`;
        });
    }

    // ── CONTEXT MENU ──────────────────────────────────────────────────────
    let _ctxMenu = null;

    function openCtxMenu(e, firmName, fpId, currentStatus, source) {
        closeCtxMenu();
        const menu = document.createElement("div");
        menu.className = "firms-ctx-menu";

        const statuses = ["Active Client", "Prospect", "Past Client", "Reference Only"];
        const statusItems = statuses
            .filter(s => s !== currentStatus)
            .map(s => `<button class="firms-ctx-item" data-action="status" data-val="${esc(s)}">Mark as ${esc(s)}</button>`)
            .join("");

        const inMyClients = (currentStatus === "Active Client" || currentStatus === "Prospect");

        menu.innerHTML = `
            ${statusItems}
            <hr class="firms-ctx-sep">
            <button class="firms-ctx-item" data-action="view">View Profile</button>
            <button class="firms-ctx-item" data-action="job">+ Add Job</button>
            <button class="firms-ctx-item" data-action="task">+ Add Task</button>
            <button class="firms-ctx-item" data-action="pitch">Generate Firm Pitch</button>
            ${inMyClients ? '<hr class="firms-ctx-sep"><button class="firms-ctx-item danger" data-action="remove">Remove from My Clients</button>' : ""}`;

        document.body.appendChild(menu);
        _ctxMenu = menu;

        // Position
        const rect = e.target.getBoundingClientRect();
        let top = rect.bottom + 4;
        let left = rect.left;
        if (left + 180 > window.innerWidth) left = window.innerWidth - 184;
        if (top + 200 > window.innerHeight) top = rect.top - menu.offsetHeight - 4;
        menu.style.top = top + "px";
        menu.style.left = left + "px";

        // Wire
        menu.querySelectorAll(".firms-ctx-item").forEach(item => {
            item.addEventListener("click", (ev) => {
                ev.stopPropagation();
                const action = item.dataset.action;
                if (action === "status") {
                    updateFirmStatus(firmName, fpId, item.dataset.val);
                } else if (action === "view") {
                    showFirmDetail(fpId);
                } else if (action === "job") {
                    quickCreateJob(firmName);
                } else if (action === "task") {
                    quickCreateTask(firmName, fpId);
                } else if (action === "pitch") {
                    openFirmPitch(firmName, fpId);
                } else if (action === "remove") {
                    updateFirmStatus(firmName, fpId, "Reference Only");
                }
                closeCtxMenu();
            });
        });

        // Close on outside click
        setTimeout(() => {
            document.addEventListener("click", closeCtxMenu, { once: true });
        }, 0);
    }

    function closeCtxMenu() {
        if (_ctxMenu) { _ctxMenu.remove(); _ctxMenu = null; }
    }

    // ── STATUS UPDATE ─────────────────────────────────────────────────────
    function updateFirmStatus(firmName, fpId, newStatus, extraData = {}) {
        const cleanId = (fpId || "").replace("custom_", "");
        fetch(`/api/firms/${encodeURIComponent(cleanId || firmName)}/status`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ firm_name: firmName, client_status: newStatus, ...extraData }),
        })
        .then(r => {
            if (!r.ok) return r.json().then(d => { throw new Error(d.error || "HTTP " + r.status); });
            return r.json();
        })
        .then(data => {
            if (data && data.error) throw new Error(data.error);
            // Update local cache so the badge changes immediately
            const f = _firmsCache.find(x => x.name === firmName);
            if (f) f.client_status = newStatus;
            // Also patch any AI-search results that are separate objects
            const fFiltered = _filtered.find(x => x.name === firmName);
            if (fFiltered) fFiltered.client_status = newStatus;
            applyFiltersAndRender();
            showToast(`${firmName} marked as ${newStatus}`);
            reloadMyClients();
        })
        .catch(err => showToast("Failed to update status: " + (err.message || "unknown error"), "error"));
    }

    function togglePin(firmName, fpId, currentlyPinned) {
        const newPinned = !currentlyPinned;
        const cleanId = (fpId || "").replace("custom_", "");
        fetch(`/api/firms/${encodeURIComponent(cleanId || firmName)}/pin`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ firm_name: firmName, pinned: newPinned }),
        })
        .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(() => {
            const f = _firmsCache.find(x => x.name === firmName);
            if (f) f.pinned = newPinned;
            applyFiltersAndRender();
            reloadMyClients();
        })
        .catch(err => showToast("Failed to pin firm", "error"));
    }

    function reloadMyClients() {
        fetch("/api/firms/my-clients")
            .then(r => r.json())
            .then(data => {
                _myClients = data.firms || [];
                renderMyClients();
            });
    }

    // ── FIRM DETAIL ───────────────────────────────────────────────────────
    function showFirmDetail(fpId) {
        if (!fpId) return;
        const listView = $("#firms-list-view");
        const detail = $("#firm-detail");
        if (!detail) return;
        if (listView) listView.style.display = "none";
        detail.style.display = "block";
        detail.innerHTML = '<p class="no-data" style="padding:24px">Loading…</p>';

        const endpoint = String(fpId).startsWith("custom_")
            ? `/api/custom/firms/${fpId.replace("custom_", "")}`
            : `/api/firms/${encodeURIComponent(fpId)}`;

        fetch(endpoint)
            .then(r => r.json())
            .then(data => {
                const firm = data.firm;
                if (!firm) { detail.innerHTML = `<p class="no-data" style="padding:24px">Firm not found.</p>`; return; }
                renderFirmDetail(firm);
            })
            .catch(() => { detail.innerHTML = `<p class="no-data" style="padding:24px">Failed to load firm.</p>`; });
    }

    function renderFirmDetail(firm) {
        const detail = $("#firm-detail");
        const totalAtty = firm.total_attorneys || "—";
        const ppp = firm.ppp ? fmtPPP(firm.ppp) : "—";
        const offices = (firm.offices || "").split(";").map(s => s.trim()).filter(Boolean);
        const website = firm.website || "";
        const areas = firm.practice_areas || {};
        const sortedAreas = Object.entries(areas).sort((a, b) => b[1] - a[1]);
        const officePills = offices.map(o => `<span class="firm-area-pill">${esc(o)}</span>`).join("");

        const status = firm.client_status || "Reference Only";
        const isReference = status === "Reference Only" || status === "Past Client";

        // Notes
        const notes = firm.notes || [];
        let notesHtml = notes.map(n =>
            `<div class="firm-note" data-id="${n.id}">
                <div class="firm-note-text">${esc(n.note)}</div>
                <div class="firm-note-meta">${esc(n.created_by || "Admin")} · ${n.created_at || ""}
                    <button class="firm-note-delete" data-id="${n.id}">&times;</button>
                </div>
            </div>`).join("") || '<p class="no-data" style="padding:8px">No notes yet.</p>';

        // Contacts
        const contacts = firm.contacts || [];
        let contactsHtml = contacts.map(c =>
            `<div class="firm-contact" data-id="${c.id}">
                <div class="firm-contact-name">${esc(c.name)}${c.title ? ` <span class="firm-contact-title">${esc(c.title)}</span>` : ""}</div>
                <div class="firm-contact-info">
                    ${c.email ? `<span>${esc(c.email)}</span>` : ""}
                    ${c.phone ? `<span>${esc(c.phone)}</span>` : ""}
                    <button class="firm-contact-delete" data-id="${c.id}">&times;</button>
                </div>
            </div>`).join("") || '<p class="no-data" style="padding:8px">No contacts yet.</p>';

        detail.innerHTML = `
            <button class="btn-back firm-back" id="firm-back">← Back to Firms</button>
            <div class="firm-detail-header">
                <div>
                    <h2 class="firm-detail-name">${esc(firm.name)}</h2>
                    <div class="firm-detail-meta">
                        ${esc(totalAtty)} attorneys · PPP ${esc(ppp)}
                        ${website ? ` · <a href="${esc(website)}" target="_blank" class="firm-detail-website">${esc(website)}</a>` : ""}
                    </div>
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                    ${isReference ? `<button class="firm-mark-active-btn" id="firm-mark-active-btn">⭐ Mark as Active Client</button>` : ""}
                    <button class="btn-primary btn-sm" id="firm-pitch-btn">📄 Create Firm Pitch</button>
                </div>
            </div>

            <!-- CRM Header -->
            <div class="firm-detail-crm" id="firm-detail-crm">
                <div class="firm-crm-field">
                    <span class="firm-crm-label">Client Status</span>
                    <select class="firm-crm-select" id="crm-status">
                        <option${status==="Active Client"?" selected":""}>Active Client</option>
                        <option${status==="Prospect"?" selected":""}>Prospect</option>
                        <option${status==="Past Client"?" selected":""}>Past Client</option>
                        <option${status==="Reference Only"?" selected":""}>Reference Only</option>
                    </select>
                </div>
                <div class="firm-crm-field">
                    <span class="firm-crm-label">Priority</span>
                    <select class="firm-crm-select" id="crm-priority">
                        <option${(firm.priority||"Normal")==="High"?" selected":""}>High</option>
                        <option${(firm.priority||"Normal")==="Normal"?" selected":""}>Normal</option>
                        <option${(firm.priority||"Normal")==="Low"?" selected":""}>Low</option>
                    </select>
                </div>
                <div class="firm-crm-field">
                    <span class="firm-crm-label">Owner</span>
                    <input class="firm-crm-input" id="crm-owner" type="text" value="${esc(firm.owner||"")}" placeholder="Your name">
                </div>
                <div class="firm-crm-field">
                    <span class="firm-crm-label">Last Contact</span>
                    <input class="firm-crm-input" id="crm-last-contact" type="date" value="${esc(firm.last_contact_date||"")}">
                </div>
                <div class="firm-crm-field">
                    <span class="firm-crm-label">Next Follow-up</span>
                    <input class="firm-crm-input" id="crm-followup" type="date" value="${esc(firm.next_follow_up||"")}">
                </div>
                <button class="firm-crm-save-btn" id="crm-save-btn">Save</button>
            </div>

            <!-- Tabs -->
            <div class="firm-tabs">
                <button class="firm-tab active" data-panel="firm-overview">Overview</button>
                <button class="firm-tab" data-panel="firm-jobs-panel">Jobs</button>
                <button class="firm-tab" data-panel="firm-top-candidates">Top Candidates</button>
                <button class="firm-tab" data-panel="firm-pipeline-panel">Pipeline</button>
                <button class="firm-tab" data-panel="firm-relationship-panel">Relationship</button>
                <button class="firm-tab" data-panel="firm-notes-panel">Notes & Contacts</button>
            </div>

            <!-- Overview -->
            <div class="firm-panel active" id="firm-overview">
                <div class="firm-overview-grid">
                    <div class="firm-overview-section">
                        <h3>Practice Areas</h3>
                        <div class="firm-chart">${buildPieChart(sortedAreas)}</div>
                    </div>
                    <div class="firm-overview-section">
                        <h3>Offices (${offices.length})</h3>
                        <div class="firm-offices">${officePills || '<p class="no-data">No office data</p>'}</div>
                        <h3 style="margin-top:20px">Key Stats</h3>
                        <div class="firm-stats-grid">
                            <div class="firm-stat"><div class="firm-stat-value">${esc(firm.partners||"—")}</div><div class="firm-stat-label">Partners</div></div>
                            <div class="firm-stat"><div class="firm-stat-value">${esc(firm.counsel||"—")}</div><div class="firm-stat-label">Counsel</div></div>
                            <div class="firm-stat"><div class="firm-stat-value">${esc(firm.associates||"—")}</div><div class="firm-stat-label">Associates</div></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Jobs (lazy) -->
            <div class="firm-panel" id="firm-jobs-panel" style="display:none">
                <p class="no-data" style="padding:12px">Loading jobs…</p>
            </div>

            <!-- Top Candidates (lazy) -->
            <div class="firm-panel" id="firm-top-candidates" style="display:none">
                <p class="no-data" style="padding:12px">Loading top candidates…</p>
            </div>

            <!-- Pipeline (lazy) -->
            <div class="firm-panel" id="firm-pipeline-panel" style="display:none">
                <p class="no-data" style="padding:12px">Loading pipeline…</p>
            </div>

            <!-- Relationship Timeline (lazy) -->
            <div class="firm-panel" id="firm-relationship-panel" style="display:none">
                <p class="no-data" style="padding:12px">Loading relationship history…</p>
            </div>

            <!-- Notes & Contacts -->
            <div class="firm-panel" id="firm-notes-panel" style="display:none">
                <div class="firm-overview-grid">
                    <div class="firm-overview-section">
                        <h3>Notes</h3>
                        <div id="firm-notes-list">${notesHtml}</div>
                        <div class="firm-note-form">
                            <textarea id="firm-note-input" rows="2" placeholder="Add a note…"></textarea>
                            <button class="btn-primary btn-sm" id="firm-note-add">Add Note</button>
                        </div>
                    </div>
                    <div class="firm-overview-section">
                        <h3>Contacts</h3>
                        <div id="firm-contacts-list">${contactsHtml}</div>
                        <div class="firm-contact-form">
                            <input type="text" id="fc-name" placeholder="Name *" class="firm-contact-input">
                            <input type="text" id="fc-title" placeholder="Title" class="firm-contact-input">
                            <input type="text" id="fc-email" placeholder="Email" class="firm-contact-input">
                            <input type="text" id="fc-phone" placeholder="Phone" class="firm-contact-input">
                            <button class="btn-primary btn-sm" id="firm-contact-add">Add Contact</button>
                        </div>
                    </div>
                </div>
            </div>`;

        const lazyLoaded = {};

        // Back button
        detail.querySelector("#firm-back").addEventListener("click", () => {
            detail.style.display = "none";
            const lv = $("#firms-list-view");
            if (lv) lv.style.display = "";
            // Refresh my clients in case status was changed
            reloadMyClients();
            fetch("/api/firms/recently-viewed").then(r=>r.json()).then(d=>renderRecentlyViewed(d.firms||[]));
        });

        // Mark as Active Client button
        const markBtn = detail.querySelector("#firm-mark-active-btn");
        if (markBtn) {
            markBtn.addEventListener("click", () => {
                fetch(`/api/firms/${encodeURIComponent(firm.fp_id||firm.name)}/mark-active`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ firm_name: firm.name }),
                }).then(() => {
                    showToast(`${firm.name} is now an Active Client`);
                    markBtn.remove();
                    const statusSel = detail.querySelector("#crm-status");
                    if (statusSel) statusSel.value = "Active Client";
                    reloadMyClients();
                });
            });
        }

        // CRM Save
        detail.querySelector("#crm-save-btn").addEventListener("click", () => {
            const newStatus = detail.querySelector("#crm-status").value;
            const payload = {
                firm_name: firm.name,
                client_status: newStatus,
                priority: detail.querySelector("#crm-priority").value,
                owner: detail.querySelector("#crm-owner").value.trim(),
                last_contact_date: detail.querySelector("#crm-last-contact").value,
                next_follow_up: detail.querySelector("#crm-followup").value,
            };
            fetch(`/api/firms/${encodeURIComponent(firm.fp_id||firm.name)}/status`, {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            })
            .then(r => {
                if (!r.ok) return r.json().then(d => { throw new Error(d.error || "HTTP " + r.status); });
                return r.json();
            })
            .then(data => {
                if (data && data.error) throw new Error(data.error);
                showToast("CRM settings saved");
                const f = _firmsCache.find(x => x.name === firm.name);
                if (f) { f.client_status = newStatus; f.priority = payload.priority; }
                reloadMyClients();
            })
            .catch(err => showToast("Failed to save: " + (err.message || "unknown error"), "error"));
        });

        // Firm pitch button
        const fpBtn = detail.querySelector("#firm-pitch-btn");
        if (fpBtn) {
            fpBtn.addEventListener("click", () => {
                if (window.JAIDE && window.JAIDE.openFirmPitchModal) {
                    window.JAIDE.openFirmPitchModal({
                        firm: { id: firm.fp_id || "", name: firm.name,
                            meta: (firm.total_attorneys ? firm.total_attorneys + " attorneys" : "") +
                                  (firm.ppp ? " · PPP " + fmtPPP(firm.ppp) : "") }
                    });
                }
            });
        }

        // Tabs + lazy loading
        detail.querySelectorAll(".firm-tab").forEach(tab => {
            tab.addEventListener("click", () => {
                detail.querySelectorAll(".firm-tab").forEach(t => t.classList.remove("active"));
                detail.querySelectorAll(".firm-panel").forEach(p => { p.style.display="none"; p.classList.remove("active"); });
                tab.classList.add("active");
                const panelId = tab.dataset.panel;
                const panel = detail.querySelector("#" + panelId);
                if (panel) { panel.style.display="block"; panel.classList.add("active"); }
                if (panelId === "firm-jobs-panel" && !lazyLoaded[panelId]) {
                    lazyLoaded[panelId] = true; loadFirmJobs(firm.fp_id, panel);
                }
                if (panelId === "firm-top-candidates" && !lazyLoaded[panelId]) {
                    lazyLoaded[panelId] = true; loadTopCandidates(firm.fp_id, firm.name, panel);
                }
                if (panelId === "firm-pipeline-panel" && !lazyLoaded[panelId]) {
                    lazyLoaded[panelId] = true; loadFirmPipeline(firm.fp_id, panel);
                }
                if (panelId === "firm-relationship-panel" && !lazyLoaded[panelId]) {
                    lazyLoaded[panelId] = true; loadRelationshipTimeline(firm.fp_id, panel);
                }
            });
        });

        // Notes
        detail.querySelector("#firm-note-add").addEventListener("click", () => {
            const input = detail.querySelector("#firm-note-input");
            const note = input.value.trim();
            if (!note) return;
            fetch(`/api/firms/${firm.fp_id}/notes`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ note }),
            }).then(() => { input.value = ""; showFirmDetail(firm.fp_id);
                setTimeout(() => detail.querySelector('[data-panel="firm-notes-panel"]')?.click(), 80);
                // Update last_contact_date
                const today = new Date().toISOString().slice(0,10);
                fetch(`/api/firms/${encodeURIComponent(firm.fp_id||firm.name)}/status`, {
                    method: "PUT", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ firm_name: firm.name, last_contact_date: today }),
                });
            });
        });
        detail.querySelectorAll(".firm-note-delete").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                fetch(`/api/firms/${firm.fp_id}/notes/${btn.dataset.id}`, { method: "DELETE" })
                    .then(() => { showFirmDetail(firm.fp_id);
                        setTimeout(() => detail.querySelector('[data-panel="firm-notes-panel"]')?.click(), 80);
                    });
            });
        });

        // Contacts
        detail.querySelector("#firm-contact-add").addEventListener("click", () => {
            const name = detail.querySelector("#fc-name").value.trim();
            if (!name) return;
            fetch(`/api/firms/${firm.fp_id}/contacts`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name, title: detail.querySelector("#fc-title").value.trim(),
                    email: detail.querySelector("#fc-email").value.trim(),
                    phone: detail.querySelector("#fc-phone").value.trim(),
                }),
            }).then(() => { showFirmDetail(firm.fp_id);
                setTimeout(() => detail.querySelector('[data-panel="firm-notes-panel"]')?.click(), 80);
            });
        });
        detail.querySelectorAll(".firm-contact-delete").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                fetch(`/api/firms/${firm.fp_id}/contacts/${btn.dataset.id}`, { method: "DELETE" })
                    .then(() => { showFirmDetail(firm.fp_id);
                        setTimeout(() => detail.querySelector('[data-panel="firm-notes-panel"]')?.click(), 80);
                    });
            });
        });
    }

    // ── LAZY-LOAD PANELS ─────────────────────────────────────────────────
    function loadFirmJobs(fpId, panel) {
        fetch(`/api/firms/${fpId}/jobs`).then(r => r.json()).then(data => {
            const jobs = data.jobs || [];
            if (!jobs.length) { panel.innerHTML = '<p class="no-data" style="padding:12px">No jobs found.</p>'; return; }
            panel.innerHTML = `<div class="firm-jobs-list">
                ${jobs.map(j => `<div class="firm-job-row">
                    <div class="firm-job-title"><a class="firm-entity-link firm-job-link" data-job-id="${esc(j.id||"")}">${esc(j.job_title)}</a></div>
                    <div class="firm-job-meta">
                        ${j.job_location ? `<span>${esc(j.job_location)}</span>` : ""}
                        ${j.practice_areas ? `<span>${esc(j.practice_areas)}</span>` : ""}
                        <span class="firm-job-status firm-job-status-${(j.status||"").toLowerCase().replace(/\s+/g,"-")}">${esc(j.status||"Unknown")}</span>
                    </div>
                </div>`).join("")}
            </div>`;
            panel.querySelectorAll(".firm-job-link").forEach(link => {
                link.addEventListener("click", (e) => {
                    e.preventDefault();
                    if (link.dataset.jobId && window.JAIDE?.navigateTo) {
                        window.JAIDE.navigateTo("dashboard");
                        setTimeout(() => window.JAIDE.loadPipelineForJob?.(parseInt(link.dataset.jobId)), 150);
                    }
                });
            });
        }).catch(() => { panel.innerHTML = '<p class="no-data" style="padding:12px">Failed to load jobs.</p>'; });
    }

    function loadFirmPipeline(fpId, panel) {
        fetch(`/api/firms/${fpId}/pipeline`).then(r => r.json()).then(data => {
            const cands = data.candidates || [];
            if (!cands.length) { panel.innerHTML = '<p class="no-data" style="padding:12px">No pipeline candidates.</p>'; return; }
            panel.innerHTML = `<div class="firm-pipeline-list">
                ${cands.map(c => `<div class="firm-pipeline-row">
                    <div class="firm-pipeline-name"><a class="firm-entity-link firm-attorney-link" data-attorney-id="${esc(String(c.attorney_id||""))}">${esc(c.attorney_name)}</a></div>
                    <div class="firm-pipeline-meta">
                        <span class="firm-pipeline-stage firm-pipeline-stage-${(c.stage||"").toLowerCase().replace(/\s+/g,"-")}">${esc(c.stage)}</span>
                        ${c.job_title ? `<a class="firm-entity-link firm-pjob-link" data-job-id="${esc(String(c.job_id||""))}">${esc(c.job_title)}</a>` : ""}
                        ${c.attorney_firm ? `<span class="firm-pipeline-firm">${esc(c.attorney_firm)}</span>` : ""}
                    </div>
                </div>`).join("")}
            </div>`;
            panel.querySelectorAll(".firm-attorney-link").forEach(link => {
                link.addEventListener("click", (e) => { e.preventDefault(); openAttorneyById(link.dataset.attorneyId); });
            });
            panel.querySelectorAll(".firm-pjob-link").forEach(link => {
                link.addEventListener("click", (e) => {
                    e.preventDefault();
                    if (window.JAIDE?.navigateTo) {
                        window.JAIDE.navigateTo("dashboard");
                        setTimeout(() => window.JAIDE.loadPipelineForJob?.(parseInt(link.dataset.jobId)), 150);
                    }
                });
            });
        }).catch(() => { panel.innerHTML = '<p class="no-data" style="padding:12px">Failed to load pipeline.</p>'; });
    }

    function loadRelationshipTimeline(fpId, panel) {
        fetch(`/api/firms/${encodeURIComponent(fpId)}/relationship-timeline`)
            .then(r => r.json())
            .then(data => {
                const events = data.events || [];
                if (!events.length) {
                    panel.innerHTML = '<p class="no-data" style="padding:12px">No relationship history yet. Add notes, create jobs, or add candidates to start tracking.</p>';
                    return;
                }
                panel.innerHTML = `<div class="relationship-timeline">
                    ${events.map(ev => {
                        const statusPill = ev.status
                            ? `<span class="rt-status-pill ${ev.status.toLowerCase()==="completed"?"rt-status-completed":"rt-status-pending"}">${esc(ev.status)}</span>`
                            : "";
                        const dateStr = ev.date ? relDate(ev.date) : "";
                        return `<div class="rt-event rt-event-${esc(ev.type||"note")}">
                            <div class="rt-icon">${esc(ev.icon||"📝")}</div>
                            <div class="rt-body">
                                <div class="rt-text">${esc(ev.text||"")}${statusPill}</div>
                                ${dateStr ? `<div class="rt-meta">${dateStr}</div>` : ""}
                            </div>
                        </div>`;
                    }).join("")}
                </div>`;
            })
            .catch(() => { panel.innerHTML = '<p class="no-data" style="padding:12px">Failed to load timeline.</p>'; });
    }

    function loadTopCandidates(fpId, firmName, panel) {
        fetch(`/api/firms/${fpId}/top-candidates`).then(r => r.json()).then(data => {
            const candidates = data.candidates || [];
            const dna = data.dna;
            if (!candidates.length) {
                panel.innerHTML = `<p class="no-data" style="padding:12px">${esc(data.message||"No top candidates found.")}</p>`;
                return;
            }
            let dnaSummary = "";
            if (dna) {
                const schools = (dna.feeder_schools||[]).map(s=>`${esc(s.school)} (${Math.round(s.pct*100)}%)`).join(", ");
                const feeders = (dna.feeder_firms||[]).map(f=>`${esc(f.firm)} (${f.hires})`).join(", ");
                const areas = (dna.practice_areas||[]).map(a=>`${esc(a.area)} (${Math.round(a.pct*100)}%)`).join(", ");
                const cy = dna.class_year_range||{};
                dnaSummary = `<div class="tc-dna-summary">
                    <div class="tc-dna-header"><strong>Hiring DNA</strong><span class="tc-dna-meta">${dna.total_hires} hires analyzed</span></div>
                    <div class="tc-dna-pills">
                        ${schools?`<div class="tc-dna-row"><span class="tc-dna-label">Schools:</span> ${schools}</div>`:""}
                        ${feeders?`<div class="tc-dna-row"><span class="tc-dna-label">Feeder firms:</span> ${feeders}</div>`:""}
                        ${areas?`<div class="tc-dna-row"><span class="tc-dna-label">Practice areas:</span> ${areas}</div>`:""}
                        ${cy.min?`<div class="tc-dna-row"><span class="tc-dna-label">Class years:</span> ${cy.min}–${cy.max} (median ${cy.median})</div>`:""}
                    </div>
                </div>`;
            }
            const header = `<div class="tc-header">
                <div><h3 class="tc-title">Top 50 Candidates for ${esc(firmName)}</h3>
                <p class="tc-subtitle">Matched against hiring patterns</p></div>
                <div class="tc-controls">
                    <select class="tc-sort" id="tc-sort-select">
                        <option value="score">Best Match</option>
                        <option value="year-new">Class Year (newest)</option>
                        <option value="year-old">Class Year (oldest)</option>
                        <option value="firm">Firm Name (A–Z)</option>
                    </select>
                    <button class="tc-refresh-btn" id="tc-refresh">↻</button>
                </div>
            </div>`;
            panel.innerHTML = dnaSummary + header + '<div class="tc-list" id="tc-list"></div>';
            renderTopCandidateList(candidates, panel.querySelector("#tc-list"));
            const sortSel = panel.querySelector("#tc-sort-select");
            sortSel.addEventListener("change", () => {
                const sorted = [...candidates];
                if (sortSel.value==="year-new") sorted.sort((a,b)=>(parseInt(b.graduation_year)||0)-(parseInt(a.graduation_year)||0));
                else if (sortSel.value==="year-old") sorted.sort((a,b)=>(parseInt(a.graduation_year)||0)-(parseInt(b.graduation_year)||0));
                else if (sortSel.value==="firm") sorted.sort((a,b)=>(a.current_firm||"").localeCompare(b.current_firm||""));
                else sorted.sort((a,b)=>b.match_score-a.match_score);
                renderTopCandidateList(sorted, panel.querySelector("#tc-list"));
            });
            panel.querySelector("#tc-refresh").addEventListener("click", () => {
                panel.innerHTML = '<p class="no-data" style="padding:12px">Refreshing…</p>';
                fetch(`/api/firms/${fpId}/top-candidates/refresh`, { method: "POST" })
                    .then(() => loadTopCandidates(fpId, firmName, panel));
            });
        }).catch(() => { panel.innerHTML = '<p class="no-data" style="padding:12px">Failed to load candidates.</p>'; });
    }

    function renderTopCandidateList(candidates, container) {
        container.innerHTML = candidates.map((c) => {
            const scoreColor = c.match_score >= 80 ? "tc-score-green" : c.match_score >= 60 ? "tc-score-blue" : "tc-score-yellow";
            const reasons = (c.match_reasons || []).map(r => {
                let icon = "", cls = "tc-tag-default";
                if (r.includes("School")) { icon = "📚"; cls = "tc-tag-school"; }
                else if (r === "Boomerang") { icon = "🔄"; cls = "tc-tag-boom"; }
                else if (r.includes("Feeder Firm") || r.includes("Ex-Feeder")) { icon = "🏢"; cls = "tc-tag-firm"; }
                else if (r.includes("Practice")) { icon = "📋"; cls = "tc-tag-pa"; }
                else if (r.includes("Specialty")) { icon = "🎯"; cls = "tc-tag-spec"; }
                else if (r.includes("Location")) { icon = "📍"; cls = "tc-tag-loc"; }
                else if (r.includes("Class Year")) { icon = "🎓"; cls = "tc-tag-cy"; }
                return `<span class="tc-tag ${cls}">${icon} ${esc(r)}</span>`;
            }).join("");
            const specs = c.specialty ? c.specialty.split(",").slice(0,3).map(s=>`<span class="tc-spec-pill">${esc(s.trim())}</span>`).join("") : "";
            return `<div class="tc-card" data-attorney-id="${esc(c.id)}">
                <div class="tc-score ${scoreColor}">${c.match_score}</div>
                <div class="tc-card-body">
                    <div class="tc-card-name">${esc(c.name)}</div>
                    <div class="tc-card-meta">${esc(c.current_firm)} · ${esc(c.title)}</div>
                    <div class="tc-card-detail">
                        ${c.graduation_year ? "Class of " + esc(c.graduation_year) + " · " : ""}${esc(c.law_school)}
                        ${c.location ? " · " + esc(c.location) : ""}
                    </div>
                    <div class="tc-card-specs">${specs}</div>
                    <div class="tc-card-reasons">${reasons}</div>
                </div>
                <div class="tc-card-actions">
                    <button class="tc-action-btn tc-view-profile" data-id="${esc(c.id)}">Profile</button>
                    <button class="tc-action-btn tc-add-pipeline" data-id="${esc(c.id)}" data-name="${esc(c.name)}">+ Pipeline</button>
                </div>
            </div>`;
        }).join("");
        container.querySelectorAll(".tc-view-profile").forEach(btn => {
            btn.addEventListener("click", (e) => { e.stopPropagation(); openAttorneyById(btn.dataset.id); });
        });
        container.querySelectorAll(".tc-card").forEach(card => {
            card.addEventListener("click", () => openAttorneyById(card.dataset.attorneyId));
        });
    }

    // ── PIE CHART ─────────────────────────────────────────────────────────
    function buildPieChart(sortedAreas) {
        if (!sortedAreas.length) return '<p class="no-data">No practice area data</p>';
        const total = sortedAreas.reduce((s, a) => s + a[1], 0);
        let cumPct = 0;
        const stops = sortedAreas.map(([, count], i) => {
            const pct = (count / total) * 100;
            const color = PIE_COLORS[i % PIE_COLORS.length];
            const stop = `${color} ${cumPct.toFixed(2)}% ${(cumPct + pct).toFixed(2)}%`;
            cumPct += pct;
            return stop;
        });
        const legend = sortedAreas.map(([name, count], i) => {
            const pct = ((count / total) * 100).toFixed(1);
            return `<div class="pie-legend-item">
                <span class="pie-legend-swatch" style="background:${PIE_COLORS[i%PIE_COLORS.length]}"></span>
                <span class="pie-legend-name">${esc(name)}</span>
                <span class="pie-legend-count">${count} (${pct}%)</span>
            </div>`;
        }).join("");
        return `<div class="pie-chart-container">
            <div class="pie-chart" style="background:conic-gradient(${stops.join(", ")})"></div>
            <div class="pie-legend">${legend}</div>
        </div>`;
    }

    // ── HELPERS ───────────────────────────────────────────────────────────
    function openAttorneyById(id) {
        fetch(`/api/attorneys/${encodeURIComponent(id)}`)
            .then(r => r.json())
            .then(data => { if (data.attorney && window.JAIDE?.openProfile) window.JAIDE.openProfile(data.attorney); });
    }

    function quickCreateJob(firmName) {
        if (window.JAIDE?.navigateTo) {
            window.JAIDE.navigateTo("jobs");
            setTimeout(() => {
                const btn = document.getElementById("btn-add-custom-job");
                if (btn) btn.click();
                setTimeout(() => {
                    const firmInput = document.getElementById("cj-firm-name");
                    if (firmInput) { firmInput.value = firmName; firmInput.dispatchEvent(new Event("input")); }
                }, 200);
            }, 150);
        }
    }

    function quickCreateTask(firmName, fpId) {
        if (window.JAIDE?.openTaskModal) {
            window.JAIDE.openTaskModal({ firm_name: firmName, firm_fp_id: fpId || "" });
        }
    }

    function openFirmPitch(firmName, fpId) {
        if (window.JAIDE?.openFirmPitchModal) {
            window.JAIDE.openFirmPitchModal({ firm: { id: fpId || "", name: firmName, meta: "" } });
        }
    }

    function showToast(msg, type = "success") {
        if (window.JAIDE?.showToast) { window.JAIDE.showToast(msg, type); return; }
        const t = document.createElement("div");
        t.style.cssText = "position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1e293b;color:white;padding:10px 20px;border-radius:8px;font-size:13px;z-index:9999;pointer-events:none";
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 2500);
    }

    // ── AUTO-DETECTION HOOKS ──────────────────────────────────────────────
    // When a job is created or candidate added to pipeline for a firm,
    // prompt the user to mark the firm as an Active Client
    window.addEventListener("customRecordSaved", (e) => {
        if (e.detail?.type === "firm") {
            _loaded = false;
            loadFirms();
        }
    });
    window.addEventListener("customRecordDeleted", (e) => {
        if (e.detail?.type === "firm") {
            _firmsCache = _firmsCache.filter(f => f.source !== "custom" || String(f.id) !== String(e.detail.id));
            applyFiltersAndRender();
        }
    });

    // Hook: prompt when a job is added to ATS for a firm not yet active
    window.addEventListener("jobCreatedForFirm", (e) => {
        const firmName = e.detail?.firm_name;
        const fpId = e.detail?.firm_fp_id || firmName;
        if (!firmName) return;
        const cached = _firmsCache.find(f => f.name === firmName);
        if (!cached || cached.client_status === "Active Client") return;
        showMarkActivePrompt(firmName, fpId);
    });

    // Hook: prompt when candidate added to pipeline for a firm
    window.addEventListener("candidateAddedToPipeline", (e) => {
        const firmName = e.detail?.employer_name;
        const fpId = e.detail?.firm_fp_id || firmName;
        if (!firmName) return;
        const cached = _firmsCache.find(f => f.name === firmName);
        if (!cached || cached.client_status === "Active Client") return;
        showMarkActivePrompt(firmName, fpId);
    });

    let _promptTimeout = null;
    function showMarkActivePrompt(firmName, fpId) {
        // Remove any existing prompt
        const existing = document.getElementById("firm-prompt-bar");
        if (existing) existing.remove();
        clearTimeout(_promptTimeout);

        const bar = document.createElement("div");
        bar.className = "firm-prompt-bar";
        bar.id = "firm-prompt-bar";
        bar.innerHTML = `
            <span class="firm-prompt-bar-text">Mark <strong>${esc(firmName)}</strong> as an Active Client?</span>
            <button class="firm-prompt-bar-yes" id="fpm-yes">Yes</button>
            <button class="firm-prompt-bar-no" id="fpm-no">Not now</button>`;
        document.body.appendChild(bar);

        bar.querySelector("#fpm-yes").addEventListener("click", () => {
            updateFirmStatus(firmName, fpId, "Active Client");
            bar.remove();
        });
        bar.querySelector("#fpm-no").addEventListener("click", () => bar.remove());

        _promptTimeout = setTimeout(() => bar.remove(), 10000);
    }

    // ── DASHBOARD FOLLOW-UP ALERT ─────────────────────────────────────────
    window.JAIDE.loadFirmFollowupAlert = function (container) {
        fetch("/api/firms/need-followup")
            .then(r => r.json())
            .then(data => {
                const count = data.count || 0;
                if (!count || !container) return;
                const alert = document.createElement("div");
                alert.className = "dash-followup-alert";
                alert.innerHTML = `
                    <span class="dash-followup-icon">⚠️</span>
                    <span class="dash-followup-text">
                        <strong>${count} active client${count !== 1 ? "s" : ""}</strong> with no activity in 7+ days.
                        <a class="dash-followup-link" id="followup-firms-link">View firms →</a>
                    </span>`;
                container.insertBefore(alert, container.firstChild);
                alert.querySelector("#followup-firms-link").addEventListener("click", () => {
                    if (window.JAIDE?.navigateTo) window.JAIDE.navigateTo("firms");
                });
                alert.addEventListener("click", () => {
                    if (window.JAIDE?.navigateTo) window.JAIDE.navigateTo("firms");
                });
            });
    };

    // ── NAVIGATE BY FIRM NAME (cross-module) ──────────────────────────────
    window.JAIDE.showFirmByName = function (firmName) {
        if (!firmName) return;
        const q = firmName.toLowerCase().trim();
        const match = _firmsCache.find(f => f.name.toLowerCase() === q);
        if (match) {
            if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("firms");
            setTimeout(() => showFirmDetail(match.fp_id || match.id), 100);
        } else {
            fetch(`/api/firms?search=${encodeURIComponent(firmName)}`)
                .then(r => r.json())
                .then(data => {
                    const firms = data.firms || [];
                    if (firms.length) {
                        if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("firms");
                        setTimeout(() => showFirmDetail(firms[0].fp_id || firms[0].id), 100);
                    }
                });
        }
    };

    // ── INIT ──────────────────────────────────────────────────────────────
    function init() {
        initTableSort();
        initSearchAndFilters();
    }

    // Run init when DOM is ready (this script loads at end of body)
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();
