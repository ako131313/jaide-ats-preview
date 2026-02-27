/* ============================================================
   JAIDE ATS – Candidate Comparison Tool
   ============================================================ */
(function () {
    "use strict";

    // ── Utilities ───────────────────────────────────────────────────
    function esc(s) {
        if (s == null) return "";
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    const $id = (id) => document.getElementById(id);

    // ── State ────────────────────────────────────────────────────────
    let _candidates = [];
    let _context = {};
    let _aiResults = null;

    // ── Init ─────────────────────────────────────────────────────────
    // Scripts are at end of <body>, so DOMContentLoaded has already fired.
    // Call init() directly instead.
    init();

    function init() {
        // Context modal
        $id("compare-context-close")?.addEventListener("click", closeContext);
        $id("compare-context-cancel")?.addEventListener("click", closeContext);
        $id("compare-context-overlay")?.addEventListener("click", (e) => {
            if (e.target === $id("compare-context-overlay")) closeContext();
        });

        $id("compare-quick-btn")?.addEventListener("click", () => {
            captureContext();
            closeContext();
            renderResults(false);
        });

        $id("compare-context-form")?.addEventListener("submit", (e) => {
            e.preventDefault();
            captureContext();
            closeContext();
            renderResults(true);
        });

        // Results overlay
        $id("compare-back-btn")?.addEventListener("click", closeResults);
        $id("compare-pdf-btn")?.addEventListener("click", exportPDF);

        // Delegate copy button (rendered dynamically inside results body)
        $id("compare-results-body")?.addEventListener("click", (e) => {
            if (e.target.closest("#compare-copy-btn")) copyClientSummary();
        });
    }

    // ── Open context modal ───────────────────────────────────────────
    function openCompareModal(candidates, defaultJobId) {
        _candidates = candidates;
        _aiResults = null;

        // Candidate chips
        const preview = $id("compare-candidates-preview");
        if (preview) {
            preview.innerHTML = candidates.map(c => `
                <div class="compare-cand-chip">
                    <div class="compare-cand-chip-name">${esc(c.name || "")}</div>
                    <div class="compare-cand-chip-firm">${esc(c.current_firm || c.firm_name || "")}</div>
                </div>
            `).join("");
        }

        // Load jobs into selector
        const sel = $id("compare-job-select");
        if (sel) {
            sel.innerHTML = '<option value="">No specific job</option>';
            fetch("/api/jobs?status=Active")
                .then(r => r.json())
                .then(data => {
                    (data.jobs || []).forEach(j => {
                        const opt = document.createElement("option");
                        opt.value = j.id;
                        opt.textContent = `${j.title}${j.employer_name ? " — " + j.employer_name : ""}`;
                        sel.appendChild(opt);
                    });
                    // Pre-select the job that surfaced these candidates
                    if (defaultJobId) sel.value = String(defaultJobId);
                })
                .catch(() => {});
        }

        // Reset form state
        const noteEl = $id("compare-custom-note");
        if (noteEl) noteEl.value = "";
        document.querySelectorAll(".compare-priority-item input").forEach(cb => {
            cb.checked = ["compensation", "practice", "culture", "pedigree"].includes(cb.value);
        });

        $id("compare-context-overlay").classList.add("open");
    }

    function closeContext() {
        $id("compare-context-overlay").classList.remove("open");
    }

    function captureContext() {
        const sel = $id("compare-job-select");
        const jobId = sel && sel.value ? parseInt(sel.value) : null;
        const jobTitle = (sel && sel.value)
            ? sel.options[sel.selectedIndex].textContent
            : "";
        const priorities = Array.from(
            document.querySelectorAll(".compare-priority-item input:checked")
        ).map(i => i.value);
        const customNote = ($id("compare-custom-note")?.value || "").trim();
        _context = { jobId, jobTitle, priorities, customNote };
    }

    // ── Render results overlay ───────────────────────────────────────
    function renderResults(startAI) {
        const overlay = $id("compare-results-overlay");
        const body = $id("compare-results-body");
        const titleEl = $id("compare-results-title");

        const names = _candidates.map(c => c.name || "").filter(Boolean).join(" vs. ");
        if (titleEl) titleEl.textContent = `Compare: ${names}`;

        let html = buildQuickCompareSection();

        if (startAI) {
            html += `
            <div class="compare-ai-loading" id="compare-ai-loading">
                <div class="spinner"></div>
                <span>AI is analyzing candidates&hellip; this may take 15–20 seconds.</span>
            </div>`;
        } else if (_aiResults) {
            html += buildAIResultsSection(_aiResults);
        }

        if (body) body.innerHTML = html;
        if (overlay) overlay.classList.add("open");

        if (startAI) callCompareAPI();
    }

    async function callCompareAPI() {
        try {
            const payload = {
                candidates: _candidates.map(c => ({
                    id: c.id || c.attorney_id || 0,
                    name: c.name || "",
                    current_firm: c.current_firm || c.firm_name || "",
                    title: c.title || "",
                    graduation_year: c.graduation_year || c.graduationYear || "",
                    law_school: c.law_school || c.lawSchool || "",
                    bar_admission: c.bar_admission || "",
                    practice_areas: c.practice_areas || "",
                    specialties: c.specialties || c.specialty || "",
                    location: c.location || "",
                    prior_firms: c.prior_firms || "",
                    tier: c.tier || "",
                    match_score: c.match_score || 0,
                    qualifications_summary: c.qualifications_summary || c.rationale || "",
                    is_boomerang: c.is_boomerang || false,
                })),
                job_id: _context.jobId,
                priorities: _context.priorities,
                custom_note: _context.customNote,
            };

            const res = await fetch("/api/compare", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            if (!res.ok) throw new Error(`API error ${res.status}`);

            const data = await res.json();
            _aiResults = data;

            const loading = $id("compare-ai-loading");
            if (loading) {
                loading.outerHTML = buildAIResultsSection(data);
                // Re-bind copy button delegate since innerHTML was replaced
            }
        } catch (err) {
            const loading = $id("compare-ai-loading");
            if (loading) {
                loading.outerHTML = `<div class="compare-error">AI comparison failed. Quick compare is shown above.</div>`;
            }
        }
    }

    function closeResults() {
        $id("compare-results-overlay").classList.remove("open");
    }

    // ── Quick Compare Table ──────────────────────────────────────────
    function buildQuickCompareSection() {
        const rows = [
            ["Current Firm",   c => c.current_firm || c.firm_name || "—"],
            ["Title",          c => c.title || "—"],
            ["Law School",     c => c.law_school || c.lawSchool || "—"],
            ["Class Year",     c => c.graduation_year || c.graduationYear || "—"],
            ["Bar Admission",  c => c.bar_admission || "—"],
            ["Practice Areas", c => c.practice_areas || "—"],
            ["Specialties",    c => c.specialties || c.specialty || "—"],
            ["Location",       c => c.location || "—"],
            ["Prior Firms",    c => c.prior_firms || "—"],
            ["Tier",           c => c.tier || "—"],
            ["Match Score",    c => c.match_score ? String(c.match_score) : "—"],
        ];

        const ths = _candidates.map(c =>
            `<th><div class="compare-th-name">${esc(c.name || "")}</div><div class="compare-th-firm">${esc(c.current_firm || c.firm_name || "")}</div></th>`
        ).join("");

        const bodyRows = rows.map(([label, fn]) => {
            const cells = _candidates.map(c => `<td>${esc(fn(c))}</td>`).join("");
            return `<tr><td class="compare-row-label">${esc(label)}</td>${cells}</tr>`;
        }).join("");

        return `
        <section class="compare-section">
            <h2 class="compare-section-title">Quick Compare</h2>
            <div class="compare-table-wrap">
                <table class="compare-table">
                    <thead><tr><th class="compare-row-label-th"></th>${ths}</tr></thead>
                    <tbody>${bodyRows}</tbody>
                </table>
            </div>
        </section>`;
    }

    // ── AI Results Sections ──────────────────────────────────────────
    function buildAIResultsSection(data) {
        let html = '<div class="compare-ai-divider"><span>AI Deep Analysis</span></div>';

        // Executive Summary
        if (data.executive_summary) {
            html += `
            <section class="compare-section">
                <h2 class="compare-section-title">Executive Summary</h2>
                <div class="compare-executive-summary">${esc(data.executive_summary)}</div>
            </section>`;
        }

        // Ranking Cards
        if (data.ranked_candidates && data.ranked_candidates.length) {
            const medals = ["🥇", "🥈", "🥉", "4th"];
            const cards = data.ranked_candidates.map((r, i) => {
                const medal = medals[i] || `#${r.rank}`;
                const strengths = (r.strengths || []).map(s => `<li>${esc(s)}</li>`).join("");
                const concerns = (r.concerns || []).map(s => `<li>${esc(s)}</li>`).join("");

                const dimScores = Object.entries(r.dimension_scores || {}).map(([k, v]) => `
                    <div class="compare-dim-row">
                        <span class="compare-dim-label">${esc(k.replace(/_/g, " "))}</span>
                        <div class="compare-dim-bar-wrap">
                            <div class="compare-dim-bar" style="width:${Math.min(100, v || 0)}%"></div>
                        </div>
                        <span class="compare-dim-score">${v || 0}</span>
                    </div>`
                ).join("");

                return `
                <div class="compare-rank-card${i === 0 ? " compare-rank-card-first" : ""}">
                    <div class="compare-rank-header">
                        <span class="compare-rank-medal">${medal}</span>
                        <div class="compare-rank-info">
                            <div class="compare-rank-name">${esc(r.name || "")}</div>
                            <div class="compare-rank-headline">${esc(r.headline || "")}</div>
                        </div>
                        <div class="compare-rank-score-badge">${r.overall_score || 0}</div>
                    </div>
                    ${dimScores ? `<div class="compare-dim-scores">${dimScores}</div>` : ""}
                    <div class="compare-rank-lists">
                        ${strengths ? `<div><div class="compare-list-label">Strengths</div><ul class="compare-ul compare-ul-green">${strengths}</ul></div>` : ""}
                        ${concerns ? `<div><div class="compare-list-label">Considerations</div><ul class="compare-ul compare-ul-amber">${concerns}</ul></div>` : ""}
                    </div>
                </div>`;
            }).join("");

            html += `
            <section class="compare-section">
                <h2 class="compare-section-title">Candidate Rankings</h2>
                <div class="compare-rank-cards">${cards}</div>
            </section>`;
        }

        // Head-to-Head Table
        if (data.head_to_head && data.head_to_head.length) {
            const rows = data.head_to_head.map(h =>
                `<tr>
                    <td class="compare-row-label">${esc(h.dimension || "")}</td>
                    <td class="compare-winner-cell">${esc(h.winner || "—")}</td>
                    <td>${esc(h.analysis || "")}</td>
                </tr>`
            ).join("");
            html += `
            <section class="compare-section">
                <h2 class="compare-section-title">Head-to-Head Analysis</h2>
                <div class="compare-table-wrap">
                    <table class="compare-table compare-hth-table">
                        <thead><tr><th>Dimension</th><th>Advantage</th><th>Analysis</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </section>`;
        }

        // Recommendation
        if (data.recommendation) {
            html += `
            <section class="compare-section">
                <h2 class="compare-section-title">Recommendation</h2>
                <div class="compare-recommendation">${esc(data.recommendation)}</div>
            </section>`;
        }

        // Client-Ready Summary
        if (data.client_ready_summary) {
            html += `
            <section class="compare-section">
                <h2 class="compare-section-title">
                    Client-Ready Summary
                    <button class="btn-secondary compare-copy-btn" id="compare-copy-btn">Copy</button>
                </h2>
                <div class="compare-client-summary" id="compare-client-summary-text">${esc(data.client_ready_summary)}</div>
            </section>`;
        }

        return html;
    }

    // ── Copy to Clipboard ────────────────────────────────────────────
    function copyClientSummary() {
        const el = $id("compare-client-summary-text");
        if (!el) return;
        const text = el.innerText || el.textContent || "";
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                const btn = $id("compare-copy-btn");
                if (btn) {
                    btn.textContent = "Copied!";
                    setTimeout(() => { btn.textContent = "Copy"; }, 2000);
                }
            }).catch(fallbackCopy.bind(null, text));
        } else {
            fallbackCopy(text);
        }
    }

    function fallbackCopy(text) {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.cssText = "position:fixed;opacity:0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        const btn = $id("compare-copy-btn");
        if (btn) { btn.textContent = "Copied!"; setTimeout(() => { btn.textContent = "Copy"; }, 2000); }
    }

    // ── PDF Export ───────────────────────────────────────────────────
    async function exportPDF() {
        const btn = $id("compare-pdf-btn");
        if (btn) { btn.disabled = true; btn.textContent = "Generating…"; }
        try {
            const res = await fetch("/api/compare/pdf", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    candidates: _candidates.map(c => ({
                        name: c.name || "",
                        current_firm: c.current_firm || c.firm_name || "",
                        title: c.title || "",
                        graduation_year: c.graduation_year || c.graduationYear || "",
                        law_school: c.law_school || c.lawSchool || "",
                        bar_admission: c.bar_admission || "",
                        practice_areas: c.practice_areas || "",
                        specialties: c.specialties || c.specialty || "",
                        location: c.location || "",
                        tier: c.tier || "",
                        match_score: c.match_score || 0,
                    })),
                    job_context: _context.jobTitle || "",
                    comparison_data: _aiResults || null,
                }),
            });
            if (!res.ok) throw new Error("PDF API error");
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "jaide-comparison.pdf";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (err) {
            alert("PDF export failed. Please try again.");
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = "Export PDF"; }
        }
    }

    // ── Exports ──────────────────────────────────────────────────────
    window.JAIDE = window.JAIDE || {};
    window.JAIDE.openCompareModal = openCompareModal;

})();
