/**
 * dashboard.js — JAIDE ATS Dashboard Command Center
 * Handles: Tasks, Worklists, Pipeline summary, Action Items, Quick Actions
 */
(function () {
    "use strict";

    // ── State ──────────────────────────────────────────────────────────────
    let _allTasks = [];
    let _allWorklists = [];
    let _pendingWorklistAttorney = null; // for add-to-worklist flow
    let _selectedWorklistColor = "#0059FF";
    let _myCandidates = [];   // raw data for client-side filter/sort
    let _myJobs = [];         // raw data for client-side filter
    let _candSortKey = "last_activity"; // default sort
    let _candSortDir = 1;     // 1 = desc (newest first), -1 = asc

    // ── Boot ───────────────────────────────────────────────────────────────
    function init() {
        _bindQuickActions();
        _bindTaskModal();
        _bindWorklistModal();
        _bindWorklistDetail();
        _bindAddToWorklist();
        _bindCandidateFilters();
        _bindJobFilters();
        // Re-load whenever navigateTo("dashboard") is called
        document.addEventListener("viewActivated", function (e) {
            if (e.detail === "dashboard") loadDashboardData();
        });
        // Also load immediately if dashboard is already active on page load
        var dashView = document.getElementById("view-dashboard");
        if (dashView && dashView.classList.contains("view-active")) {
            loadDashboardData();
        }
        // Expose globally for other modules
        window.JAIDE = window.JAIDE || {};
        window.JAIDE.openAddToWorklist = openAddToWorklist;
        window.JAIDE.openTaskModal = openTaskModal;
        window.JAIDE.loadDashboardData = loadDashboardData;
        window.JAIDE._makeAC = _makeAC;
    }

    // ── Data loading ──────────────────────────────────────────────────────
    function loadDashboardData() {
        Promise.all([
            fetch("/api/dashboard/stats").then(r => r.json()),
            fetch("/api/dashboard/action-items").then(r => r.json()),
            fetch("/api/tasks").then(r => r.json()),
            fetch("/api/worklists").then(r => r.json()),
            fetch("/api/dashboard/candidates").then(r => r.json()),
            fetch("/api/dashboard/jobs").then(r => r.json()),
        ]).then(function ([stats, items, tasks, worklists, candData, jobsData]) {
            _allTasks = tasks;
            _allWorklists = worklists;
            _myCandidates = candData.candidates || [];
            _myJobs = jobsData.jobs || [];
            _renderUnifiedActionItems(tasks, items);
            _renderWorklists(worklists);
            _renderMyCandidates();
            _renderMyJobs();
        }).catch(function (err) {
            console.warn("Dashboard load error:", err);
        });
    }

    // Load metrics for the Pipeline page
    function _loadPipelineMetrics() {
        fetch("/api/dashboard/stats")
            .then(r => r.json())
            .then(_renderMetrics)
            .catch(function() {});
    }

    // ── Metrics ──────────────────────────────────────────────────────────
    function _renderMetrics(stats) {
        _setText("metric-active-jobs", stats.active_jobs ?? "–");
        _setText("metric-pipeline", stats.total_pipeline ?? "–");
        _setText("metric-open-tasks", stats.open_tasks ?? "–");
        _setText("metric-pipeline-value", "$" + _fmt(stats.total_pipeline_value ?? 0));
        // interviews from stage_counts
        var sc = stats.stage_counts || {};
        var ivw = (sc["Interview 1"] || 0) + (sc["Interview 2"] || 0) + (sc["Final Interview"] || 0);
        _setText("metric-interviews", ivw);
        _setText("metric-placements", sc["Placed"] || 0);
        // overdue badge on tasks card
        if (stats.overdue_tasks > 0) {
            var card = document.getElementById("metric-card-tasks");
            if (card) {
                var badge = card.querySelector(".metric-overdue-badge");
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = "metric-overdue-badge dash-badge-count";
                    badge.style.cssText = "position:absolute;top:8px;right:8px;";
                    card.style.position = "relative";
                    card.appendChild(badge);
                }
                badge.textContent = stats.overdue_tasks + " overdue";
            }
        }
    }

    // ── My Candidates ────────────────────────────────────────────────────
    var _candStageFilter = "";
    var _jobsStatusFilter = "";

    var STAGE_GROUPS = {
        early: ["Identified", "Contacted", "Responded", "Phone Screen", "Submitted to Client"],
        interview: ["Interview 1", "Interview 2", "Final Interview", "Reference Check"],
        offer: ["Offer Extended", "Placed"],
        rejected: ["Rejected", "Withdrawn", "On Hold"],
    };

    function _stagePillClass(stage) {
        if (STAGE_GROUPS.offer.includes(stage)) return "stage-pill-offer";
        if (STAGE_GROUPS.interview.includes(stage)) return "stage-pill-interview";
        if (STAGE_GROUPS.rejected.includes(stage)) return "stage-pill-rejected";
        return "stage-pill-early";
    }

    function _timeAgo(dateStr) {
        if (!dateStr) return "–";
        var d = new Date(dateStr.replace(" ", "T"));
        var diff = Math.floor((Date.now() - d.getTime()) / 1000);
        if (diff < 60) return "just now";
        if (diff < 3600) return Math.floor(diff / 60) + "m ago";
        if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
        if (diff < 604800) return Math.floor(diff / 86400) + "d ago";
        return d.toLocaleDateString();
    }

    function _renderMyCandidates() {
        var el = document.getElementById("dash-my-candidates");
        if (!el) return;

        // Filter
        var data = _myCandidates.filter(function (c) {
            if (!_candStageFilter) return true;
            var grp = STAGE_GROUPS[_candStageFilter] || [];
            return grp.includes(c.stage);
        });

        // Sort
        var sk = _candSortKey;
        var sd = _candSortDir; // -1 = desc (most recent first for dates), 1 = asc
        data = data.slice().sort(function (a, b) {
            var av, bv;
            if (sk === "name") {
                av = (a.attorney_name || "").toLowerCase();
                bv = (b.attorney_name || "").toLowerCase();
                return sd * av.localeCompare(bv);
            }
            if (sk === "stage") {
                av = (a.stage || "").toLowerCase();
                bv = (b.stage || "").toLowerCase();
                return sd * av.localeCompare(bv);
            }
            if (sk === "days") {
                av = a.days_in_stage || 0;
                bv = b.days_in_stage || 0;
                return sd * (av - bv);
            }
            // default: last_activity (date desc = sd=-1)
            av = a.updated_at || a.added_at || "";
            bv = b.updated_at || b.added_at || "";
            return sd * (av > bv ? -1 : av < bv ? 1 : 0);
        });

        if (!data.length) {
            el.innerHTML = '<div class="dash-loading">No candidates in pipeline yet.</div>';
            return;
        }

        var colDefs = [
            { key: "name",          label: "Candidate" },
            { key: "firm",          label: "Current Firm", nosort: true },
            { key: "job",           label: "Job Title", nosort: true },
            { key: "client",        label: "Client Firm", nosort: true },
            { key: "stage",         label: "Stage" },
            { key: "days",          label: "Days in Stage" },
            { key: "last_activity", label: "Last Activity" },
            { key: "actions",       label: "", nosort: true },
        ];

        var thead = colDefs.map(function (col) {
            if (col.nosort) return '<th class="my-table-th">' + _esc(col.label) + '</th>';
            var active = _candSortKey === col.key;
            var dir = active ? (_candSortDir === -1 ? " ↓" : " ↑") : "";
            return '<th class="my-table-th my-table-sortable" data-sort-key="' + col.key + '">' + _esc(col.label) + dir + '</th>';
        }).join("");

        var rows = data.map(function (c) {
            var daysInStage = c.days_in_stage || 0;
            var daysClass = daysInStage >= 7 ? " days-stuck" : "";
            var pillCls = _stagePillClass(c.stage);
            var lastAct = _timeAgo(c.updated_at || c.added_at);
            return '<tr class="my-table-row">' +
                '<td class="my-table-td"><span class="cand-name-link" data-pid="' + c.id + '" data-aid="' + _esc(c.attorney_id) + '" data-src="' + _esc(c.attorney_source) + '">' + _esc(c.attorney_name || "—") + '</span></td>' +
                '<td class="my-table-td my-table-muted">' + _esc(c.attorney_firm || "—") + '</td>' +
                '<td class="my-table-td"><span class="cand-job-link" data-jid="' + (c.job_id || "") + '">' + _esc(c.job_title || "—") + '</span></td>' +
                '<td class="my-table-td"><span class="cand-firm-link" data-eid="' + (c.employer_id || "") + '">' + _esc(c.employer_name || "—") + '</span></td>' +
                '<td class="my-table-td"><span class="stage-pill ' + pillCls + '">' + _esc(c.stage) + '</span></td>' +
                '<td class="my-table-td' + daysClass + '">' + daysInStage + 'd</td>' +
                '<td class="my-table-td my-table-muted">' + _esc(lastAct) + '</td>' +
                '<td class="my-table-td my-table-actions">' +
                '  <button class="my-action-btn" title="Create Task" data-task-cand-id="' + _esc(c.attorney_id) + '" data-task-cand-src="' + _esc(c.attorney_source) + '" data-task-cand-name="' + _esc(c.attorney_name) + '" data-task-cand-firm="' + _esc(c.attorney_firm) + '"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18M9 16l2 2 4-4"/></svg></button>' +
                '</td>' +
                '</tr>';
        }).join("");

        el.innerHTML = '<div class="my-table-wrap"><table class="my-table"><thead><tr>' + thead + '</tr></thead><tbody>' + rows + '</tbody></table></div>';

        // Sort header clicks
        el.querySelectorAll(".my-table-sortable").forEach(function (th) {
            th.addEventListener("click", function () {
                var key = this.getAttribute("data-sort-key");
                if (_candSortKey === key) {
                    _candSortDir *= -1;
                } else {
                    _candSortKey = key;
                    _candSortDir = 1;
                }
                _renderMyCandidates();
            });
        });

        // Candidate name → open profile
        el.querySelectorAll(".cand-name-link").forEach(function (link) {
            link.addEventListener("click", function () {
                var src = this.getAttribute("data-src");
                var aid = this.getAttribute("data-aid");
                if (src === "custom") {
                    if (window.JAIDE && window.JAIDE.openCustomAttorneyProfile) window.JAIDE.openCustomAttorneyProfile(aid);
                } else {
                    if (window.JAIDE && window.JAIDE.openAttorneyProfile) window.JAIDE.openAttorneyProfile(aid);
                }
            });
        });

        // Job title → navigate to pipeline filtered by job
        el.querySelectorAll(".cand-job-link").forEach(function (link) {
            link.addEventListener("click", function () {
                var jid = this.getAttribute("data-jid");
                if (jid && window.JAIDE && window.JAIDE.loadPipelineForJob) {
                    window.JAIDE.loadPipelineForJob(parseInt(jid));
                }
                if (window.navigateTo) window.navigateTo("pipeline");
            });
        });

        // Create task quick action
        el.querySelectorAll("[data-task-cand-name]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                openTaskModal({
                    attorney_id: this.getAttribute("data-task-cand-id"),
                    attorney_source: this.getAttribute("data-task-cand-src"),
                    attorney_name: this.getAttribute("data-task-cand-name"),
                    attorney_firm: this.getAttribute("data-task-cand-firm"),
                });
            });
        });
    }

    function _bindCandidateFilters() {
        var bar = document.getElementById("my-cand-filters");
        if (bar) {
            bar.addEventListener("click", function (e) {
                var pill = e.target.closest(".stage-filter-pill");
                if (!pill) return;
                bar.querySelectorAll(".stage-filter-pill").forEach(function (p) { p.classList.remove("active"); });
                pill.classList.add("active");
                _candStageFilter = pill.getAttribute("data-stage");
                _renderMyCandidates();
            });
        }
        var viewAllLink = document.getElementById("dash-view-all-pipeline");
        if (viewAllLink) {
            viewAllLink.addEventListener("click", function (e) {
                e.preventDefault();
                if (window.navigateTo) window.navigateTo("pipeline");
            });
        }
    }

    // ── My Active Jobs ────────────────────────────────────────────────────
    function _renderMyJobs() {
        var el = document.getElementById("dash-my-jobs");
        if (!el) return;

        var data = _myJobs.filter(function (j) {
            if (!_jobsStatusFilter) return true;
            return j.status === _jobsStatusFilter;
        });

        if (!data.length) {
            el.innerHTML = '<div class="dash-loading">No jobs yet.</div>';
            return;
        }

        var STATUS_CLASSES = { Active: "job-status-active", "On Hold": "job-status-hold", Closed: "job-status-closed", Filled: "job-status-filled" };

        var rows = data.map(function (j) {
            var statusCls = STATUS_CLASSES[j.status] || "";
            var daysOpen = j.days_open || 0;
            var earlyDots = _dots(j.early_count || 0, "dot-early");
            var ivwDots = _dots(j.interview_count || 0, "dot-interview");
            var placedDots = _dots(j.placed_count || 0, "dot-placed");
            var stageSummary = earlyDots + ivwDots + placedDots;
            var stageMeta = [];
            if (j.early_count) stageMeta.push(j.early_count + " early");
            if (j.interview_count) stageMeta.push(j.interview_count + " interview");
            if (j.placed_count) stageMeta.push(j.placed_count + " placed");
            var stageText = stageMeta.join(" · ") || "—";
            return '<tr class="my-table-row">' +
                '<td class="my-table-td"><span class="cand-job-link" data-jid="' + j.id + '">' + _esc(j.title || "—") + '</span></td>' +
                '<td class="my-table-td my-table-muted">' + _esc(j.employer_name || "—") + '</td>' +
                '<td class="my-table-td my-table-muted">' + _esc(j.location || "—") + '</td>' +
                '<td class="my-table-td"><span class="cand-job-link" data-jid="' + j.id + '">' + (j.candidate_count || 0) + '</span></td>' +
                '<td class="my-table-td"><span class="stage-dots" title="' + _esc(stageText) + '">' + (stageSummary || '<span class="my-table-muted">—</span>') + '</span></td>' +
                '<td class="my-table-td my-table-muted">' + daysOpen + 'd</td>' +
                '<td class="my-table-td"><span class="job-status-pill ' + statusCls + '">' + _esc(j.status || "—") + '</span></td>' +
                '<td class="my-table-td my-table-actions">' +
                '  <button class="my-action-btn my-action-add-cand" title="Add Candidate" data-jid="' + j.id + '" data-jtitle="' + _esc(j.title) + '"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="17" y1="11" x2="23" y2="11"/></svg></button>' +
                '  <button class="my-action-btn" title="View Pipeline" data-pipeline-jid="' + j.id + '"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg></button>' +
                '</td>' +
                '</tr>';
        }).join("");

        var thead = '<th class="my-table-th">Job Title</th><th class="my-table-th">Client Firm</th><th class="my-table-th">Location</th><th class="my-table-th">Candidates</th><th class="my-table-th">Stage Breakdown</th><th class="my-table-th">Days Open</th><th class="my-table-th">Status</th><th class="my-table-th"></th>';

        el.innerHTML = '<div class="my-table-wrap"><table class="my-table"><thead><tr>' + thead + '</tr></thead><tbody>' + rows + '</tbody></table></div>';

        // Job link → pipeline filtered by job
        el.querySelectorAll(".cand-job-link").forEach(function (link) {
            link.addEventListener("click", function () {
                var jid = this.getAttribute("data-jid");
                if (jid && window.JAIDE && window.JAIDE.loadPipelineForJob) {
                    window.JAIDE.loadPipelineForJob(parseInt(jid));
                }
                if (window.navigateTo) window.navigateTo("pipeline");
            });
        });

        // Add candidate → open pipeline add modal with job context
        el.querySelectorAll(".my-action-add-cand").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var jid = parseInt(this.getAttribute("data-jid"));
                if (window.JAIDE && window.JAIDE.openAddToPipelineModal) {
                    window.JAIDE.openAddToPipelineModal({ jobId: jid });
                }
            });
        });

        // View pipeline
        el.querySelectorAll("[data-pipeline-jid]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var jid = parseInt(this.getAttribute("data-pipeline-jid"));
                if (window.JAIDE && window.JAIDE.loadPipelineForJob) {
                    window.JAIDE.loadPipelineForJob(jid);
                }
                if (window.navigateTo) window.navigateTo("pipeline");
            });
        });
    }

    function _dots(count, cls) {
        var MAX = 5;
        var html = "";
        var shown = Math.min(count, MAX);
        for (var i = 0; i < shown; i++) html += '<span class="stage-dot ' + cls + '"></span>';
        if (count > MAX) html += '<span class="stage-dot-overflow">+' + (count - MAX) + '</span>';
        return html;
    }

    function _bindJobFilters() {
        var bar = document.getElementById("my-jobs-filters");
        if (bar) {
            bar.addEventListener("click", function (e) {
                var pill = e.target.closest(".stage-filter-pill");
                if (!pill) return;
                bar.querySelectorAll(".stage-filter-pill").forEach(function (p) { p.classList.remove("active"); });
                pill.classList.add("active");
                _jobsStatusFilter = pill.getAttribute("data-status");
                _renderMyJobs();
            });
        }
    }

    // ── Unified Action Items (tasks + system alerts) ─────────────────────
    // TODO (Nylas): When Nylas integration is active, the /api/email/webhook endpoint
    //   will update email_log tracking fields. At that point, add a "hot lead" alert here:
    //   type "email_opened" → "{{name}} opened your email — follow up now!" (green border)
    //   type "email_replied" → "{{name}} replied to your outreach" (blue border, high urgency)
    //   These should be fetched via /api/dashboard/action-items and injected into systemAlerts.
    var _ALERT_STYLES = {
        stuck_candidate:    { border: "#EAB308", bg: "#FEFCE8" },
        empty_job:          { border: "#F97316", bg: "#FFF7ED" },
        upcoming_interview: { border: "#3B82F6", bg: "#EFF6FF" },
        firm_followup:      { border: "#9CA3AF", bg: "#F9FAFB" },
    };
    var _PRI_WEIGHT = { High: 0, Medium: 1, Low: 2 };

    function _renderUnifiedActionItems(tasks, systemAlerts) {
        var el = document.getElementById("dash-action-items");
        var badge = document.getElementById("dash-action-items-count");
        if (!el) return;
        var today = _today();
        var tomorrow = _addDays(today, 1);

        var unified = [];

        // Task items — all open tasks
        tasks.forEach(function (t) {
            if (t.status === "Completed" || t.status === "Cancelled") return;
            var d = t.due_date || "";
            var urgency = d && d < today ? 0
                        : d === today   ? 2
                        : d === tomorrow ? 3
                        : 6;
            unified.push({ kind: "task", urgency: urgency, task: t });
        });

        // System alert items — skip task-type alerts (tasks cover them)
        systemAlerts.forEach(function (item) {
            if (item.type === "overdue_task" || item.type === "task_due_today") return;
            var urgency = (item.type === "stuck_candidate" || item.type === "empty_job") ? 1 : 5;
            unified.push({ kind: "alert", urgency: urgency, item: item });
        });

        // Sort: urgency asc; within same urgency sort tasks by priority then due_date
        unified.sort(function (a, b) {
            if (a.urgency !== b.urgency) return a.urgency - b.urgency;
            if (a.kind === "task" && b.kind === "task") {
                var pa = _PRI_WEIGHT[a.task.priority] !== undefined ? _PRI_WEIGHT[a.task.priority] : 1;
                var pb = _PRI_WEIGHT[b.task.priority] !== undefined ? _PRI_WEIGHT[b.task.priority] : 1;
                if (pa !== pb) return pa - pb;
                // Overdue: earliest (most overdue) first
                var da = a.task.due_date || "9999";
                var db = b.task.due_date || "9999";
                return da < db ? -1 : da > db ? 1 : 0;
            }
            return 0;
        });

        if (badge) badge.textContent = unified.length > 0 ? String(unified.length) : "";

        if (!unified.length) {
            el.innerHTML = '<div class="dash-loading" style="padding:20px">All caught up! No tasks or alerts.</div>';
            return;
        }

        el.innerHTML = unified.map(function (u) {
            return u.kind === "task"
                ? _buildTaskItem(u.task, today, tomorrow)
                : _buildAlertItem(u.item);
        }).join("");

        // Checkbox → complete with strikethrough animation
        el.querySelectorAll("[data-complete-task]").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                var id = parseInt(this.getAttribute("data-complete-task"));
                _completeTaskAnimated(this, id);
            });
        });

        // Task row click → edit modal
        el.querySelectorAll(".ai-item-task").forEach(function (row) {
            row.addEventListener("click", function (e) {
                if (e.target.closest("[data-complete-task]")) return;
                var id = parseInt(this.getAttribute("data-task-id"));
                var task = _allTasks.find(function (t) { return t.id === id; });
                if (task) openTaskModal(task);
            });
        });

        // Alert action link clicks
        el.querySelectorAll(".ai-action-link").forEach(function (link) {
            link.addEventListener("click", function (e) {
                e.stopPropagation();
                var type = this.getAttribute("data-action-type");
                var id = this.getAttribute("data-action-id");
                if (type === "stuck_candidate") {
                    if (window.navigateTo) window.navigateTo("pipeline");
                } else if (type === "empty_job") {
                    if (window.navigateTo) window.navigateTo("jobs");
                } else if (type === "overdue_task" || type === "task_due_today") {
                    var task = _allTasks.find(function (t) { return t.id === parseInt(id); });
                    if (task) openTaskModal(task);
                }
            });
        });
    }

    function _buildTaskItem(t, today, tomorrow) {
        var d = t.due_date || "";
        var isOverdue  = d && d < today;
        var isToday    = d === today;
        var isTomorrow = d === tomorrow;
        var rowCls = isOverdue ? "task-overdue" : isToday ? "task-today" : isTomorrow ? "task-upcoming" : "";
        var pri = (t.priority || "medium").toLowerCase();
        var dotCls = pri === "high" ? "dot-high" : pri === "low" ? "dot-low" : "dot-medium";
        var overdueBadge = isOverdue ? '<span class="ai-overdue-badge">OVERDUE</span>' : "";
        var dueLabel = isOverdue   ? '<span class="ai-due-label">Due ' + _esc(d) + '</span>'
                     : isToday    ? '<span class="ai-due-label ai-due-today">Today</span>'
                     : isTomorrow ? '<span class="ai-due-label">Tomorrow</span>'
                     : "";
        var typeLabel = t.task_type && t.task_type !== "General"
            ? '<span class="ai-type-label">' + _esc(t.task_type) + '</span>' : "";
        var pills = "";
        if (t.attorney_name) pills += '<span class="ai-pill ai-pill-cand">' + _esc(t.attorney_name) + '</span>';
        if (t.job_title)     pills += '<span class="ai-pill ai-pill-job">' + _esc(t.job_title) + '</span>';
        if (t.firm_name)     pills += '<span class="ai-pill ai-pill-firm">' + _esc(t.firm_name) + '</span>';
        return '<div class="ai-item ai-item-task ' + rowCls + '" data-task-id="' + t.id + '">' +
            '<div class="ai-check" data-complete-task="' + t.id + '" title="Mark complete"></div>' +
            '<div class="ai-body">' +
                '<div class="ai-top">' +
                    '<span class="ai-priority-dot ' + dotCls + '"></span>' +
                    '<span class="ai-title">' + _esc(t.title) + '</span>' +
                    overdueBadge + typeLabel + dueLabel +
                '</div>' +
                (pills ? '<div class="ai-meta">' + pills + '</div>' : '') +
            '</div>' +
        '</div>';
    }

    function _buildAlertItem(item) {
        var style = _ALERT_STYLES[item.type] || { border: "#9CA3AF", bg: "#F9FAFB" };
        var actionId = String(item.task_id || item.pipeline_id || item.job_id || "");
        var icon = _alertIconSvg(item.type);
        return '<div class="ai-item ai-item-alert" style="border-left-color:' + style.border + ';background:' + style.bg + '">' +
            '<div class="ai-alert-icon">' + icon + '</div>' +
            '<div class="ai-body">' +
                '<div class="ai-top"><span class="ai-title">' + _esc(item.message) + '</span></div>' +
                '<div class="ai-meta"><span class="ai-action-link" data-action-type="' + _esc(item.type) + '" data-action-id="' + _esc(actionId) + '">' + _esc(item.action) + ' →</span></div>' +
            '</div>' +
        '</div>';
    }

    function _alertIconSvg(type) {
        if (type === "stuck_candidate")
            return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#EAB308" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
        if (type === "empty_job")
            return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F97316" stroke-width="2" stroke-linecap="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>';
        return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
    }

    function _completeTaskAnimated(checkEl, id) {
        var row = checkEl.closest(".ai-item-task");
        if (row) {
            checkEl.classList.add("ai-check-done");
            var titleEl = row.querySelector(".ai-title");
            if (titleEl) titleEl.style.cssText = "text-decoration:line-through;color:#aaa;transition:all .2s";
            row.style.opacity = "0.45";
        }
        fetch("/api/tasks/" + id + "/complete", { method: "PUT" })
            .then(function () { loadDashboardData(); })
            .catch(console.warn);
    }

    // ── Worklists ─────────────────────────────────────────────────────────
    function _renderWorklists(worklists) {
        var el = document.getElementById("dash-worklists-list");
        if (!el) return;
        if (!worklists.length) {
            el.innerHTML = '<div class="dash-worklists-empty">No worklists yet.<br><small>Create one to curate attorney lists.</small></div>';
            return;
        }
        el.innerHTML = worklists.slice(0, 8).map(wl => `
            <div class="dash-worklist-card" data-wl-id="${wl.id}">
                <div class="dash-worklist-dot" style="background:${_esc(wl.color || '#0059FF')}"></div>
                <span class="dash-worklist-name">${_esc(wl.name)}</span>
                <span class="dash-worklist-count">${wl.member_count || 0} members</span>
            </div>`).join("");
        el.querySelectorAll(".dash-worklist-card").forEach(card => {
            card.addEventListener("click", function () {
                openWorklistDetail(parseInt(this.getAttribute("data-wl-id")));
            });
        });
    }

    // ── Pipeline Funnel (compact horizontal) ─────────────────────────────
    function _renderPipelineFunnel(stats) {
        var el = document.getElementById("dash-pipeline-funnel");
        if (!el) return;
        var sc = stats.stage_counts || {};

        var EARLY   = ["Identified", "Contacted", "Responded", "Phone Screen", "Submitted to Client"];
        var INTERVIEW = ["Interview 1", "Interview 2", "Final Interview", "Reference Check"];
        var OFFER   = ["Offer Extended", "Placed"];

        var earlyN = EARLY.reduce(function (s, n) { return s + (sc[n] || 0); }, 0);
        var ivwN   = INTERVIEW.reduce(function (s, n) { return s + (sc[n] || 0); }, 0);
        var offerN = OFFER.reduce(function (s, n) { return s + (sc[n] || 0); }, 0);
        var total  = earlyN + ivwN + offerN;

        if (!total) {
            el.innerHTML = '<div class="dash-loading">No pipeline data yet.</div>';
            return;
        }

        var earlyPct = Math.round(earlyN / total * 100);
        var ivwPct   = Math.round(ivwN   / total * 100);
        var offerPct = 100 - earlyPct - ivwPct;

        // Segmented bar
        var bar = '<div class="pfunnel-hbar">' +
            (earlyN ? '<div class="pfunnel-seg seg-early" style="width:' + earlyPct + '%" title="Early: ' + earlyN + '"><span>' + earlyN + ' early</span></div>' : '') +
            (ivwN   ? '<div class="pfunnel-seg seg-interview" style="width:' + ivwPct + '%" title="Interview: ' + ivwN + '"><span>' + ivwN + ' interview</span></div>' : '') +
            (offerN ? '<div class="pfunnel-seg seg-offer" style="width:' + offerPct + '%" title="Offer/Placed: ' + offerN + '"><span>' + offerN + ' offer/placed</span></div>' : '') +
        '</div>';

        // Stage chips (non-zero only)
        var allStages = EARLY.map(function (n) { return { name: n, cls: "pchip-early" }; })
            .concat(INTERVIEW.map(function (n) { return { name: n, cls: "pchip-interview" }; }))
            .concat(OFFER.map(function (n) { return { name: n, cls: "pchip-offer" }; }));

        var chips = allStages.filter(function (s) { return sc[s.name]; }).map(function (s) {
            return '<span class="pfunnel-chip ' + s.cls + '"><strong>' + sc[s.name] + '</strong> ' + _esc(s.name) + '</span>';
        }).join("");

        el.innerHTML = bar + '<div class="pfunnel-chips">' + chips + '</div>';
    }

    // ── Quick Actions ─────────────────────────────────────────────────────
    function _bindQuickActions() {
        _on("dash-btn-add-candidate", "click", function () {
            if (window.JAIDE && window.JAIDE.openCustomAttorneyModal) window.JAIDE.openCustomAttorneyModal(null);
        });
        _on("dash-btn-add-job", "click", function () {
            if (window.JAIDE && window.JAIDE.openCustomJobModal) window.JAIDE.openCustomJobModal(null);
        });
        _on("dash-btn-add-firm", "click", function () {
            if (window.JAIDE && window.JAIDE.openCustomFirmModal) window.JAIDE.openCustomFirmModal(null);
        });
        _on("dash-btn-new-task", "click", function () { openTaskModal(null); });
        _on("dash-btn-new-task-2", "click", function () { openTaskModal(null); });
        _on("dash-btn-new-worklist", "click", function () { openWorklistModal(null); });
        // dash-manage-jobs, dash-manage-employers, dash-sent-emails handled by ats.js
        _on("dash-view-all-worklists", "click", function () { openWorklistModal(null); });
        _on("dash-goto-pipeline", "click", function () { if (window.navigateTo) window.navigateTo("pipeline"); });
    }

    // ── Task Modal ────────────────────────────────────────────────────────

    // Autocomplete helper — creates a reusable debounced AC controller
    function _makeAC(inputId, dropdownId, pillId, pillLabelId, clearId, searchFn, onSelect) {
        var input = document.getElementById(inputId);
        var dropdown = document.getElementById(dropdownId);
        var pill = document.getElementById(pillId);
        var pillLabel = document.getElementById(pillLabelId);
        var clearBtn = document.getElementById(clearId);
        if (!input) return { clear: function(){} };

        var _timer = null;
        var _selected = null;

        function clear() {
            _selected = null;
            input.value = "";
            if (pill) pill.style.display = "none";
            if (input) { input.style.display = ""; input.placeholder = input._placeholder || ""; }
            hideDropdown();
        }

        function select(item) {
            _selected = item;
            if (pillLabel) pillLabel.textContent = item.label;
            if (pill) pill.style.display = "";
            input.value = "";
            input.style.display = "none";
            hideDropdown();
            onSelect(item);
        }

        function hideDropdown() {
            if (dropdown) dropdown.style.display = "none";
        }

        function showResults(items) {
            if (!dropdown) return;
            if (!items.length) {
                dropdown.innerHTML = '<div class="ac-no-results">No results found</div>';
            } else {
                dropdown.innerHTML = items.map(function(item, i) {
                    return '<div class="ac-option" data-idx="' + i + '">' + _esc(item.label) + '</div>';
                }).join("");
                dropdown.querySelectorAll(".ac-option").forEach(function(opt, i) {
                    opt.addEventListener("mousedown", function(e) {
                        e.preventDefault();
                        select(items[i]);
                    });
                });
            }
            dropdown.style.display = "";
        }

        input._placeholder = input.placeholder;
        input.addEventListener("input", function() {
            clearTimeout(_timer);
            var q = this.value.trim();
            if (q.length < 2) { hideDropdown(); return; }
            _timer = setTimeout(function() {
                searchFn(q).then(showResults);
            }, 300);
        });
        input.addEventListener("blur", function() {
            setTimeout(hideDropdown, 150);
        });
        if (clearBtn) clearBtn.addEventListener("click", clear);

        return {
            clear: clear,
            select: select,
            getSelected: function() { return _selected; },
        };
    }

    var _acAttorney = null;
    var _acJob = null;
    var _acFirm = null;

    function _initAC() {
        _acAttorney = _makeAC(
            "task-attorney-input", "task-attorney-dropdown",
            "task-attorney-pill", "task-attorney-pill-label", "task-attorney-clear",
            function(q) { return fetch("/api/search/attorneys?q=" + encodeURIComponent(q)).then(r => r.json()); },
            function(item) {
                document.getElementById("task-attorney-id").value = item.id || "";
                document.getElementById("task-attorney-source").value = item.source || "fp";
                document.getElementById("task-attorney-name").value = item.name || "";
            }
        );
        _acJob = _makeAC(
            "task-job-input", "task-job-dropdown",
            "task-job-pill", "task-job-pill-label", "task-job-clear",
            function(q) { return fetch("/api/search/jobs?q=" + encodeURIComponent(q)).then(r => r.json()); },
            function(item) {
                var rawId = String(item.id || "").replace("custom_", "");
                document.getElementById("task-job-id").value = rawId;
                document.getElementById("task-job-title").value = item.title || "";
                // auto-fill firm if no firm selected yet
                if (item.firm && _acFirm && !_acFirm.getSelected()) {
                    document.getElementById("task-firm-name").value = item.firm;
                }
            }
        );
        _acFirm = _makeAC(
            "task-firm-input", "task-firm-dropdown",
            "task-firm-pill", "task-firm-pill-label", "task-firm-clear",
            function(q) { return fetch("/api/search/firms?q=" + encodeURIComponent(q)).then(r => r.json()); },
            function(item) {
                document.getElementById("task-firm-name").value = item.name || "";
                document.getElementById("task-firm-fp-id").value = item.fp_id || "";
            }
        );
    }

    function _resetAC() {
        // Reset AC fields and their hidden inputs
        if (_acAttorney) _acAttorney.clear();
        if (_acJob) _acJob.clear();
        if (_acFirm) _acFirm.clear();
        ["task-attorney-id", "task-attorney-source", "task-attorney-name",
         "task-job-id", "task-job-title", "task-firm-name", "task-firm-fp-id"].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.value = "";
        });
        // Show inputs (hidden when pill is active)
        ["task-attorney-input", "task-job-input", "task-firm-input"].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.style.display = "";
        });
    }

    function _prefillAC(task) {
        // Pre-fill attorney pill if task has attorney
        if (task.attorney_id && task.attorney_name && _acAttorney) {
            _acAttorney.select({
                id: task.attorney_id,
                source: task.attorney_source || "fp",
                name: task.attorney_name,
                label: task.attorney_name + (task.attorney_firm ? " — " + task.attorney_firm : ""),
            });
            document.getElementById("task-attorney-id").value = task.attorney_id;
            document.getElementById("task-attorney-source").value = task.attorney_source || "fp";
            document.getElementById("task-attorney-name").value = task.attorney_name;
        }
        // Pre-fill job pill
        if (task.job_id && task.job_title && _acJob) {
            _acJob.select({
                id: task.job_id,
                title: task.job_title,
                label: task.job_title + (task.firm_name ? " — " + task.firm_name : ""),
            });
            document.getElementById("task-job-id").value = task.job_id;
        }
        // Pre-fill firm
        if (task.firm_name && !task.job_id && _acFirm) {
            _acFirm.select({ name: task.firm_name, label: task.firm_name });
            document.getElementById("task-firm-name").value = task.firm_name;
        }
    }

    function openTaskModal(task) {
        var overlay = document.getElementById("task-modal-overlay");
        if (!overlay) return;
        var form = document.getElementById("task-form");
        form.reset();
        _resetAC();
        document.getElementById("task-id").value = task ? task.id : "";
        document.getElementById("task-modal-title").textContent = task ? "Edit Task" : "New Task";
        if (task) {
            _setVal("task-title", task.title || "");
            _setVal("task-type", task.task_type || "General");
            _setVal("task-priority", task.priority || "Medium");
            _setVal("task-due-date", task.due_date || "");
            _setVal("task-due-time", task.due_time || "");
            _setVal("task-description", task.description || "");
            _prefillAC(task);
        }
        overlay.classList.add("open");
    }

    function _bindTaskModal() {
        _initAC();
        _on("task-modal-close", "click", _closeTaskModal);
        _on("task-modal-cancel", "click", _closeTaskModal);
        _on("task-modal-overlay", "click", function (e) {
            if (e.target === this) _closeTaskModal();
        });
        var form = document.getElementById("task-form");
        if (form) form.addEventListener("submit", _onTaskSubmit);
    }

    function _closeTaskModal() {
        var overlay = document.getElementById("task-modal-overlay");
        if (overlay) overlay.classList.remove("open");
    }

    function _onTaskSubmit(e) {
        e.preventDefault();
        var id = document.getElementById("task-id").value;
        var jobIdRaw = (document.getElementById("task-job-id").value || "").replace("custom_", "");
        var data = {
            title: _getVal("task-title"),
            task_type: _getVal("task-type"),
            priority: _getVal("task-priority"),
            due_date: _getVal("task-due-date") || null,
            due_time: _getVal("task-due-time") || null,
            description: _getVal("task-description") || null,
            attorney_name: document.getElementById("task-attorney-name").value || null,
            attorney_id: document.getElementById("task-attorney-id").value || null,
            attorney_source: document.getElementById("task-attorney-source").value || "fp",
            firm_name: document.getElementById("task-firm-name").value || null,
            job_id: jobIdRaw ? parseInt(jobIdRaw) : null,
            job_title: document.getElementById("task-job-title").value || null,
            firm_fp_id: document.getElementById("task-firm-fp-id").value || null,
        };
        var url = id ? "/api/tasks/" + id : "/api/tasks";
        var method = id ? "PUT" : "POST";
        fetch(url, { method: method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
            .then(function(r) { return r.json(); })
            .then(function (res) {
                if (res.ok || res.id) {
                    _closeTaskModal();
                    loadDashboardData();
                    _showToast("Task saved.");
                } else {
                    _showToast("Error: " + (res.error || "Could not save task."), true);
                }
            });
    }

    // ── Worklist Modal ────────────────────────────────────────────────────
    function openWorklistModal(wl) {
        var overlay = document.getElementById("worklist-modal-overlay");
        if (!overlay) return;
        document.getElementById("worklist-form").reset();
        document.getElementById("worklist-id").value = wl ? wl.id : "";
        document.getElementById("worklist-modal-title").textContent = wl ? "Edit Worklist" : "New Worklist";
        _selectedWorklistColor = (wl && wl.color) || "#0059FF";
        if (wl) {
            _setVal("worklist-name", wl.name || "");
            _setVal("worklist-description", wl.description || "");
        }
        document.getElementById("worklist-color").value = _selectedWorklistColor;
        document.querySelectorAll(".wl-color-swatch").forEach(s => {
            s.classList.toggle("active", s.getAttribute("data-color") === _selectedWorklistColor);
        });
        overlay.classList.add("open");
    }

    function _bindWorklistModal() {
        _on("worklist-modal-close", "click", _closeWorklistModal);
        _on("worklist-modal-cancel", "click", _closeWorklistModal);
        _on("worklist-modal-overlay", "click", function (e) {
            if (e.target === this) _closeWorklistModal();
        });
        var picker = document.getElementById("worklist-color-picker");
        if (picker) {
            picker.addEventListener("click", function (e) {
                var swatch = e.target.closest(".wl-color-swatch");
                if (!swatch) return;
                _selectedWorklistColor = swatch.getAttribute("data-color");
                document.getElementById("worklist-color").value = _selectedWorklistColor;
                document.querySelectorAll(".wl-color-swatch").forEach(s => s.classList.remove("active"));
                swatch.classList.add("active");
            });
        }
        var form = document.getElementById("worklist-form");
        if (form) form.addEventListener("submit", _onWorklistSubmit);
    }

    function _closeWorklistModal() {
        var overlay = document.getElementById("worklist-modal-overlay");
        if (overlay) overlay.classList.remove("open");
    }

    function _onWorklistSubmit(e) {
        e.preventDefault();
        var id = document.getElementById("worklist-id").value;
        var data = {
            name: _getVal("worklist-name"),
            description: _getVal("worklist-description") || "",
            color: document.getElementById("worklist-color").value || "#0059FF",
        };
        var url = id ? "/api/worklists/" + id : "/api/worklists";
        var method = id ? "PUT" : "POST";
        fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
            .then(r => r.json())
            .then(function (res) {
                if (res.ok || res.id) {
                    _closeWorklistModal();
                    loadDashboardData();
                    _showToast("Worklist saved.");
                } else {
                    _showToast("Error: " + (res.error || "Could not save worklist."), true);
                }
            });
    }

    // ── Worklist Detail ───────────────────────────────────────────────────
    function openWorklistDetail(worklistId) {
        var overlay = document.getElementById("worklist-detail-overlay");
        if (!overlay) return;
        overlay.classList.add("open");
        overlay.setAttribute("data-wl-id", worklistId);
        document.getElementById("worklist-detail-members").innerHTML = '<div class="dash-loading">Loading…</div>';
        fetch("/api/worklists/" + worklistId)
            .then(r => r.json())
            .then(function (wl) {
                var wl_obj = wl;
                _setText("worklist-detail-name", wl.name);
                var dot = document.getElementById("worklist-detail-dot");
                if (dot) dot.style.background = wl.color || "#0059FF";
                _setText("worklist-detail-count", (wl.member_count || 0) + " members");
                _renderWorklistMembers(wl.members || [], wl);
                // store for actions
                overlay._wl = wl;
            });
    }

    function _renderWorklistMembers(members, wl) {
        var el = document.getElementById("worklist-detail-members");
        if (!el) return;
        if (!members.length) {
            el.innerHTML = '<div class="dash-loading">No members yet.</div>';
            return;
        }
        el.innerHTML = members.map(m => `
            <div class="worklist-member-row">
                ${m.attorney_source === "custom" ? '<span class="source-badge source-badge-custom">Custom</span>' : '<span class="source-badge source-badge-fp">FP</span>'}
                <span class="worklist-member-name">${_esc(m.attorney_name || "Attorney #" + m.attorney_id)}</span>
                <span class="worklist-member-firm">${_esc(m.attorney_firm || "")}</span>
                <span class="worklist-member-remove" data-rm-id="${_esc(m.attorney_id)}" data-rm-src="${_esc(m.attorney_source)}" title="Remove">×</span>
            </div>`).join("");
        el.querySelectorAll("[data-rm-id]").forEach(btn => {
            btn.addEventListener("click", function () {
                var wlId = parseInt(document.getElementById("worklist-detail-overlay").getAttribute("data-wl-id"));
                var attyId = this.getAttribute("data-rm-id");
                var src = this.getAttribute("data-rm-src");
                fetch("/api/worklists/" + wlId + "/members/" + attyId + "?source=" + src, { method: "DELETE" })
                    .then(() => openWorklistDetail(wlId));
            });
        });
    }

    function _bindWorklistDetail() {
        _on("worklist-detail-close", "click", function () {
            document.getElementById("worklist-detail-overlay").classList.remove("open");
        });
        _on("worklist-detail-overlay", "click", function (e) {
            if (e.target === this) this.classList.remove("open");
        });
        _on("worklist-detail-edit", "click", function () {
            var overlay = document.getElementById("worklist-detail-overlay");
            if (overlay && overlay._wl) {
                document.getElementById("worklist-detail-overlay").classList.remove("open");
                openWorklistModal(overlay._wl);
            }
        });
        _on("worklist-detail-delete", "click", function () {
            var overlay = document.getElementById("worklist-detail-overlay");
            var wl = overlay && overlay._wl;
            if (!wl) return;
            if (!confirm("Delete worklist \"" + wl.name + "\"? This cannot be undone.")) return;
            fetch("/api/worklists/" + wl.id, { method: "DELETE" })
                .then(() => {
                    overlay.classList.remove("open");
                    loadDashboardData();
                    _showToast("Worklist deleted.");
                });
        });
    }

    // ── Add to Worklist flow ──────────────────────────────────────────────
    function openAddToWorklist(attorney) {
        _pendingWorklistAttorney = attorney;
        var overlay = document.getElementById("add-to-worklist-overlay");
        if (!overlay) return;
        var nameEl = document.getElementById("add-to-worklist-name");
        if (nameEl) nameEl.textContent = "Adding: " + (attorney.name || attorney.attorney_name || "");
        var listEl = document.getElementById("add-to-worklist-list");
        if (listEl) listEl.innerHTML = '<div class="dash-loading">Loading…</div>';
        overlay.classList.add("open");
        Promise.all([
            fetch("/api/worklists").then(r => r.json()),
            fetch("/api/attorneys/" + encodeURIComponent(attorney.id || attorney.attorney_id) + "/worklists?source=" + (attorney.source || attorney.attorney_source || "fp")).then(r => r.json()),
        ]).then(function ([worklists, myWorklists]) {
            _allWorklists = worklists;
            var myIds = new Set(myWorklists.map(w => w.id));
            if (!listEl) return;
            if (!worklists.length) {
                listEl.innerHTML = '<div class="dash-loading">No worklists yet.</div>';
                return;
            }
            listEl.innerHTML = worklists.map(wl => `
                <div class="add-to-worklist-item" data-wl-id="${wl.id}">
                    <div class="add-to-worklist-dot" style="background:${_esc(wl.color || '#0059FF')}"></div>
                    <span class="add-to-worklist-name">${_esc(wl.name)}</span>
                    ${myIds.has(wl.id) ? '<span class="add-to-worklist-check">✓</span>' : ''}
                </div>`).join("");
            listEl.querySelectorAll(".add-to-worklist-item").forEach(item => {
                item.addEventListener("click", function () {
                    var wlId = parseInt(this.getAttribute("data-wl-id"));
                    _addToWorklist(wlId);
                });
            });
        });
    }

    function _addToWorklist(wlId) {
        var a = _pendingWorklistAttorney;
        if (!a) return;
        fetch("/api/worklists/" + wlId + "/members", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                attorney_id: a.id || a.attorney_id,
                attorney_source: a.source || a.attorney_source || "fp",
                attorney_name: a.name || a.attorney_name || "",
                attorney_firm: a.current_firm || a.attorney_firm || "",
                attorney_email: a.email || a.attorney_email || "",
            }),
        }).then(() => {
            document.getElementById("add-to-worklist-overlay").classList.remove("open");
            _showToast("Added to worklist.");
        });
    }

    function _bindAddToWorklist() {
        _on("add-to-worklist-close", "click", function () {
            document.getElementById("add-to-worklist-overlay").classList.remove("open");
        });
        _on("add-to-worklist-overlay", "click", function (e) {
            if (e.target === this) this.classList.remove("open");
        });
        _on("add-to-worklist-new", "click", function () {
            document.getElementById("add-to-worklist-overlay").classList.remove("open");
            openWorklistModal(null);
        });
    }

    // ── Helpers ───────────────────────────────────────────────────────────
    function _on(id, evt, fn) {
        var el = document.getElementById(id);
        if (el) el.addEventListener(evt, fn);
    }
    function _setText(id, val) {
        var el = document.getElementById(id);
        if (el) el.textContent = val;
    }
    function _setVal(id, val) {
        var el = document.getElementById(id);
        if (el) el.value = val;
    }
    function _getVal(id) {
        var el = document.getElementById(id);
        return el ? el.value.trim() : "";
    }
    function _esc(str) {
        return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function _today() {
        return new Date().toISOString().split("T")[0];
    }
    function _addDays(dateStr, n) {
        var d = new Date(dateStr + "T00:00:00Z");
        d.setUTCDate(d.getUTCDate() + n);
        return d.toISOString().split("T")[0];
    }
    function _fmt(n) {
        return Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
    }
    function _showToast(msg, isError) {
        if (window.JAIDE && window.JAIDE.showToast) {
            window.JAIDE.showToast(msg, isError ? "error" : "success");
        } else {
            var tc = document.getElementById("toast-container");
            if (!tc) return;
            var t = document.createElement("div");
            t.className = "toast" + (isError ? " toast-error" : "");
            t.textContent = msg;
            tc.appendChild(t);
            setTimeout(() => t.remove(), 3000);
        }
    }

    // ── Init ──────────────────────────────────────────────────────────────
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();
