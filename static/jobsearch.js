// ============================================================
// JAIDE ATS – Job Search Module
// ============================================================
(function () {
    "use strict";

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    // State
    let currentJobs = [];
    let selectedJobIds = new Set();
    let lastQuery = "";

    // DOM refs (lazy — elements may not exist immediately)
    function jobResultsContent() { return document.getElementById("job-results-content"); }
    function jobResultsGrid() { return document.getElementById("job-results-grid"); }
    function jobResultsTitle() { return document.getElementById("job-results-title"); }
    function jobResultsCount() { return document.getElementById("job-results-count"); }
    function jobFloatingBar() { return document.getElementById("job-floating-bar"); }
    function jobFabCount() { return document.getElementById("job-fab-count"); }
    function resultsPlaceholder() { return document.getElementById("results-placeholder"); }

    // ---- Helpers ----
    function esc(s) {
        if (s == null) return "";
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function firmInitials(name) {
        if (!name) return "?";
        const words = name.replace(/LLP|LLC|PC|L\.L\.P\.|P\.C\./gi, "").trim().split(/\s+/);
        if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
        return (words[0] || "?").substring(0, 2).toUpperCase();
    }

    function firmColor(name) {
        let h = 0;
        for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
        const colors = ["#2563eb", "#0891b2", "#7c3aed", "#059669", "#0d9488", "#4f46e5", "#0369a1", "#15803d", "#b45309", "#9333ea"];
        return colors[Math.abs(h) % colors.length];
    }

    function statusBadgeClass(status) {
        if (!status) return "jstatus-open";
        const s = status.toLowerCase();
        if (s === "open") return "jstatus-open";
        if (s === "closed") return "jstatus-closed";
        if (s === "filled") return "jstatus-filled";
        return "jstatus-open";
    }

    function truncate(text, maxLen) {
        if (!text || text.length <= maxLen) return text || "";
        return text.substring(0, maxLen) + "...";
    }

    function showToast(msg, type) {
        // Reuse ATS toast if available
        if (window.ATS && window.ATS.showToast) {
            window.ATS.showToast(msg, type);
            return;
        }
        const container = document.getElementById("toast-container");
        if (!container) return;
        const toast = document.createElement("div");
        toast.className = `toast toast-${type || "info"}`;
        toast.textContent = msg;
        container.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add("show"));
        setTimeout(() => {
            toast.classList.remove("show");
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ---- Search ----
    function search(query) {
        lastQuery = query;
        const loader = window.JAIDE.addLoader();

        fetch("/api/jobsearch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query, use_ai: true }),
        })
            .then((r) => r.json())
            .then((data) => {
                loader.remove();
                if (data.error) {
                    window.JAIDE.addBubble(data.error, "assistant");
                    return;
                }
                window.JAIDE.addBubble(data.chat_response || "Search complete.", "assistant");
                currentJobs = data.jobs || [];
                selectedJobIds.clear();
                renderJobResults(data);
                window.JAIDE.collapseForResults();
            })
            .catch((err) => {
                loader.remove();
                window.JAIDE.addBubble("Something went wrong — please try again.", "assistant");
                console.error(err);
            });
    }

    // ---- Render job results ----
    function renderJobResults(data) {
        const content = jobResultsContent();
        const grid = jobResultsGrid();
        const title = jobResultsTitle();
        const count = jobResultsCount();
        const placeholder = resultsPlaceholder();

        if (!content || !grid) return;

        // Hide other views
        if (window.JAIDE.hideAllViews) window.JAIDE.hideAllViews();

        // Show job results
        content.style.display = "block";
        if (placeholder) placeholder.style.display = "none";

        const jobs = data.jobs || [];
        title.textContent = "Job Search Results";
        count.textContent = `${jobs.length} of ${data.total_jobs || "?"} jobs`;

        if (!jobs.length) {
            grid.innerHTML = '<div class="job-results-empty"><p>No jobs found matching your criteria.</p><p class="job-results-empty-sub">Try broadening your search terms.</p></div>';
            updateJobFloatingBar();
            return;
        }

        grid.innerHTML = "";
        jobs.forEach((job, i) => {
            grid.appendChild(createJobCard(job, i));
        });

        updateJobFloatingBar();
    }

    // ---- Job Card ----
    function createJobCard(job, index) {
        const card = document.createElement("div");
        card.className = "job-card";
        card.dataset.jobId = job.id;

        const initials = firmInitials(job.firm_name);
        const color = firmColor(job.firm_name);
        const statusCls = statusBadgeClass(job.status);

        // Practice area pills
        const areas = (job.practice_areas || "").split(",").map(s => s.trim()).filter(Boolean);
        const specs = (job.specialty || "").split(",").map(s => s.trim()).filter(Boolean);
        const allPills = [...areas, ...specs];
        const pillsHtml = allPills.slice(0, 4).map(p =>
            `<span class="job-pill">${esc(p)}</span>`
        ).join("");

        // Experience
        let expHtml = "";
        if (job.min_years || job.max_years) {
            if (job.min_years && job.max_years) {
                expHtml = `<span class="job-exp">${esc(job.min_years)}-${esc(job.max_years)} yrs</span>`;
            } else if (job.min_years) {
                expHtml = `<span class="job-exp">${esc(job.min_years)}+ yrs</span>`;
            } else {
                expHtml = `<span class="job-exp">Up to ${esc(job.max_years)} yrs</span>`;
            }
        }

        // Location (first city only for display)
        const locationShort = (job.job_location || "").split(";")[0].trim();

        // Description preview
        const descPreview = truncate(job.job_description, 200);

        card.innerHTML = `
            <div class="job-card-select">
                <input type="checkbox" class="job-card-cb" data-job-id="${esc(job.id)}" ${selectedJobIds.has(job.id) ? "checked" : ""}>
            </div>
            <div class="job-card-body">
                <div class="job-card-top">
                    <div class="job-card-avatar" style="background:${color}">${esc(initials)}</div>
                    <div class="job-card-header">
                        <div class="job-card-title-row">
                            <a class="job-card-title" data-job-idx="${index}">${esc(job.job_title)}</a>
                            <span class="job-status-pill ${statusCls}">${esc(job.status || "Open")}</span>
                        </div>
                        <div class="job-card-firm">${esc(job.firm_name)}</div>
                        <div class="job-card-meta">
                            ${locationShort ? `<span class="job-meta-item"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>${esc(locationShort)}</span>` : ""}
                            ${expHtml}
                        </div>
                    </div>
                </div>
                ${allPills.length ? `<div class="job-card-pills">${pillsHtml}</div>` : ""}
                ${descPreview ? `<div class="job-card-desc">${esc(descPreview)}</div>` : ""}
                <div class="job-card-actions">
                    <button class="job-card-btn job-card-btn-primary" data-action="find-attorneys" data-job-idx="${index}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
                        Find Attorneys
                    </button>
                    <button class="job-card-btn" data-action="add-ats" data-job-idx="${index}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/></svg>
                        Add to ATS
                    </button>
                    <button class="job-card-btn" data-action="view-detail" data-job-idx="${index}">
                        View Details
                    </button>
                </div>
            </div>`;

        // Wire checkbox
        const cb = card.querySelector(".job-card-cb");
        cb.addEventListener("change", () => {
            if (cb.checked) {
                selectedJobIds.add(job.id);
                card.classList.add("job-card-selected");
            } else {
                selectedJobIds.delete(job.id);
                card.classList.remove("job-card-selected");
            }
            updateJobFloatingBar();
        });

        // Wire title click → detail
        card.querySelector(".job-card-title").addEventListener("click", (e) => {
            e.preventDefault();
            openJobDetail(currentJobs[index]);
        });

        // Wire action buttons
        card.querySelectorAll(".job-card-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const action = btn.dataset.action;
                const idx = parseInt(btn.dataset.jobIdx);
                const j = currentJobs[idx];
                if (!j) return;

                if (action === "find-attorneys") {
                    findAttorneysForJob(j);
                } else if (action === "add-ats") {
                    addJobToATS(j, btn);
                } else if (action === "view-detail") {
                    openJobDetail(j);
                }
            });
        });

        return card;
    }

    // ---- Find Attorneys ----
    function findAttorneysForJob(job) {
        // Build a concise search query from the job
        const parts = [];
        if (job.firm_name) parts.push(job.firm_name);
        if (job.job_title) parts.push(`is hiring for a ${job.job_title}`);
        if (job.job_location) parts.push(`in ${job.job_location}`);
        if (job.practice_areas) parts.push(`Practice areas: ${job.practice_areas}`);
        if (job.specialty) parts.push(`Specialty: ${job.specialty}`);
        if (job.min_years && job.max_years) {
            parts.push(`${job.min_years}-${job.max_years} years of experience required`);
        } else if (job.min_years) {
            parts.push(`${job.min_years}+ years of experience required`);
        }

        // Use full JD if short enough, otherwise use constructed summary
        let searchText;
        if (job.job_description && job.job_description.length <= 3000) {
            searchText = job.job_description;
        } else {
            searchText = parts.join(". ") + ".";
        }

        if (window.JAIDE.triggerAttorneySearch) {
            // Pass firm name directly for exact matching (no fuzzy needed)
            window.JAIDE.triggerAttorneySearch(searchText, job.firm_name || "");
        }
    }

    // ---- Add to ATS ----
    function addJobToATS(job, btnEl) {
        if (btnEl) {
            btnEl.disabled = true;
            btnEl.textContent = "Adding...";
        }

        fetch("/api/jobsearch/add-to-ats", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job: job }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    showToast(`Added "${job.job_title}" at ${data.firm_name} to ATS`, "success");
                    if (btnEl) {
                        btnEl.textContent = "Added";
                        btnEl.classList.add("job-card-btn-done");
                    }
                } else {
                    showToast("Failed to add: " + (data.error || "Unknown error"), "error");
                    if (btnEl) {
                        btnEl.disabled = false;
                        btnEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/></svg> Add to ATS';
                    }
                }
            })
            .catch(() => {
                showToast("Connection error adding to ATS", "error");
                if (btnEl) {
                    btnEl.disabled = false;
                    btnEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/></svg> Add to ATS';
                }
            });
    }

    // ---- Job Detail Modal ----
    function openJobDetail(job) {
        const overlay = document.getElementById("job-detail-overlay");
        const content = document.getElementById("job-detail-content");
        if (!overlay || !content) return;

        const initials = firmInitials(job.firm_name);
        const color = firmColor(job.firm_name);
        const statusCls = statusBadgeClass(job.status);

        const areas = (job.practice_areas || "").split(",").map(s => s.trim()).filter(Boolean);
        const specs = (job.specialty || "").split(",").map(s => s.trim()).filter(Boolean);
        const allPills = [...areas, ...specs];
        const pillsHtml = allPills.map(p => `<span class="job-pill">${esc(p)}</span>`).join("");

        let expText = "";
        if (job.min_years && job.max_years) {
            expText = `${job.min_years}-${job.max_years} years`;
        } else if (job.min_years) {
            expText = `${job.min_years}+ years`;
        }

        // Format locations
        const locations = (job.job_location || "").split(";").map(s => s.trim()).filter(Boolean);
        const locationsHtml = locations.map(l => `<span class="job-detail-location">${esc(l)}</span>`).join("");

        content.innerHTML = `
            <div class="job-detail-header">
                <div class="job-card-avatar job-detail-avatar" style="background:${color}">${esc(initials)}</div>
                <div>
                    <h2 class="job-detail-title">${esc(job.job_title)}</h2>
                    <div class="job-detail-firm">${esc(job.firm_name)}</div>
                </div>
                <span class="job-status-pill ${statusCls}" style="margin-left:auto">${esc(job.status || "Open")}</span>
            </div>

            <div class="job-detail-meta">
                ${locationsHtml ? `<div class="job-detail-field"><strong>Locations</strong><div class="job-detail-locations">${locationsHtml}</div></div>` : ""}
                ${expText ? `<div class="job-detail-field"><strong>Experience</strong><div>${esc(expText)}</div></div>` : ""}
                ${allPills.length ? `<div class="job-detail-field"><strong>Practice Areas</strong><div class="job-card-pills">${pillsHtml}</div></div>` : ""}
                ${job.id ? `<div class="job-detail-field"><strong>Job ID</strong><div>${esc(job.id)}</div></div>` : ""}
                ${job.closed_date ? `<div class="job-detail-field"><strong>Closed Date</strong><div>${esc(job.closed_date)}</div></div>` : ""}
            </div>

            ${job.job_description ? `
                <div class="job-detail-section">
                    <h3>Full Description</h3>
                    <div class="job-detail-description">${esc(job.job_description).replace(/\n/g, "<br>")}</div>
                </div>
            ` : ""}

            <div class="job-detail-actions">
                <button class="btn-primary" id="job-detail-find-attorneys">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
                    Find Attorneys
                </button>
                <button class="btn-secondary" id="job-detail-add-ats">Add to ATS</button>
            </div>`;

        // Wire buttons
        document.getElementById("job-detail-find-attorneys").addEventListener("click", () => {
            overlay.classList.remove("open");
            findAttorneysForJob(job);
        });
        document.getElementById("job-detail-add-ats").addEventListener("click", (e) => {
            addJobToATS(job, e.target);
        });

        overlay.classList.add("open");
    }

    // Close job detail
    document.addEventListener("DOMContentLoaded", () => {
        const closeBtn = document.getElementById("job-detail-close");
        const overlay = document.getElementById("job-detail-overlay");
        if (closeBtn) {
            closeBtn.addEventListener("click", () => overlay.classList.remove("open"));
        }
        if (overlay) {
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) overlay.classList.remove("open");
            });
        }
    });

    // ---- Floating Action Bar ----
    function updateJobFloatingBar() {
        const bar = jobFloatingBar();
        const countEl = jobFabCount();
        if (!bar) return;

        const count = selectedJobIds.size;
        if (count === 0) {
            bar.style.display = "none";
            return;
        }
        bar.style.display = "flex";
        if (countEl) countEl.textContent = `${count} selected`;
    }

    function getSelectedJobs() {
        return currentJobs.filter(j => selectedJobIds.has(j.id));
    }

    // Wire floating bar buttons
    document.addEventListener("DOMContentLoaded", () => {
        const fabFindAttorneys = document.getElementById("job-fab-find-attorneys");
        const fabAddAts = document.getElementById("job-fab-add-ats");
        const fabClear = document.getElementById("job-fab-clear");

        if (fabFindAttorneys) {
            fabFindAttorneys.addEventListener("click", () => {
                const jobs = getSelectedJobs();
                if (!jobs.length) return;
                // Find attorneys for the first selected job
                findAttorneysForJob(jobs[0]);
            });
        }

        if (fabAddAts) {
            fabAddAts.addEventListener("click", () => {
                const jobs = getSelectedJobs();
                if (!jobs.length) return;
                fabAddAts.disabled = true;
                fabAddAts.textContent = "Adding...";

                let completed = 0;
                let errors = 0;
                jobs.forEach(job => {
                    fetch("/api/jobsearch/add-to-ats", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ job: job }),
                    })
                        .then(r => r.json())
                        .then(data => {
                            completed++;
                            if (!data.ok) errors++;
                            if (completed === jobs.length) {
                                fabAddAts.disabled = false;
                                fabAddAts.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/><path d="M12 14v4M10 16h4"/></svg> Add to ATS';
                                if (errors) {
                                    showToast(`Added ${completed - errors} of ${jobs.length} jobs (${errors} failed)`, "error");
                                } else {
                                    showToast(`Added ${completed} job${completed > 1 ? "s" : ""} to ATS`, "success");
                                }
                            }
                        })
                        .catch(() => {
                            completed++;
                            errors++;
                            if (completed === jobs.length) {
                                fabAddAts.disabled = false;
                                fabAddAts.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/><path d="M12 14v4M10 16h4"/></svg> Add to ATS';
                                showToast(`Added ${completed - errors} of ${jobs.length} jobs (${errors} failed)`, "error");
                            }
                        });
                });
            });
        }

        if (fabClear) {
            fabClear.addEventListener("click", () => {
                selectedJobIds.clear();
                const grid = jobResultsGrid();
                if (grid) {
                    grid.querySelectorAll(".job-card-cb").forEach(cb => {
                        cb.checked = false;
                        cb.closest(".job-card").classList.remove("job-card-selected");
                    });
                }
                updateJobFloatingBar();
            });
        }

        // Wire filter/sort controls
        const filterStatus = document.getElementById("job-filter-status-search");
        const sortSelect = document.getElementById("job-sort-search");

        if (filterStatus) {
            filterStatus.addEventListener("change", () => applyJobFilters());
        }
        if (sortSelect) {
            sortSelect.addEventListener("change", () => applyJobFilters());
        }
    });

    function applyJobFilters() {
        const filterStatus = document.getElementById("job-filter-status-search");
        const sortSelect = document.getElementById("job-sort-search");
        const grid = jobResultsGrid();
        if (!grid) return;

        let filtered = [...currentJobs];

        // Filter by status
        if (filterStatus && filterStatus.value) {
            filtered = filtered.filter(j =>
                (j.status || "").toLowerCase() === filterStatus.value.toLowerCase()
            );
        }

        // Sort
        if (sortSelect) {
            const sortBy = sortSelect.value;
            if (sortBy === "firm") {
                filtered.sort((a, b) => (a.firm_name || "").localeCompare(b.firm_name || ""));
            } else if (sortBy === "title") {
                filtered.sort((a, b) => (a.job_title || "").localeCompare(b.job_title || ""));
            }
            // "relevance" keeps original order
        }

        // Re-render
        grid.innerHTML = "";
        filtered.forEach((job, i) => {
            // Find original index for data lookups
            const origIdx = currentJobs.indexOf(job);
            grid.appendChild(createJobCard(job, origIdx >= 0 ? origIdx : i));
        });

        const count = jobResultsCount();
        if (count) count.textContent = `${filtered.length} of ${currentJobs.length} jobs shown`;
    }

    // Handle Escape key for job detail modal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            const overlay = document.getElementById("job-detail-overlay");
            if (overlay && overlay.classList.contains("open")) {
                overlay.classList.remove("open");
            }
        }
    });

    // ---- Expose API ----
    window.JobSearch = {
        search: search,
        getCurrentJobs: () => currentJobs,
        getSelectedJobs: getSelectedJobs,
    };

})();
