// ============================================================
// JAIDE ATS – ATS (Applicant Tracking System) Module
// ============================================================
(function () {
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    function esc(s) {
        if (s == null) return "";
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    // ---- Toast notifications ----
    function showToast(message, type = "success") {
        const container = $("#toast-container");
        const toast = document.createElement("div");
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => toast.classList.add("show"), 10);
        setTimeout(() => {
            toast.classList.remove("show");
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    function timeAgo(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);
        if (diff < 60) return "just now";
        if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
        if (diff < 604800) return `${Math.floor(diff / 86400)} days ago`;
        return date.toLocaleDateString();
    }

    // ================================================================
    // View Navigation
    // ================================================================
    function showAtsView(viewId) {
        if (window.JAIDE && window.JAIDE.hideAllViews) {
            window.JAIDE.hideAllViews();
        }
        const view = document.getElementById(viewId);
        if (view) view.style.display = "block";
    }

    // Dashboard loader — populates metrics, pipeline board, and activity feed
    function loadDashboard() {
        loadPipelineBoard();
        loadActivityLog();
        // Fetch dashboard metrics
        fetch("/api/pipeline")
            .then(r => r.json())
            .then(data => {
                const pipeline = data.pipeline || [];
                const metricPipeline = document.getElementById("metric-pipeline");
                if (metricPipeline) metricPipeline.textContent = pipeline.length;
                const interviewStages = ["Phone Screen", "Submitted to Client", "Interview 1", "Interview 2", "Final Interview"];
                const interviews = pipeline.filter(p => interviewStages.includes(p.stage)).length;
                const metricInterviews = document.getElementById("metric-interviews");
                if (metricInterviews) metricInterviews.textContent = interviews;
                const placements = pipeline.filter(p => p.stage === "Placed").length;
                const metricPlacements = document.getElementById("metric-placements");
                if (metricPlacements) metricPlacements.textContent = placements;
                // Total pipeline value
                const totalValue = pipeline.reduce((sum, p) => sum + (parseFloat(p.placement_fee) || 0), 0);
                const metricValue = document.getElementById("metric-pipeline-value");
                if (metricValue) metricValue.textContent = "$" + totalValue.toLocaleString();
            });
        fetch("/api/jobs?status=Active")
            .then(r => r.json())
            .then(data => {
                const metricJobs = document.getElementById("metric-active-jobs");
                if (metricJobs) metricJobs.textContent = (data.jobs || []).length;
            });
    }

    // Expose loadDashboard for navigation
    window.JAIDE = window.JAIDE || {};
    window.JAIDE.loadDashboard = loadDashboard;
    window.JAIDE.openAddToPipelineModal = openAddToPipelineModal;
    window.JAIDE.loadPipelineForJob = (jobId) => loadPipelineBoard(jobId);
    window.JAIDE.loadJobOptions = loadJobOptions;

    // Listen for add-to-pipeline events from profile view (decoupled from window.JAIDE)
    document.addEventListener("jaide:addToPipeline", (e) => {
        openAddToPipelineModal(e.detail);
    });

    // Auto-load dashboard if it's the active view on page load
    const dashboardViewEl = document.getElementById("view-dashboard");
    if (dashboardViewEl && dashboardViewEl.classList.contains("view-active")) {
        loadDashboard();
    }

    // Dashboard quick action buttons
    const dashManageJobs = $("#dash-manage-jobs");
    const dashManageEmployers = $("#dash-manage-employers");
    const dashSentEmails = $("#dash-sent-emails");

    const dashAddCandidate = $("#dash-add-candidate");
    if (dashAddCandidate) {
        dashAddCandidate.addEventListener("click", () => openCandidateSearchModal());
    }
    const btnPipelineAdd = $("#btn-pipeline-add");
    if (btnPipelineAdd) {
        btnPipelineAdd.addEventListener("click", () => openCandidateSearchModal());
    }
    const btnPipelineNewSearch = $("#btn-pipeline-new-search");
    if (btnPipelineNewSearch) {
        btnPipelineNewSearch.addEventListener("click", () => openCandidateSearchModal());
    }

    if (dashManageJobs) {
        dashManageJobs.addEventListener("click", () => {
            if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("attorneys");
            setTimeout(() => { showAtsView("jobs-view"); loadJobs(); }, 50);
        });
    }
    if (dashManageEmployers) {
        dashManageEmployers.addEventListener("click", () => {
            if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("attorneys");
            setTimeout(() => { showAtsView("employers-view"); loadEmployers(); }, 50);
        });
    }
    if (dashSentEmails) {
        dashSentEmails.addEventListener("click", () => {
            if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("attorneys");
            setTimeout(() => {
                if (window.JAIDE.hideAllViews) window.JAIDE.hideAllViews();
                const sentView = document.getElementById("sent-emails-view");
                if (sentView) sentView.style.display = "block";
                // Load sent emails
                fetch("/api/email/log")
                    .then(r => r.json())
                    .then(data => {
                        const entries = data.entries || [];
                        const tableEl = document.getElementById("sent-emails-table");
                        if (!tableEl) return;
                        if (!entries.length) {
                            tableEl.innerHTML = '<p class="no-data" style="padding:20px">No emails sent yet.</p>';
                            return;
                        }
                        let rows = "";
                        entries.forEach(e => {
                            const statusClass = e.status === "sent" ? "status-sent" : "status-failed";
                            rows += '<tr><td>' + esc(e.timestamp || "") + '</td><td>' + esc(e.candidate_name || "") + '</td><td>' + esc(e.to || "") + '</td><td>' + esc(e.subject || "") + '</td><td><span class="email-status ' + statusClass + '">' + esc(e.status || "") + '</span></td><td class="cell-error">' + esc(e.error || "") + '</td></tr>';
                        });
                        tableEl.innerHTML = '<div class="table-wrapper"><table class="candidate-table"><thead><tr><th>Time</th><th>Candidate</th><th>To</th><th>Subject</th><th>Status</th><th>Error</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
                    });
            }, 50);
        });
    }

    // ================================================================
    // Employer Management
    // ================================================================
    let _employerCache = [];

    function loadEmployers(search) {
        const q = search || ($("#employer-search") ? $("#employer-search").value : "");
        fetch(`/api/employers?search=${encodeURIComponent(q)}`)
            .then(r => r.json())
            .then(data => {
                _employerCache = data.employers || [];
                renderEmployersTable(_employerCache);
            });
    }

    function renderEmployersTable(employers) {
        const container = $("#employers-table");
        if (!employers.length) {
            container.innerHTML = '<p class="no-data" style="padding:20px">No employers yet. Click "Add Employer" to get started.</p>';
            return;
        }
        let rows = "";
        employers.forEach(e => {
            rows += `<tr>
                <td><a class="name-link emp-link" data-id="${e.id}">${esc(e.name)}</a></td>
                <td>${esc(e.city || "")}${e.city && e.state ? ", " : ""}${esc(e.state || "")}</td>
                <td class="cell-center">${e.active_jobs || 0}</td>
                <td class="cell-center">${e.total_candidates || 0}</td>
                <td>${e.created_at ? new Date(e.created_at).toLocaleDateString() : ""}</td>
            </tr>`;
        });
        container.innerHTML = `<div class="table-wrapper"><table class="candidate-table">
            <thead><tr><th>Name</th><th>Location</th><th>Active Jobs</th><th>Candidates</th><th>Created</th></tr></thead>
            <tbody>${rows}</tbody></table></div>`;
        container.querySelectorAll(".emp-link").forEach(link => {
            link.addEventListener("click", () => showEmployerDetail(parseInt(link.dataset.id)));
        });
    }

    // Employer search
    const empSearch = $("#employer-search");
    if (empSearch) {
        let debounce;
        empSearch.addEventListener("input", () => {
            clearTimeout(debounce);
            debounce = setTimeout(() => loadEmployers(empSearch.value), 300);
        });
    }

    // Add employer
    $("#btn-add-employer").addEventListener("click", () => openEmployerModal());

    function openEmployerModal(employer) {
        const overlay = $("#employer-modal-overlay");
        $("#employer-modal-title").textContent = employer ? "Edit Employer" : "Add Employer";
        $("#emp-id").value = employer ? employer.id : "";
        $("#emp-name").value = employer ? employer.name : "";
        $("#emp-website").value = employer ? (employer.website || "") : "";
        $("#emp-city").value = employer ? (employer.city || "") : "";
        $("#emp-state").value = employer ? (employer.state || "") : "";
        $("#emp-notes").value = employer ? (employer.notes || "") : "";
        $("#employer-modal-status").textContent = "";
        overlay.classList.add("open");
    }

    function closeEmployerModal() {
        $("#employer-modal-overlay").classList.remove("open");
    }
    $("#employer-modal-close").addEventListener("click", closeEmployerModal);
    $("#employer-modal-cancel").addEventListener("click", closeEmployerModal);
    $("#employer-modal-overlay").addEventListener("click", e => { if (e.target === $("#employer-modal-overlay")) closeEmployerModal(); });

    $("#employer-form").addEventListener("submit", e => {
        e.preventDefault();
        const id = $("#emp-id").value;
        const payload = {
            name: $("#emp-name").value.trim(),
            website: $("#emp-website").value.trim(),
            city: $("#emp-city").value.trim(),
            state: $("#emp-state").value.trim(),
            notes: $("#emp-notes").value.trim(),
        };
        if (!payload.name) { $("#employer-modal-status").textContent = "Name is required"; return; }

        const url = id ? `/api/employers/${id}` : "/api/employers";
        const method = id ? "PUT" : "POST";
        fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
            .then(r => r.json())
            .then(data => {
                if (data.error) { $("#employer-modal-status").textContent = data.error; return; }
                closeEmployerModal();
                showToast(id ? "Employer updated" : "Employer created");
                loadEmployers();
            });
    });

    function showEmployerDetail(id) {
        showAtsView("employer-detail-view");
        fetch(`/api/employers/${id}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) return;
                const emp = data.employer;
                const jobs = data.jobs || [];
                $("#employer-detail-title").textContent = emp.name;
                const content = $("#employer-detail-content");
                let info = `<div class="employer-info">`;
                if (emp.website) info += `<div><strong>Website:</strong> <a href="${esc(emp.website)}" target="_blank">${esc(emp.website)}</a></div>`;
                if (emp.city || emp.state) info += `<div><strong>Location:</strong> ${esc(emp.city || "")}${emp.city && emp.state ? ", " : ""}${esc(emp.state || "")}</div>`;
                if (emp.notes) info += `<div><strong>Notes:</strong> ${esc(emp.notes)}</div>`;
                info += `</div>`;

                let jobsHtml = `<h3 style="margin:20px 0 10px">Jobs (${jobs.length})</h3>`;
                if (jobs.length) {
                    let rows = "";
                    jobs.forEach(j => {
                        const statusClass = { Active: "status-active", "On Hold": "status-hold", Filled: "status-filled", Closed: "status-closed" }[j.status] || "";
                        rows += `<tr>
                            <td><a class="name-link job-link" data-id="${j.id}">${esc(j.title)}</a></td>
                            <td>${esc(j.location || "")}</td>
                            <td>${esc(j.practice_area || "")}</td>
                            <td><span class="job-status-badge ${statusClass}">${esc(j.status)}</span></td>
                            <td class="cell-center">${j.candidate_count || 0}</td>
                        </tr>`;
                    });
                    jobsHtml += `<div class="table-wrapper"><table class="candidate-table">
                        <thead><tr><th>Title</th><th>Location</th><th>Practice Area</th><th>Status</th><th>Candidates</th></tr></thead>
                        <tbody>${rows}</tbody></table></div>`;
                } else {
                    jobsHtml += '<p class="no-data">No jobs yet for this employer.</p>';
                }
                content.innerHTML = info + jobsHtml;
                content.querySelectorAll(".job-link").forEach(link => {
                    link.addEventListener("click", () => {
                        if (window.JAIDE && window.JAIDE.navigateTo) window.JAIDE.navigateTo("dashboard");
                        loadPipelineBoard(parseInt(link.dataset.id));
                    });
                });

                // Edit button
                const editBtn = $("#btn-edit-employer");
                editBtn.onclick = () => openEmployerModal(emp);
            });
    }

    $("#btn-employer-back").addEventListener("click", () => { showAtsView("employers-view"); loadEmployers(); });

    // ================================================================
    // Job Management
    // ================================================================
    function loadJobs() {
        const status = $("#job-filter-status") ? $("#job-filter-status").value : "";
        const employerId = $("#job-filter-employer") ? $("#job-filter-employer").value : "";
        const params = new URLSearchParams();
        if (status) params.set("status", status);
        if (employerId) params.set("employer_id", employerId);

        fetch(`/api/jobs?${params}`)
            .then(r => r.json())
            .then(data => renderJobsTable(data.jobs || []));

        // Populate employer filter
        loadEmployerOptions($("#job-filter-employer"));
    }

    function renderJobsTable(jobs) {
        const container = $("#jobs-table");
        if (!jobs.length) {
            container.innerHTML = '<p class="no-data" style="padding:20px">No jobs yet. Click "Add Job" to create one.</p>';
            return;
        }
        let rows = "";
        jobs.forEach(j => {
            const statusClass = { Active: "status-active", "On Hold": "status-hold", Filled: "status-filled", Closed: "status-closed" }[j.status] || "";
            rows += `<tr>
                <td><a class="name-link job-pipeline-link" data-id="${j.id}">${esc(j.title)}</a></td>
                <td>${esc(j.employer_name || "")}</td>
                <td>${esc(j.location || "")}</td>
                <td>${esc(j.practice_area || "")}</td>
                <td><span class="job-status-badge ${statusClass}">${esc(j.status)}</span></td>
                <td class="cell-center">${j.candidate_count || 0}</td>
                <td>${j.created_at ? new Date(j.created_at).toLocaleDateString() : ""}</td>
            </tr>`;
        });
        container.innerHTML = `<div class="table-wrapper"><table class="candidate-table">
            <thead><tr><th>Title</th><th>Employer</th><th>Location</th><th>Practice Area</th><th>Status</th><th>Candidates</th><th>Created</th></tr></thead>
            <tbody>${rows}</tbody></table></div>`;
        container.querySelectorAll(".job-pipeline-link").forEach(link => {
            link.addEventListener("click", () => {
                if (window.JAIDE && window.JAIDE.navigateTo) window.JAIDE.navigateTo("dashboard");
                loadPipelineBoard(parseInt(link.dataset.id));
            });
        });
    }

    // Job filters
    const jobFilterStatus = $("#job-filter-status");
    const jobFilterEmployer = $("#job-filter-employer");
    if (jobFilterStatus) jobFilterStatus.addEventListener("change", loadJobs);
    if (jobFilterEmployer) jobFilterEmployer.addEventListener("change", loadJobs);

    // Add job
    $("#btn-add-job").addEventListener("click", () => openJobModal());

    function openJobModal(job) {
        const overlay = $("#job-modal-overlay");
        $("#job-modal-title").textContent = job ? "Edit Job" : "Add Job";
        $("#job-id").value = job ? job.id : "";
        loadEmployerOptions($("#job-employer"), job ? job.employer_id : null);
        $("#job-title").value = job ? job.title : "";
        $("#job-location").value = job ? (job.location || "") : "";
        $("#job-status").value = job ? job.status : "Active";
        $("#job-practice-area").value = job ? (job.practice_area || "") : "";
        $("#job-specialty").value = job ? (job.specialty || "") : "";
        $("#job-grad-min").value = job ? (job.graduation_year_min || "") : "";
        $("#job-grad-max").value = job ? (job.graduation_year_max || "") : "";
        $("#job-salary-min").value = job ? (job.salary_min || "") : "";
        $("#job-salary-max").value = job ? (job.salary_max || "") : "";
        $("#job-bar").value = job ? (job.bar_required || "") : "";
        $("#job-description").value = job ? (job.description || "") : "";
        $("#job-modal-status").textContent = "";
        overlay.classList.add("open");
    }

    function closeJobModal() { $("#job-modal-overlay").classList.remove("open"); }
    $("#job-modal-close").addEventListener("click", closeJobModal);
    $("#job-modal-cancel").addEventListener("click", closeJobModal);
    $("#job-modal-overlay").addEventListener("click", e => { if (e.target === $("#job-modal-overlay")) closeJobModal(); });

    // Create employer from job modal
    $("#btn-job-new-employer").addEventListener("click", () => openEmployerModal());

    $("#job-form").addEventListener("submit", e => {
        e.preventDefault();
        const id = $("#job-id").value;
        const payload = {
            employer_id: parseInt($("#job-employer").value) || null,
            title: $("#job-title").value.trim(),
            location: $("#job-location").value.trim(),
            status: $("#job-status").value,
            practice_area: $("#job-practice-area").value.trim(),
            specialty: $("#job-specialty").value.trim(),
            graduation_year_min: parseInt($("#job-grad-min").value) || null,
            graduation_year_max: parseInt($("#job-grad-max").value) || null,
            salary_min: parseInt($("#job-salary-min").value) || null,
            salary_max: parseInt($("#job-salary-max").value) || null,
            bar_required: $("#job-bar").value.trim(),
            description: $("#job-description").value.trim(),
        };
        if (!payload.title) { $("#job-modal-status").textContent = "Title is required"; return; }
        if (!payload.employer_id) { $("#job-modal-status").textContent = "Employer is required"; return; }

        const url = id ? `/api/jobs/${id}` : "/api/jobs";
        const method = id ? "PUT" : "POST";
        fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
            .then(r => r.json())
            .then(data => {
                if (data.error) { $("#job-modal-status").textContent = data.error; return; }
                closeJobModal();
                showToast(id ? "Job updated" : `Job created: ${payload.title}`);
                loadJobs();
            });
    });

    // ---- Helper: load employer dropdown options ----
    function loadEmployerOptions(selectEl, selectedId) {
        if (!selectEl) return;
        fetch("/api/employers")
            .then(r => r.json())
            .then(data => {
                const emps = data.employers || [];
                const firstOpt = selectEl.querySelector("option:first-child");
                const firstText = firstOpt ? firstOpt.textContent : "All Employers";
                selectEl.innerHTML = `<option value="">${firstText}</option>`;
                emps.forEach(e => {
                    const opt = document.createElement("option");
                    opt.value = e.id;
                    opt.textContent = e.name;
                    if (selectedId && e.id === selectedId) opt.selected = true;
                    selectEl.appendChild(opt);
                });
            });
    }

    // ================================================================
    // Save as Job (from search results)
    // ================================================================
    const saveJobBtn = $("#btn-save-job");
    if (saveJobBtn) {
        saveJobBtn.addEventListener("click", () => {
            if (saveJobBtn._savedJobId) {
                // Already saved - go to pipeline on dashboard
                if (window.JAIDE && window.JAIDE.navigateTo) window.JAIDE.navigateTo("dashboard");
                loadPipelineBoard(saveJobBtn._savedJobId);
                return;
            }
            // Pre-fill job modal from search meta
            const meta = window.JAIDE && window.JAIDE.getCurrentMeta ? window.JAIDE.getCurrentMeta() : null;
            const jdText = window.JAIDE && window.JAIDE.getCurrentJdText ? window.JAIDE.getCurrentJdText() : "";
            const job = {
                title: "",
                location: "",
                practice_area: "",
                bar_required: "",
                description: jdText,
            };
            if (meta) {
                job.location = meta.city ? `${meta.city}, ${meta.state || ""}`.trim() : "";
                job.practice_area = (meta.practice_areas || []).join(", ");
                job.bar_required = (meta.required_bars || []).join(", ");
                job.graduation_year_min = meta.grad_year_min;
                job.graduation_year_max = meta.grad_year_max;
            }
            openJobModal(job);
        });
    }

    // ================================================================
    // Pipeline Board (Kanban)
    // ================================================================
    const STAGES = [
        "Identified", "Contacted", "Responded", "Phone Screen",
        "Submitted to Client", "Interview 1", "Interview 2", "Final Interview",
        "Reference Check", "Offer Extended", "Offer Accepted", "Placed",
        "Rejected", "Withdrawn", "On Hold"
    ];

    const STAGE_THEME = {
        "Identified": "blue", "Contacted": "blue", "Responded": "blue",
        "Phone Screen": "blue", "Submitted to Client": "blue",
        "Interview 1": "blue", "Interview 2": "blue", "Final Interview": "blue",
        "Reference Check": "green", "Offer Extended": "green", "Offer Accepted": "green", "Placed": "green",
        "Rejected": "red", "Withdrawn": "red", "On Hold": "yellow"
    };

    const PROMPT_STAGES = ["Rejected", "Withdrawn", "Offer Extended", "Placed"];

    let _pipelineData = [];
    let _currentFilterJobId = null;
    let _sortables = [];

    function loadPipelineBoard(filterJobId) {
        if (filterJobId !== undefined) {
            _currentFilterJobId = filterJobId;
            const filterEl = $("#pipeline-filter-job");
            if (filterEl) filterEl.value = filterJobId || "";
        }
        const params = new URLSearchParams();
        const jobId = _currentFilterJobId || ($("#pipeline-filter-job") ? $("#pipeline-filter-job").value : "");
        const employerId = $("#pipeline-filter-employer") ? $("#pipeline-filter-employer").value : "";
        const search = $("#pipeline-search") ? $("#pipeline-search").value : "";
        if (jobId) params.set("job_id", jobId);
        if (employerId) params.set("employer_id", employerId);
        if (search) params.set("search", search);

        fetch(`/api/pipeline?${params}`)
            .then(r => r.json())
            .then(data => {
                _pipelineData = data.pipeline || [];
                renderKanbanBoard(_pipelineData);
            });

        // Populate filters
        loadJobOptions($("#pipeline-filter-job"));
        loadEmployerOptions($("#pipeline-filter-employer"));
    }

    function loadJobOptions(selectEl) {
        if (!selectEl) return;
        fetch("/api/jobs?status=Active")
            .then(r => r.json())
            .then(data => {
                const jobs = data.jobs || [];
                // Also get On Hold jobs
                fetch("/api/jobs?status=On Hold")
                    .then(r2 => r2.json())
                    .then(data2 => {
                        const allJobs = [...jobs, ...(data2.jobs || [])];
                        const firstOpt = selectEl.querySelector("option:first-child");
                        const firstText = firstOpt ? firstOpt.textContent : "All Jobs";
                        const savedVal = selectEl.value;
                        selectEl.innerHTML = `<option value="">${firstText}</option>`;
                        // Group by employer
                        const grouped = {};
                        allJobs.forEach(j => {
                            const emp = j.employer_name || "Unknown";
                            if (!grouped[emp]) grouped[emp] = [];
                            grouped[emp].push(j);
                        });
                        Object.keys(grouped).sort().forEach(emp => {
                            const optgroup = document.createElement("optgroup");
                            optgroup.label = emp;
                            grouped[emp].forEach(j => {
                                const opt = document.createElement("option");
                                opt.value = j.id;
                                opt.textContent = `${j.title} (${j.status})`;
                                optgroup.appendChild(opt);
                            });
                            selectEl.appendChild(optgroup);
                        });
                        if (savedVal) selectEl.value = savedVal;
                    });
            });
    }

    function renderKanbanBoard(pipeline) {
        const board = $("#kanban-board");
        const emptyState = $("#pipeline-empty");

        // Cleanup old sortables
        _sortables.forEach(s => s.destroy());
        _sortables = [];
        board.innerHTML = "";

        // Sort pipeline entries
        const sortMode = $("#pipeline-sort") ? $("#pipeline-sort").value : "newest";
        const sorted = [...pipeline];
        if (sortMode === "oldest") sorted.sort((a, b) => new Date(a.added_at) - new Date(b.added_at));
        else if (sortMode === "alpha") sorted.sort((a, b) => (a.attorney_name || "").localeCompare(b.attorney_name || ""));
        else sorted.sort((a, b) => new Date(b.updated_at || b.added_at) - new Date(a.updated_at || a.added_at));

        // Group by stage
        const byStage = {};
        STAGES.forEach(s => byStage[s] = []);
        sorted.forEach(entry => {
            const stage = entry.stage || "Identified";
            if (byStage[stage]) byStage[stage].push(entry);
        });

        // Check if any data at all
        const totalEntries = sorted.length;
        if (totalEntries === 0 && !_currentFilterJobId) {
            board.style.display = "none";
            emptyState.style.display = "flex";
            return;
        }
        board.style.display = "flex";
        emptyState.style.display = "none";

        // Determine which stages to show (hide terminal stages if empty unless filter is set)
        const hiddenIfEmpty = ["Rejected", "Withdrawn", "On Hold"];

        STAGES.forEach(stage => {
            const entries = byStage[stage];
            if (!entries.length && hiddenIfEmpty.includes(stage) && !_currentFilterJobId) return;

            const theme = STAGE_THEME[stage] || "blue";
            const col = document.createElement("div");
            col.className = "kanban-column";
            col.dataset.stage = stage;

            col.innerHTML = `
                <div class="kanban-col-header kanban-theme-${theme}">
                    <span class="kanban-col-title">${esc(stage)}</span>
                    <span class="kanban-col-count">${entries.length}</span>
                </div>
                <div class="kanban-col-body" data-stage="${esc(stage)}"></div>
                ${stage === "Identified" ? '<button class="kanban-add-btn" data-stage="Identified">+ Add Candidate</button>' : ""}
            `;

            const body = col.querySelector(".kanban-col-body");
            entries.forEach(entry => {
                body.appendChild(createKanbanCard(entry));
            });

            board.appendChild(col);

            // SortableJS for drag-and-drop
            const sortable = new Sortable(body, {
                group: "pipeline",
                animation: 150,
                ghostClass: "kanban-ghost",
                chosenClass: "kanban-chosen",
                dragClass: "kanban-drag",
                onEnd: (evt) => handleDragEnd(evt),
            });
            _sortables.push(sortable);
        });

        // Wire add candidate buttons
        board.querySelectorAll(".kanban-add-btn").forEach(btn => {
            btn.addEventListener("click", () => openCandidateSearchModal());
        });
    }

    function createKanbanCard(entry) {
        const card = document.createElement("div");
        card.className = "kanban-card";
        card.dataset.pipelineId = entry.id;
        card.dataset.stage = entry.stage;

        const showJob = !_currentFilterJobId;
        const daysInStage = timeAgo(entry.updated_at || entry.added_at);

        const feeDisplay = entry.placement_fee ? `<div class="kanban-card-fee">$${Number(entry.placement_fee).toLocaleString()}</div>` : "";

        card.innerHTML = `
            <div class="kanban-card-name"><a class="kanban-attorney-link" data-attorney-id="${esc(String(entry.attorney_id || ""))}">${esc(entry.attorney_name || "Unknown")}</a></div>
            <div class="kanban-card-firm">${esc(entry.attorney_firm || "")}</div>
            ${showJob ? `<div class="kanban-card-job"><a class="kanban-job-link" data-job-id="${entry.job_id || ""}">${esc(entry.job_title || "")}</a> ${entry.employer_name ? "@ " + esc(entry.employer_name) : ""}</div>` : ""}
            ${feeDisplay}
            <div class="kanban-card-meta">
                <span class="kanban-card-time">${daysInStage}</span>
                ${entry.notes ? '<span class="kanban-card-notes" title="' + esc(entry.notes) + '">&#128221;</span>' : ""}
            </div>
            <div class="kanban-card-menu">
                <button class="kanban-menu-btn" title="Actions">&#8230;</button>
                <div class="kanban-menu-dropdown">
                    <button class="kanban-menu-item" data-action="note" data-id="${entry.id}">Add Note</button>
                    <button class="kanban-menu-item" data-action="fee" data-id="${entry.id}">Set Fee</button>
                    <button class="kanban-menu-item" data-action="email" data-id="${entry.id}">Send Email</button>
                    <button class="kanban-menu-item" data-action="similar" data-id="${entry.id}">Find Similar</button>
                    <button class="kanban-menu-item" data-action="pitch" data-id="${entry.id}">Generate Pitch</button>
                    <button class="kanban-menu-item kanban-menu-danger" data-action="remove" data-id="${entry.id}">Remove</button>
                </div>
            </div>
        `;

        // Attorney name link → open profile modal
        const attorneyLink = card.querySelector(".kanban-attorney-link");
        if (attorneyLink) {
            attorneyLink.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                const aid = attorneyLink.dataset.attorneyId;
                if (aid) {
                    fetch(`/api/attorneys/${encodeURIComponent(aid)}`)
                        .then(r => r.json())
                        .then(data => {
                            if (data.attorney && window.JAIDE && window.JAIDE.openProfile) {
                                window.JAIDE.openProfile(data.attorney);
                            }
                        });
                }
            });
        }
        // Job title link → filter pipeline by that job
        const jobLink = card.querySelector(".kanban-job-link");
        if (jobLink) {
            jobLink.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                const jobId = jobLink.dataset.jobId;
                if (jobId) loadPipelineBoard(parseInt(jobId));
            });
        }

        // Menu toggle
        const menuBtn = card.querySelector(".kanban-menu-btn");
        const dropdown = card.querySelector(".kanban-menu-dropdown");
        menuBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            // Close all other menus
            document.querySelectorAll(".kanban-menu-dropdown.open").forEach(d => d.classList.remove("open"));
            dropdown.classList.toggle("open");
        });

        // Menu items
        card.querySelectorAll(".kanban-menu-item").forEach(item => {
            item.addEventListener("click", (e) => {
                e.stopPropagation();
                dropdown.classList.remove("open");
                const action = item.dataset.action;
                const id = parseInt(item.dataset.id);
                if (action === "note") promptPipelineNote(id, entry);
                else if (action === "fee") promptPlacementFee(id, entry);
                else if (action === "email") handlePipelineEmail(entry);
                else if (action === "similar") handlePipelineFindSimilar(entry);
                else if (action === "pitch") handlePipelinePitch(entry);
                else if (action === "remove") handlePipelineRemove(id, entry);
            });
        });

        return card;
    }

    function handleDragEnd(evt) {
        const el = evt.item;
        const pipelineId = parseInt(el.dataset.pipelineId);
        const newStage = evt.to.dataset.stage;
        const oldStage = el.dataset.stage;

        if (oldStage === newStage) return;

        // Check if this stage needs a prompt
        if (PROMPT_STAGES.includes(newStage)) {
            openStageMovePrompt(pipelineId, oldStage, newStage, el);
        } else {
            doStageMove(pipelineId, newStage);
        }
    }

    function doStageMove(pipelineId, newStage, note) {
        fetch(`/api/pipeline/${pipelineId}/move`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stage: newStage, note: note || "" }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                // Update local data
                const entry = _pipelineData.find(e => e.id === pipelineId);
                if (entry) {
                    const name = entry.attorney_name || "Candidate";
                    showToast(`${name} moved to ${newStage}`);
                }
                loadPipelineBoard();
            }
        });
    }

    // Stage move prompt modal
    let _pendingMove = null;

    function openStageMovePrompt(pipelineId, fromStage, toStage, cardEl) {
        _pendingMove = { pipelineId, fromStage, toStage, cardEl };
        const overlay = $("#stage-move-overlay");
        const entry = _pipelineData.find(e => e.id === pipelineId);
        const name = entry ? entry.attorney_name : "Candidate";
        $("#stage-move-title").textContent = `Move ${name} to ${toStage}`;

        if (toStage === "Rejected" || toStage === "Withdrawn") {
            $("#stage-move-label").textContent = "Reason (optional)";
            $("#stage-move-note").placeholder = "Why is this candidate being " + toStage.toLowerCase() + "?";
        } else if (toStage === "Offer Extended") {
            $("#stage-move-label").textContent = "Offer Details (optional)";
            $("#stage-move-note").placeholder = "Offer details...";
        } else if (toStage === "Placed") {
            $("#stage-move-label").textContent = "Notes (optional)";
            $("#stage-move-note").placeholder = "Any placement notes...";
            $("#stage-move-date-group").style.display = "block";
        }
        if (toStage !== "Placed") {
            $("#stage-move-date-group").style.display = "none";
        }

        $("#stage-move-note").value = "";
        overlay.classList.add("open");
    }

    function closeStageMovePrompt() {
        $("#stage-move-overlay").classList.remove("open");
        if (_pendingMove) {
            // Revert the drag if cancelled
            loadPipelineBoard();
            _pendingMove = null;
        }
    }
    $("#stage-move-close").addEventListener("click", closeStageMovePrompt);
    $("#stage-move-cancel").addEventListener("click", closeStageMovePrompt);

    $("#stage-move-form").addEventListener("submit", e => {
        e.preventDefault();
        if (!_pendingMove) return;
        let note = $("#stage-move-note").value.trim();
        const date = $("#stage-move-date").value;
        if (date) note += (note ? " | " : "") + "Start date: " + date;
        doStageMove(_pendingMove.pipelineId, _pendingMove.toStage, note);
        _pendingMove = null;
        $("#stage-move-overlay").classList.remove("open");
    });

    // Pipeline note prompt
    function promptPipelineNote(pipelineId, entry) {
        const note = prompt("Notes for " + (entry.attorney_name || "candidate") + ":", entry.notes || "");
        if (note === null) return;
        fetch(`/api/pipeline/${pipelineId}/notes`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ notes: note }),
        })
        .then(r => r.json())
        .then(() => { showToast("Notes updated"); loadPipelineBoard(); });
    }

    function promptPlacementFee(pipelineId, entry) {
        const current = entry.placement_fee ? Number(entry.placement_fee).toLocaleString() : "0";
        const input = prompt("Placement fee for " + (entry.attorney_name || "candidate") + " ($):", entry.placement_fee || "");
        if (input === null) return;
        const fee = parseFloat(input.replace(/[,$]/g, "")) || 0;
        fetch(`/api/pipeline/${pipelineId}/fee`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ placement_fee: fee }),
        })
        .then(r => r.json())
        .then(() => { showToast("Placement fee updated to $" + fee.toLocaleString()); loadPipelineBoard(); loadDashboard(); });
    }

    function handlePipelineEmail(entry) {
        if (window.JAIDE && window.JAIDE.openEmailComposer) {
            window.JAIDE.openEmailComposer([{
                name: entry.attorney_name,
                email: entry.attorney_email,
                current_firm: entry.attorney_firm,
            }]);
        }
    }

    function handlePipelineFindSimilar(entry) {
        // Navigate to attorney search view and trigger Find Similar
        if (window.JAIDE && window.JAIDE.findSimilarAttorney) {
            if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("attorneys");
            setTimeout(() => {
                window.JAIDE.findSimilarAttorney({
                    id: entry.attorney_id || "",
                    attorney_id: entry.attorney_id || "",
                    name: entry.attorney_name || "",
                    current_firm: entry.attorney_firm || "",
                    email: entry.attorney_email || "",
                });
            }, 150);
        }
    }

    function handlePipelinePitch(entry) {
        const aid = entry.attorney_id || "";
        if (!aid) return;
        // Fetch full attorney data then open pitch modal with job pre-selected
        fetch(`/api/attorneys/${encodeURIComponent(aid)}`)
            .then(r => r.json())
            .then(data => {
                if (data.attorney && window.JAIDE && window.JAIDE.openPitchModal) {
                    window.JAIDE.openPitchModal(data.attorney, entry.id, entry.job_id);
                }
            });
    }

    function handlePipelineRemove(pipelineId, entry) {
        if (!confirm(`Remove ${entry.attorney_name || "candidate"} from pipeline?`)) return;
        fetch(`/api/pipeline/${pipelineId}`, { method: "DELETE" })
            .then(r => r.json())
            .then(() => { showToast("Removed from pipeline"); loadPipelineBoard(); });
    }

    // Pipeline filters
    const plJobFilter = $("#pipeline-filter-job");
    const plEmpFilter = $("#pipeline-filter-employer");
    const plSearch = $("#pipeline-search");
    const plSort = $("#pipeline-sort");
    if (plJobFilter) plJobFilter.addEventListener("change", () => { _currentFilterJobId = plJobFilter.value ? parseInt(plJobFilter.value) : null; loadPipelineBoard(); });
    if (plEmpFilter) plEmpFilter.addEventListener("change", () => loadPipelineBoard());
    if (plSearch) { let d; plSearch.addEventListener("input", () => { clearTimeout(d); d = setTimeout(loadPipelineBoard, 300); }); }
    if (plSort) plSort.addEventListener("change", () => renderKanbanBoard(_pipelineData));

    // Close dropdown menus on outside click
    document.addEventListener("click", () => {
        document.querySelectorAll(".kanban-menu-dropdown.open").forEach(d => d.classList.remove("open"));
    });

    // ================================================================
    // Add to Pipeline Modal (from search results)
    // ================================================================
    let _pipelineCandidates = [];

    const fabAddPipeline = $("#fab-add-pipeline");
    if (fabAddPipeline) {
        fabAddPipeline.addEventListener("click", () => {
            const selected = window.JAIDE && window.JAIDE.getSelectedCandidateObjects ? window.JAIDE.getSelectedCandidateObjects() : [];
            if (!selected.length) { showToast("No candidates selected", "error"); return; }
            openAddToPipelineModal(selected);
        });
    }

    function openAddToPipelineModal(candidates) {
        _pipelineCandidates = candidates;
        const overlay = $("#pipeline-add-overlay");
        $("#pipeline-add-title").textContent = `Add ${candidates.length} candidate${candidates.length > 1 ? "s" : ""} to a job pipeline`;
        loadJobOptions($("#pipeline-add-job"));
        $("#pipeline-add-stage").value = "Identified";
        $("#pipeline-add-notes").value = "";
        const feeInput = $("#pipeline-add-fee");
        if (feeInput) feeInput.value = "";
        $("#pipeline-add-warnings").innerHTML = "";
        $("#pipeline-add-status").textContent = "";
        overlay.classList.add("open");
    }

    function closePipelineAddModal() { $("#pipeline-add-overlay").classList.remove("open"); }
    $("#pipeline-add-close").addEventListener("click", closePipelineAddModal);
    $("#pipeline-add-cancel").addEventListener("click", closePipelineAddModal);
    $("#pipeline-add-overlay").addEventListener("click", e => { if (e.target === $("#pipeline-add-overlay")) closePipelineAddModal(); });

    $("#pipeline-add-form").addEventListener("submit", e => {
        e.preventDefault();
        const jobId = parseInt($("#pipeline-add-job").value);
        if (!jobId) { $("#pipeline-add-status").textContent = "Please select a job"; return; }
        const stage = $("#pipeline-add-stage").value;
        const notes = $("#pipeline-add-notes").value.trim();
        const feeInput = $("#pipeline-add-fee");
        const placementFee = feeInput ? parseFloat(feeInput.value) || 0 : 0;

        const _source = _pipelineCandidates.length ? _pipelineCandidates : (window._pipelineCandidate ? [window._pipelineCandidate] : []);
        const candidates = _source.map(c => ({
            attorney_id: c.id || c.attorney_id || `${c.first_name}_${c.last_name}`.toLowerCase().replace(/\s+/g, "_"),
            name: c.name || `${c.first_name || ""} ${c.last_name || ""}`.trim(),
            current_firm: c.current_firm || c.firm_name || c.firm || "",
            email: c.email || "",
        }));

        fetch("/api/pipeline", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_id: jobId, candidates, stage, notes, placement_fee: placementFee }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) { $("#pipeline-add-status").textContent = data.error; return; }
            const results = data.results || [];
            const added = results.filter(r => r.status === "added").length;
            const existing = results.filter(r => r.status === "exists");
            let msg = `${added} candidate${added !== 1 ? "s" : ""} added to pipeline`;
            if (existing.length) {
                msg += ` (${existing.length} already in pipeline)`;
                const warns = existing.map(e => `${e.name} is already in this pipeline (${e.stage})`);
                $("#pipeline-add-warnings").innerHTML = warns.map(w => `<div class="no-email-warning" style="margin-bottom:4px">${esc(w)}</div>`).join("");
            }
            showToast(msg);
            if (added > 0) {
                closePipelineAddModal();
                loadDashboard();
            }
        });
    });

    // ================================================================
    // Candidate Search Modal (add from pipeline board)
    // ================================================================
    let _searchSelectedCandidates = new Set();

    function openCandidateSearchModal() {
        _searchSelectedCandidates.clear();
        const overlay = $("#candidate-search-overlay");
        $("#candidate-search-input").value = "";
        $("#candidate-search-results").innerHTML = '<p class="no-data" style="padding:12px">Type a name to search...</p>';
        $("#candidate-search-add").disabled = true;
        overlay.classList.add("open");
        $("#candidate-search-input").focus();
    }

    function closeCandidateSearchModal() { $("#candidate-search-overlay").classList.remove("open"); }
    $("#candidate-search-close").addEventListener("click", closeCandidateSearchModal);
    $("#candidate-search-cancel").addEventListener("click", closeCandidateSearchModal);

    let _searchDebounce;
    $("#candidate-search-input").addEventListener("input", () => {
        clearTimeout(_searchDebounce);
        _searchDebounce = setTimeout(() => {
            const q = $("#candidate-search-input").value.trim();
            if (q.length < 2) {
                $("#candidate-search-results").innerHTML = '<p class="no-data" style="padding:12px">Type at least 2 characters...</p>';
                return;
            }
            fetch(`/api/attorneys/search?q=${encodeURIComponent(q)}`)
                .then(r => r.json())
                .then(data => {
                    const results = data.results || [];
                    if (!results.length) {
                        $("#candidate-search-results").innerHTML = '<p class="no-data" style="padding:12px">No attorneys found</p>';
                        return;
                    }
                    let html = '<div class="candidate-search-list">';
                    results.forEach((r, i) => {
                        html += `<label class="candidate-search-item">
                            <input type="checkbox" class="cand-search-cb" data-idx="${i}" value="${esc(r.id)}">
                            <div class="candidate-search-info">
                                <div class="candidate-search-name">${esc(r.name)}</div>
                                <div class="candidate-search-detail">${esc(r.firm)} | ${esc(r.law_school)} ${esc(r.graduation_year)}</div>
                            </div>
                        </label>`;
                    });
                    html += '</div>';
                    $("#candidate-search-results").innerHTML = html;
                    // Store results for selection
                    $("#candidate-search-results")._results = results;
                    // Wire checkboxes
                    $$(".cand-search-cb").forEach(cb => {
                        cb.addEventListener("change", () => {
                            if (cb.checked) _searchSelectedCandidates.add(parseInt(cb.dataset.idx));
                            else _searchSelectedCandidates.delete(parseInt(cb.dataset.idx));
                            $("#candidate-search-add").disabled = _searchSelectedCandidates.size === 0;
                        });
                    });
                });
        }, 300);
    });

    $("#candidate-search-add").addEventListener("click", () => {
        const results = $("#candidate-search-results")._results || [];
        const selected = Array.from(_searchSelectedCandidates).map(i => results[i]).filter(Boolean);
        if (!selected.length) return;
        closeCandidateSearchModal();
        openAddToPipelineModal(selected.map(r => ({
            id: r.id,
            name: r.name,
            current_firm: r.firm,
            email: r.email,
        })));
    });

    // ================================================================
    // Activity Log
    // ================================================================
    let _activityOffset = 0;

    function loadActivityLog(append) {
        if (!append) _activityOffset = 0;
        fetch(`/api/activity?limit=50&offset=${_activityOffset}`)
            .then(r => r.json())
            .then(data => {
                const activities = data.activities || [];
                const total = data.total || 0;
                const feed = $("#activity-feed");
                if (!append) feed.innerHTML = "";
                if (!activities.length && !append) {
                    feed.innerHTML = '<p class="no-data" style="padding:20px">No activity yet. Add candidates to a pipeline to start tracking.</p>';
                    return;
                }
                activities.forEach(a => {
                    const item = document.createElement("div");
                    item.className = "activity-item";

                    let icon, text;
                    if (!a.from_stage) {
                        icon = "plus";
                        text = `<strong>${esc(a.attorney_name)}</strong> added to <strong>${esc(a.job_title)}</strong>${a.employer_name ? " at " + esc(a.employer_name) : ""}`;
                    } else if (a.to_stage === "Placed") {
                        icon = "check";
                        text = `<strong>${esc(a.attorney_name)}</strong> placed at <strong>${esc(a.job_title)}</strong>${a.employer_name ? " at " + esc(a.employer_name) : ""}`;
                    } else if (a.to_stage === "Rejected" || a.to_stage === "Withdrawn") {
                        icon = "x";
                        text = `<strong>${esc(a.attorney_name)}</strong> ${a.to_stage.toLowerCase()} for <strong>${esc(a.job_title)}</strong>`;
                    } else {
                        icon = "arrow";
                        text = `<strong>${esc(a.attorney_name)}</strong> moved from ${esc(a.from_stage)} to <strong>${esc(a.to_stage)}</strong> for ${esc(a.job_title)}${a.employer_name ? " at " + esc(a.employer_name) : ""}`;
                    }
                    if (a.note) text += ` — <em>${esc(a.note)}</em>`;

                    const iconSvg = {
                        plus: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="#2563eb" stroke-width="1.5"/><path d="M8 5v6M5 8h6" stroke="#2563eb" stroke-width="1.5" stroke-linecap="round"/></svg>',
                        arrow: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10M10 5l3 3-3 3" stroke="#059669" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                        check: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="#059669" stroke-width="1.5"/><path d="M5 8l2 2 4-4" stroke="#059669" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                        x: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="#dc2626" stroke-width="1.5"/><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="#dc2626" stroke-width="1.5" stroke-linecap="round"/></svg>',
                    }[icon];

                    item.innerHTML = `
                        <span class="activity-icon">${iconSvg}</span>
                        <div class="activity-text">${text}</div>
                        <span class="activity-time">${timeAgo(a.changed_at)}</span>
                    `;
                    feed.appendChild(item);
                });

                _activityOffset += activities.length;
                // Load more button
                const existingBtn = feed.querySelector(".activity-load-more");
                if (existingBtn) existingBtn.remove();
                if (_activityOffset < total) {
                    const btn = document.createElement("button");
                    btn.className = "btn-secondary activity-load-more";
                    btn.textContent = "Load More";
                    btn.style.margin = "16px auto";
                    btn.style.display = "block";
                    btn.addEventListener("click", () => loadActivityLog(true));
                    feed.appendChild(btn);
                }
            });
    }

    // ================================================================
    // Pipeline Status Indicators on Search Results
    // ================================================================
    // This will be called after search results render to add "In Pipeline" badges
    // Observing the tier-tables for changes
    const tierTablesEl = document.getElementById("tier-tables");
    if (tierTablesEl) {
        const observer = new MutationObserver(() => {
            const candidates = window.JAIDE && window.JAIDE.getCurrentCandidates ? window.JAIDE.getCurrentCandidates() : [];
            if (!candidates.length) return;
            // Gather attorney IDs
            const ids = candidates.map(c => c.id || c.attorney_id || "").filter(Boolean);
            if (!ids.length) return;
            fetch("/api/pipeline/check", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ attorney_ids: ids }),
            })
            .then(r => r.json())
            .then(data => {
                const statusMap = data.status || {};
                // Add badges to rows
                const rows = tierTablesEl.querySelectorAll("tbody tr");
                rows.forEach((row, i) => {
                    if (i >= candidates.length) return;
                    const c = candidates[i];
                    const aid = c.id || c.attorney_id || "";
                    if (!aid || !statusMap[aid]) return;
                    const nameCell = row.querySelector(".cell-name");
                    if (!nameCell || nameCell.querySelector(".pipeline-badge")) return;
                    const pInfo = statusMap[aid][0];
                    const badge = document.createElement("span");
                    badge.className = "pipeline-badge";
                    badge.textContent = "In Pipeline";
                    badge.title = `${pInfo.job_title} — ${pInfo.stage}`;
                    nameCell.appendChild(badge);
                });
            });
        });
        observer.observe(tierTablesEl, { childList: true, subtree: true });
    }

})();
