// ============================================================
// JAIDE ATS – Firms Module
// ============================================================
(function () {
    "use strict";
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    function esc(s) {
        if (s == null) return "";
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    let _firmsCache = [];
    let _loaded = false;
    let _aiSearchActive = false;

    // 23-color palette for pie chart
    const PIE_COLORS = [
        "#0059FF", "#0791FE", "#f59e0b", "#ef4444", "#8b5cf6",
        "#ec4899", "#14b8a6", "#f97316", "#06b6d4", "#84cc16",
        "#6366f1", "#d946ef", "#0ea5e9", "#10b981", "#e11d48",
        "#a855f7", "#eab308", "#2563eb", "#dc2626", "#7c3aed",
        "#059669", "#db2777", "#ca8a04",
    ];

    // ================================================================
    // Load Firms
    // ================================================================
    function loadFirms() {
        if (_loaded && _firmsCache.length) {
            renderFirmsGrid(_firmsCache);
            return;
        }
        const grid = $("#firms-grid");
        const detail = $("#firm-detail");
        if (detail) detail.style.display = "none";
        if (grid) grid.innerHTML = '<p class="no-data" style="padding:20px">Loading firms...</p>';

        fetch("/api/firms")
            .then(r => r.json())
            .then(data => {
                _firmsCache = data.firms || [];
                _loaded = true;
                renderFirmsGrid(_firmsCache);
                const countEl = $("#firms-count");
                if (countEl) countEl.textContent = `${_firmsCache.length} firms`;
            });
    }

    // Expose for navigation
    window.JAIDE = window.JAIDE || {};
    window.JAIDE.loadFirms = loadFirms;

    // ================================================================
    // Search (client-side + AI toggle)
    // ================================================================
    const firmsSearch = $("#firms-search");
    const aiToggleBtn = $("#btn-ai-firm-search");

    if (aiToggleBtn) {
        aiToggleBtn.addEventListener("click", () => {
            _aiSearchActive = !_aiSearchActive;
            aiToggleBtn.classList.toggle("active", _aiSearchActive);
            if (firmsSearch) {
                firmsSearch.placeholder = _aiSearchActive
                    ? "Describe what firms you're looking for..."
                    : "Search firms...";
            }
        });
    }

    if (firmsSearch) {
        let debounce;
        firmsSearch.addEventListener("input", () => {
            if (_aiSearchActive) return; // AI search triggers on Enter only
            clearTimeout(debounce);
            debounce = setTimeout(() => {
                const q = firmsSearch.value.toLowerCase().trim();
                if (!q) {
                    renderFirmsGrid(_firmsCache);
                    return;
                }
                const filtered = _firmsCache.filter(f =>
                    f.name.toLowerCase().includes(q) ||
                    (f.offices || "").toLowerCase().includes(q) ||
                    (f.top1 || "").toLowerCase().includes(q) ||
                    (f.top2 || "").toLowerCase().includes(q) ||
                    (f.top3 || "").toLowerCase().includes(q)
                );
                renderFirmsGrid(filtered);
            }, 200);
        });

        firmsSearch.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && _aiSearchActive) {
                e.preventDefault();
                const query = firmsSearch.value.trim();
                if (!query) return;
                doAiSearch(query);
            }
        });
    }

    function doAiSearch(query) {
        const grid = $("#firms-grid");
        if (grid) {
            grid.style.display = "grid";
            grid.innerHTML = '<p class="no-data" style="padding:20px">AI is searching firms...</p>';
        }
        const detail = $("#firm-detail");
        if (detail) detail.style.display = "none";

        fetch("/api/firms/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    if (grid) grid.innerHTML = `<p class="no-data" style="padding:20px">${esc(data.error)}</p>`;
                    return;
                }
                const firms = data.firms || [];
                const countEl = $("#firms-count");
                if (countEl) countEl.textContent = `${firms.length} firms found`;
                renderFirmsGrid(firms);
            })
            .catch(() => {
                if (grid) grid.innerHTML = '<p class="no-data" style="padding:20px">AI search failed.</p>';
            });
    }

    // ================================================================
    // Render Firms Grid (with activity badges)
    // ================================================================
    function renderFirmsGrid(firms) {
        const grid = $("#firms-grid");
        const detail = $("#firm-detail");
        if (!grid) return;
        grid.style.display = "grid";
        if (detail) detail.style.display = "none";

        if (!firms.length) {
            grid.innerHTML = '<p class="no-data" style="padding:20px">No firms found.</p>';
            return;
        }

        grid.innerHTML = firms.map(f => {
            const areas = [];
            if (f.top1) areas.push(f.top1.split(":")[0].trim());
            if (f.top2) areas.push(f.top2.split(":")[0].trim());
            if (f.top3) areas.push(f.top3.split(":")[0].trim());
            const pills = areas.map(a => `<span class="firm-area-pill">${esc(a)}</span>`).join("");
            const totalAtty = f.total_attorneys || "\u2014";
            const offices = (f.offices || "").split(";").length;
            const badge = f.has_activity
                ? '<span class="firm-activity-badge">Active Pipeline</span>'
                : '';
            const matchBadge = f.top_matches
                ? `<span class="firm-match-badge">${f.top_matches} top matches</span>`
                : '';
            return `<div class="firm-card" data-fpid="${esc(f.fp_id)}">
                <div class="firm-card-name">${esc(f.name)}${badge}${matchBadge}</div>
                <div class="firm-card-meta">${esc(totalAtty)} attorneys &middot; ${offices} office${offices !== 1 ? "s" : ""}</div>
                <div class="firm-card-areas">${pills}</div>
            </div>`;
        }).join("");

        grid.querySelectorAll(".firm-card").forEach(card => {
            card.addEventListener("click", () => {
                showFirmDetail(card.dataset.fpid);
            });
        });
    }

    // ================================================================
    // Firm Detail
    // ================================================================
    function showFirmDetail(fpId) {
        const grid = $("#firms-grid");
        const detail = $("#firm-detail");
        if (!detail) return;
        grid.style.display = "none";
        detail.style.display = "block";
        detail.innerHTML = '<p class="no-data" style="padding:20px">Loading...</p>';

        fetch(`/api/firms/${fpId}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    detail.innerHTML = `<p class="no-data" style="padding:20px">${esc(data.error)}</p>`;
                    return;
                }
                renderFirmDetail(data.firm);
            });
    }

    // ================================================================
    // Build Pie Chart HTML (CSS conic-gradient)
    // ================================================================
    function buildPieChart(sortedAreas) {
        if (!sortedAreas.length) return '<p class="no-data">No practice area data</p>';

        const total = sortedAreas.reduce((s, a) => s + a[1], 0);
        // Build conic-gradient stops
        let cumPct = 0;
        const stops = [];
        sortedAreas.forEach(([, count], i) => {
            const pct = (count / total) * 100;
            const color = PIE_COLORS[i % PIE_COLORS.length];
            stops.push(`${color} ${cumPct.toFixed(2)}% ${(cumPct + pct).toFixed(2)}%`);
            cumPct += pct;
        });
        const gradient = `conic-gradient(${stops.join(", ")})`;

        const legendItems = sortedAreas.map(([name, count], i) => {
            const pct = ((count / total) * 100).toFixed(1);
            const color = PIE_COLORS[i % PIE_COLORS.length];
            return `<div class="pie-legend-item">
                <span class="pie-legend-swatch" style="background:${color}"></span>
                <span class="pie-legend-name">${esc(name)}</span>
                <span class="pie-legend-count">${count} (${pct}%)</span>
            </div>`;
        }).join("");

        return `<div class="pie-chart-container">
            <div class="pie-chart" style="background:${gradient}"></div>
            <div class="pie-legend">${legendItems}</div>
        </div>`;
    }

    function renderFirmDetail(firm) {
        const detail = $("#firm-detail");
        const totalAtty = firm.total_attorneys || "\u2014";
        const ppp = firm.ppp || "\u2014";
        const offices = (firm.offices || "").split(";").map(s => s.trim()).filter(Boolean);
        const website = firm.website || "";

        // Practice area pie chart
        const areas = firm.practice_areas || {};
        const sortedAreas = Object.entries(areas).sort((a, b) => b[1] - a[1]);
        const chartHtml = buildPieChart(sortedAreas);

        // Office pills
        const officePills = offices.map(o => `<span class="firm-area-pill">${esc(o)}</span>`).join("");

        // Notes
        const notes = firm.notes || [];
        let notesHtml = notes.map(n =>
            `<div class="firm-note" data-id="${n.id}">
                <div class="firm-note-text">${esc(n.note)}</div>
                <div class="firm-note-meta">${esc(n.created_by || "Admin")} &middot; ${n.created_at || ""}
                    <button class="firm-note-delete" data-id="${n.id}" title="Delete">&times;</button>
                </div>
            </div>`
        ).join("");
        if (!notes.length) notesHtml = '<p class="no-data" style="padding:8px">No notes yet.</p>';

        // Contacts
        const contacts = firm.contacts || [];
        let contactsHtml = contacts.map(c =>
            `<div class="firm-contact" data-id="${c.id}">
                <div class="firm-contact-name">${esc(c.name)}${c.title ? ' <span class="firm-contact-title">' + esc(c.title) + '</span>' : ''}</div>
                <div class="firm-contact-info">
                    ${c.email ? '<span>' + esc(c.email) + '</span>' : ''}
                    ${c.phone ? '<span>' + esc(c.phone) + '</span>' : ''}
                    <button class="firm-contact-delete" data-id="${c.id}" title="Delete">&times;</button>
                </div>
            </div>`
        ).join("");
        if (!contacts.length) contactsHtml = '<p class="no-data" style="padding:8px">No contacts yet.</p>';

        detail.innerHTML = `
            <button class="btn-back firm-back" id="firm-back">&larr; Back to Firms</button>
            <div class="firm-detail-header">
                <div>
                    <h2 class="firm-detail-name">${esc(firm.name)}</h2>
                    <div class="firm-detail-meta">
                        ${totalAtty} attorneys &middot; PPP ${esc(ppp)}
                        ${website ? ' &middot; <a href="' + esc(website) + '" target="_blank">' + esc(website) + '</a>' : ''}
                    </div>
                </div>
            </div>

            <!-- Firm detail tabs -->
            <div class="firm-tabs">
                <button class="firm-tab active" data-panel="firm-overview">Overview</button>
                <button class="firm-tab" data-panel="firm-jobs-panel">Jobs</button>
                <button class="firm-tab" data-panel="firm-top-candidates">Top Candidates</button>
                <button class="firm-tab" data-panel="firm-pipeline-panel">Pipeline</button>
                <button class="firm-tab" data-panel="firm-notes-panel">Notes & Contacts</button>
            </div>

            <!-- Overview panel -->
            <div class="firm-panel active" id="firm-overview">
                <div class="firm-overview-grid">
                    <div class="firm-overview-section">
                        <h3>Practice Areas</h3>
                        <div class="firm-chart">${chartHtml}</div>
                    </div>
                    <div class="firm-overview-section">
                        <h3>Offices (${offices.length})</h3>
                        <div class="firm-offices">${officePills || '<p class="no-data">No office data</p>'}</div>
                        <h3 style="margin-top:20px">Key Stats</h3>
                        <div class="firm-stats-grid">
                            <div class="firm-stat"><div class="firm-stat-value">${esc(firm.partners || "\u2014")}</div><div class="firm-stat-label">Partners</div></div>
                            <div class="firm-stat"><div class="firm-stat-value">${esc(firm.counsel || "\u2014")}</div><div class="firm-stat-label">Counsel</div></div>
                            <div class="firm-stat"><div class="firm-stat-value">${esc(firm.associates || "\u2014")}</div><div class="firm-stat-label">Associates</div></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Jobs panel (lazy-loaded) -->
            <div class="firm-panel" id="firm-jobs-panel" style="display:none">
                <p class="no-data" style="padding:12px">Loading jobs...</p>
            </div>

            <!-- Top Candidates panel (lazy-loaded) -->
            <div class="firm-panel" id="firm-top-candidates" style="display:none">
                <p class="no-data" style="padding:12px">Loading top candidates...</p>
            </div>

            <!-- Pipeline panel (lazy-loaded) -->
            <div class="firm-panel" id="firm-pipeline-panel" style="display:none">
                <p class="no-data" style="padding:12px">Loading pipeline...</p>
            </div>

            <!-- Notes & Contacts panel -->
            <div class="firm-panel" id="firm-notes-panel" style="display:none">
                <div class="firm-overview-grid">
                    <div class="firm-overview-section">
                        <h3>Notes</h3>
                        <div class="firm-notes-list" id="firm-notes-list">${notesHtml}</div>
                        <div class="firm-note-form">
                            <textarea id="firm-note-input" rows="2" placeholder="Add a note..."></textarea>
                            <button class="btn-primary btn-sm" id="firm-note-add">Add Note</button>
                        </div>
                    </div>
                    <div class="firm-overview-section">
                        <h3>Contacts</h3>
                        <div class="firm-contacts-list" id="firm-contacts-list">${contactsHtml}</div>
                        <div class="firm-contact-form">
                            <input type="text" id="fc-name" placeholder="Name *" class="firm-contact-input">
                            <input type="text" id="fc-title" placeholder="Title" class="firm-contact-input">
                            <input type="text" id="fc-email" placeholder="Email" class="firm-contact-input">
                            <input type="text" id="fc-phone" placeholder="Phone" class="firm-contact-input">
                            <button class="btn-primary btn-sm" id="firm-contact-add">Add Contact</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Track which lazy panels have been loaded
        const lazyLoaded = { "firm-jobs-panel": false, "firm-pipeline-panel": false, "firm-top-candidates": false };

        // Wire back button
        detail.querySelector("#firm-back").addEventListener("click", () => {
            detail.style.display = "none";
            $("#firms-grid").style.display = "grid";
        });

        // Wire tabs (with lazy loading)
        detail.querySelectorAll(".firm-tab").forEach(tab => {
            tab.addEventListener("click", () => {
                detail.querySelectorAll(".firm-tab").forEach(t => t.classList.remove("active"));
                detail.querySelectorAll(".firm-panel").forEach(p => { p.style.display = "none"; p.classList.remove("active"); });
                tab.classList.add("active");
                const panelId = tab.dataset.panel;
                const panel = detail.querySelector("#" + panelId);
                if (panel) { panel.style.display = "block"; panel.classList.add("active"); }

                // Lazy-load Jobs tab
                if (panelId === "firm-jobs-panel" && !lazyLoaded["firm-jobs-panel"]) {
                    lazyLoaded["firm-jobs-panel"] = true;
                    loadFirmJobs(firm.fp_id, panel);
                }
                // Lazy-load Top Candidates tab
                if (panelId === "firm-top-candidates" && !lazyLoaded["firm-top-candidates"]) {
                    lazyLoaded["firm-top-candidates"] = true;
                    loadTopCandidates(firm.fp_id, firm.name, panel);
                }
                // Lazy-load Pipeline tab
                if (panelId === "firm-pipeline-panel" && !lazyLoaded["firm-pipeline-panel"]) {
                    lazyLoaded["firm-pipeline-panel"] = true;
                    loadFirmPipeline(firm.fp_id, panel);
                }
            });
        });

        // Wire add note
        const noteAddBtn = detail.querySelector("#firm-note-add");
        if (noteAddBtn) {
            noteAddBtn.addEventListener("click", () => {
                const input = detail.querySelector("#firm-note-input");
                const note = input.value.trim();
                if (!note) return;
                fetch(`/api/firms/${firm.fp_id}/notes`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ note }),
                }).then(() => {
                    input.value = "";
                    showFirmDetail(firm.fp_id);
                    // Switch to notes tab
                    setTimeout(() => {
                        const notesTab = detail.querySelector('[data-panel="firm-notes-panel"]');
                        if (notesTab) notesTab.click();
                    }, 100);
                });
            });
        }

        // Wire delete notes
        detail.querySelectorAll(".firm-note-delete").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                fetch(`/api/firms/${firm.fp_id}/notes/${btn.dataset.id}`, { method: "DELETE" })
                    .then(() => {
                        showFirmDetail(firm.fp_id);
                        setTimeout(() => {
                            const notesTab = detail.querySelector('[data-panel="firm-notes-panel"]');
                            if (notesTab) notesTab.click();
                        }, 100);
                    });
            });
        });

        // Wire add contact
        const contactAddBtn = detail.querySelector("#firm-contact-add");
        if (contactAddBtn) {
            contactAddBtn.addEventListener("click", () => {
                const name = detail.querySelector("#fc-name").value.trim();
                if (!name) return;
                const payload = {
                    name,
                    title: detail.querySelector("#fc-title").value.trim(),
                    email: detail.querySelector("#fc-email").value.trim(),
                    phone: detail.querySelector("#fc-phone").value.trim(),
                };
                fetch(`/api/firms/${firm.fp_id}/contacts`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                }).then(() => {
                    showFirmDetail(firm.fp_id);
                    setTimeout(() => {
                        const notesTab = detail.querySelector('[data-panel="firm-notes-panel"]');
                        if (notesTab) notesTab.click();
                    }, 100);
                });
            });
        }

        // Wire delete contacts
        detail.querySelectorAll(".firm-contact-delete").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                fetch(`/api/firms/${firm.fp_id}/contacts/${btn.dataset.id}`, { method: "DELETE" })
                    .then(() => {
                        showFirmDetail(firm.fp_id);
                        setTimeout(() => {
                            const notesTab = detail.querySelector('[data-panel="firm-notes-panel"]');
                            if (notesTab) notesTab.click();
                        }, 100);
                    });
            });
        });
    }

    // ================================================================
    // Lazy-load: Jobs tab
    // ================================================================
    function loadFirmJobs(fpId, panel) {
        fetch(`/api/firms/${fpId}/jobs`)
            .then(r => r.json())
            .then(data => {
                const jobs = data.jobs || [];
                if (!jobs.length) {
                    panel.innerHTML = '<p class="no-data" style="padding:12px">No jobs found for this firm.</p>';
                    return;
                }
                panel.innerHTML = `<div class="firm-jobs-list">
                    ${jobs.map(j => {
                        const statusCls = (j.status || "").toLowerCase().replace(/\s+/g, "-");
                        return `<div class="firm-job-row">
                            <div class="firm-job-title"><a class="firm-entity-link firm-job-link" data-job-id="${esc(j.id || "")}">${esc(j.job_title)}</a></div>
                            <div class="firm-job-meta">
                                ${j.job_location ? '<span>' + esc(j.job_location) + '</span>' : ''}
                                ${j.practice_areas ? '<span>' + esc(j.practice_areas) + '</span>' : ''}
                                <span class="firm-job-status firm-job-status-${statusCls}">${esc(j.status || "Unknown")}</span>
                            </div>
                        </div>`;
                    }).join("")}
                </div>`;
                // Wire job title links → navigate to dashboard pipeline filtered by that job
                panel.querySelectorAll(".firm-job-link").forEach(link => {
                    link.addEventListener("click", (e) => {
                        e.preventDefault();
                        const jobId = link.dataset.jobId;
                        if (jobId && window.JAIDE && window.JAIDE.navigateTo) {
                            window.JAIDE.navigateTo("dashboard");
                            if (window.JAIDE.loadPipelineForJob) {
                                setTimeout(() => window.JAIDE.loadPipelineForJob(parseInt(jobId)), 150);
                            }
                        }
                    });
                });
            })
            .catch(() => {
                panel.innerHTML = '<p class="no-data" style="padding:12px">Failed to load jobs.</p>';
            });
    }

    // ================================================================
    // Lazy-load: Pipeline tab
    // ================================================================
    function loadFirmPipeline(fpId, panel) {
        fetch(`/api/firms/${fpId}/pipeline`)
            .then(r => r.json())
            .then(data => {
                const candidates = data.candidates || [];
                if (!candidates.length) {
                    panel.innerHTML = '<p class="no-data" style="padding:12px">No pipeline candidates for this firm.</p>';
                    return;
                }
                panel.innerHTML = `<div class="firm-pipeline-list">
                    ${candidates.map(c => {
                        const stageCls = (c.stage || "").toLowerCase().replace(/\s+/g, "-");
                        return `<div class="firm-pipeline-row">
                            <div class="firm-pipeline-name"><a class="firm-entity-link firm-attorney-link" data-attorney-id="${esc(String(c.attorney_id || ""))}">${esc(c.attorney_name)}</a></div>
                            <div class="firm-pipeline-meta">
                                <span class="firm-pipeline-stage firm-pipeline-stage-${stageCls}">${esc(c.stage)}</span>
                                ${c.job_title ? '<a class="firm-entity-link firm-pjob-link" data-job-id="' + esc(String(c.job_id || "")) + '">' + esc(c.job_title) + '</a>' : ''}
                                ${c.employer_name ? '<span>' + esc(c.employer_name) + '</span>' : ''}
                                ${c.attorney_firm ? '<span class="firm-pipeline-firm">' + esc(c.attorney_firm) + '</span>' : ''}
                            </div>
                        </div>`;
                    }).join("")}
                </div>`;
                // Wire attorney name links → open profile modal
                panel.querySelectorAll(".firm-attorney-link").forEach(link => {
                    link.addEventListener("click", (e) => {
                        e.preventDefault();
                        const aid = link.dataset.attorneyId;
                        if (aid) openAttorneyById(aid);
                    });
                });
                // Wire job title links → navigate to dashboard pipeline
                panel.querySelectorAll(".firm-pjob-link").forEach(link => {
                    link.addEventListener("click", (e) => {
                        e.preventDefault();
                        const jobId = link.dataset.jobId;
                        if (jobId && window.JAIDE && window.JAIDE.navigateTo) {
                            window.JAIDE.navigateTo("dashboard");
                            if (window.JAIDE.loadPipelineForJob) {
                                setTimeout(() => window.JAIDE.loadPipelineForJob(parseInt(jobId)), 150);
                            }
                        }
                    });
                });
            })
            .catch(() => {
                panel.innerHTML = '<p class="no-data" style="padding:12px">Failed to load pipeline.</p>';
            });
    }

    // ================================================================
    // Lazy-load: Top Candidates tab
    // ================================================================
    function loadTopCandidates(fpId, firmName, panel) {
        fetch(`/api/firms/${fpId}/top-candidates`)
            .then(r => r.json())
            .then(data => {
                const candidates = data.candidates || [];
                const dna = data.dna;
                if (!candidates.length) {
                    panel.innerHTML = '<p class="no-data" style="padding:12px">' +
                        (data.message || "No top candidates found for this firm.") + '</p>';
                    return;
                }

                // DNA summary bar
                let dnaSummary = "";
                if (dna) {
                    const schools = (dna.feeder_schools || []).map(s =>
                        `${esc(s.school)} (${Math.round(s.pct * 100)}%)`).join(", ");
                    const feeders = (dna.feeder_firms || []).map(f =>
                        `${esc(f.firm)} (${f.hires})`).join(", ");
                    const areas = (dna.practice_areas || []).map(a =>
                        `${esc(a.area)} (${Math.round(a.pct * 100)}%)`).join(", ");
                    const cyRange = dna.class_year_range || {};
                    dnaSummary = `<div class="tc-dna-summary">
                        <div class="tc-dna-header">
                            <strong>Hiring DNA</strong>
                            <span class="tc-dna-meta">${dna.total_hires} hires analyzed</span>
                        </div>
                        <div class="tc-dna-pills">
                            ${schools ? `<div class="tc-dna-row"><span class="tc-dna-label">Schools:</span> ${schools}</div>` : ""}
                            ${feeders ? `<div class="tc-dna-row"><span class="tc-dna-label">Feeder firms:</span> ${feeders}</div>` : ""}
                            ${areas ? `<div class="tc-dna-row"><span class="tc-dna-label">Practice areas:</span> ${areas}</div>` : ""}
                            ${cyRange.min ? `<div class="tc-dna-row"><span class="tc-dna-label">Class years:</span> ${cyRange.min}\u2013${cyRange.max} (median ${cyRange.median})</div>` : ""}
                        </div>
                    </div>`;
                }

                // Header with controls
                const header = `<div class="tc-header">
                    <div>
                        <h3 class="tc-title">Top 50 Candidates for ${esc(firmName)}</h3>
                        <p class="tc-subtitle">Matched against hiring patterns \u2014 no specific job required</p>
                    </div>
                    <div class="tc-controls">
                        <select class="tc-sort" id="tc-sort-select">
                            <option value="score">Best Match</option>
                            <option value="year-new">Class Year (newest)</option>
                            <option value="year-old">Class Year (oldest)</option>
                            <option value="firm">Firm Name (A\u2013Z)</option>
                        </select>
                        <button class="tc-refresh-btn" id="tc-refresh" title="Refresh">&#x21bb;</button>
                    </div>
                </div>`;

                // Candidate cards
                panel.innerHTML = dnaSummary + header +
                    '<div class="tc-list" id="tc-list"></div>';
                renderTopCandidateList(candidates, panel.querySelector("#tc-list"));

                // Wire sort
                const sortSel = panel.querySelector("#tc-sort-select");
                sortSel.addEventListener("change", () => {
                    const sorted = [...candidates];
                    const val = sortSel.value;
                    if (val === "year-new") sorted.sort((a, b) => (parseInt(b.graduation_year) || 0) - (parseInt(a.graduation_year) || 0));
                    else if (val === "year-old") sorted.sort((a, b) => (parseInt(a.graduation_year) || 0) - (parseInt(b.graduation_year) || 0));
                    else if (val === "firm") sorted.sort((a, b) => (a.current_firm || "").localeCompare(b.current_firm || ""));
                    else sorted.sort((a, b) => b.match_score - a.match_score);
                    renderTopCandidateList(sorted, panel.querySelector("#tc-list"));
                });

                // Wire refresh
                panel.querySelector("#tc-refresh").addEventListener("click", () => {
                    panel.innerHTML = '<p class="no-data" style="padding:12px">Refreshing...</p>';
                    fetch(`/api/firms/${fpId}/top-candidates/refresh`, { method: "POST" })
                        .then(() => loadTopCandidates(fpId, firmName, panel));
                });
            })
            .catch(() => {
                panel.innerHTML = '<p class="no-data" style="padding:12px">Failed to load top candidates.</p>';
            });
    }

    function renderTopCandidateList(candidates, container) {
        container.innerHTML = candidates.map((c, i) => {
            const scoreColor = c.match_score >= 80 ? "tc-score-green" :
                               c.match_score >= 60 ? "tc-score-blue" : "tc-score-yellow";
            const reasons = (c.match_reasons || []).map(r => {
                let icon = "", cls = "tc-tag-default";
                if (r.includes("School")) { icon = "\ud83d\udcda"; cls = "tc-tag-school"; }
                else if (r === "Boomerang") { icon = "\ud83d\udd04"; cls = "tc-tag-boom"; }
                else if (r.includes("Feeder Firm") || r.includes("Ex-Feeder")) { icon = "\ud83c\udfe2"; cls = "tc-tag-firm"; }
                else if (r.includes("Practice")) { icon = "\ud83d\udccb"; cls = "tc-tag-pa"; }
                else if (r.includes("Specialty")) { icon = "\ud83c\udfaf"; cls = "tc-tag-spec"; }
                else if (r.includes("Location")) { icon = "\ud83d\udccd"; cls = "tc-tag-loc"; }
                else if (r.includes("Class Year")) { icon = "\ud83c\udf93"; cls = "tc-tag-cy"; }
                return `<span class="tc-tag ${cls}">${icon} ${esc(r)}</span>`;
            }).join("");
            const specs = c.specialty ? c.specialty.split(",").slice(0, 3).map(s =>
                `<span class="tc-spec-pill">${esc(s.trim())}</span>`).join("") : "";
            return `<div class="tc-card" data-attorney-id="${esc(c.id)}">
                <div class="tc-score ${scoreColor}">${c.match_score}</div>
                <div class="tc-card-body">
                    <div class="tc-card-name">${esc(c.name)}</div>
                    <div class="tc-card-meta">${esc(c.current_firm)} &middot; ${esc(c.title)}</div>
                    <div class="tc-card-detail">
                        ${c.graduation_year ? "Class of " + esc(c.graduation_year) + " &middot; " : ""}
                        ${esc(c.law_school)}
                        ${c.location ? " &middot; " + esc(c.location) : ""}
                    </div>
                    <div class="tc-card-specs">${specs}</div>
                    <div class="tc-card-reasons">${reasons}</div>
                </div>
                <div class="tc-card-actions">
                    <button class="tc-action-btn tc-view-profile" data-id="${esc(c.id)}" title="View Profile">Profile</button>
                    <button class="tc-action-btn tc-add-pipeline" data-id="${esc(c.id)}" data-name="${esc(c.name)}" title="Add to Pipeline">+ Pipeline</button>
                </div>
            </div>`;
        }).join("");

        // Wire profile links
        container.querySelectorAll(".tc-view-profile").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                openAttorneyById(btn.dataset.id);
            });
        });
        // Wire card click to open profile
        container.querySelectorAll(".tc-card").forEach(card => {
            card.addEventListener("click", () => {
                openAttorneyById(card.dataset.attorneyId);
            });
        });
        // Wire add to pipeline
        container.querySelectorAll(".tc-add-pipeline").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const aid = btn.dataset.id;
                const name = btn.dataset.name;
                if (aid && window.JAIDE && window.JAIDE.openProfile) {
                    openAttorneyById(aid);
                }
            });
        });
    }

    // Helper: fetch attorney by ID and open profile modal
    function openAttorneyById(attorneyId) {
        fetch(`/api/attorneys/${encodeURIComponent(attorneyId)}`)
            .then(r => r.json())
            .then(data => {
                if (data.attorney && window.JAIDE && window.JAIDE.openProfile) {
                    window.JAIDE.openProfile(data.attorney);
                }
            })
            .catch(() => {});
    }

    // ================================================================
    // Navigate to firm by name (for clickable firm names elsewhere)
    // ================================================================
    window.JAIDE.showFirmByName = function (firmName) {
        if (!firmName) return;
        const q = firmName.toLowerCase().trim();
        const match = _firmsCache.find(f => f.name.toLowerCase() === q);
        if (match) {
            if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("firms");
            setTimeout(() => showFirmDetail(match.fp_id), 100);
        } else {
            // Load firms first, then try
            fetch(`/api/firms?search=${encodeURIComponent(firmName)}`)
                .then(r => r.json())
                .then(data => {
                    const firms = data.firms || [];
                    if (firms.length) {
                        if (window.JAIDE.navigateTo) window.JAIDE.navigateTo("firms");
                        setTimeout(() => showFirmDetail(firms[0].fp_id), 100);
                    }
                });
        }
    };

})();
