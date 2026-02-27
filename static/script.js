// ============================================================
// JAIDE ATS – Attorney Search Client
// ============================================================
(function () {
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    // DOM refs
    const chatMessages = $("#chat-messages");
    const chatInput = $("#chat-input");
    const btnSend = $("#btn-send");
    const welcome = $("#welcome");
    const chips = $("#suggestion-chips");
    const jsWelcome = $("#job-search-welcome");
    const jsChips = $("#job-suggestion-chips");
    const resultsPlaceholder = $("#results-placeholder");
    const resultsContent = $("#results-content");
    const chartsFirms = $("#chart-bars-firms");
    const chartsSchools = $("#chart-bars-schools");
    const chartsRow = $("#charts-row");
    const scoringBars = $("#scoring-bars");
    const tierTables = $("#tier-tables");
    const tableSearch = $("#table-search");
    const btnExport = $("#btn-export");
    const profileOverlay = $("#profile-overlay");
    const profileCard = $("#profile-card");
    const resultsTitle = $("#results-title");
    const modeToggle = $("#mode-toggle");
    const modeLabel = $("#mode-label");
    const modeBadge = $("#results-mode-badge");
    const panelDivider = $("#panel-divider");
    const chatPanel = $("#chat-panel");
    const resultsPanel = $("#results-panel");
    const appContainer = $(".app-container");

    let currentCandidates = [];
    let currentSortedCandidates = [];
    let useAI = true;
    let hasResults = false;
    let searchMode = "attorney"; // "attorney" or "job"
    let attySourceFilter = "all"; // "all", "fp", "custom"

    // ---- Selection state ----
    const selectedCandidates = new Set(); // indices into currentSortedCandidates

    // ---- Email templates ----
    const EMAIL_TEMPLATES = {
        initial: {
            subject: "Confidential Opportunity — {firm}",
            body: "Dear {first_name},\n\nI hope this message finds you well. I'm reaching out regarding a confidential opportunity that I believe aligns well with your background and experience.\n\nGiven your work at {firm} and your expertise in {specialties}, I wanted to connect about a role that could be an excellent next step.\n\nWould you be open to a brief, confidential conversation this week?\n\nBest regards,\n{sender_name}\n{sender_title}\n{sender_phone}\n{sender_email}",
        },
        followup: {
            subject: "Following Up — Opportunity Discussion",
            body: "Hi {first_name},\n\nI wanted to follow up on my earlier message about a potential opportunity. I understand your schedule may be busy, but I believe this role could be a strong fit given your background at {firm}.\n\nPlease let me know if you'd like to schedule a brief call at your convenience.\n\nBest,\n{sender_name}\n{sender_title}\n{sender_phone}",
        },
        confidential: {
            subject: "Confidential Inquiry",
            body: "Dear {first_name},\n\nI'm writing on a strictly confidential basis regarding an opportunity that may be of interest. A leading firm is seeking an attorney with precisely the kind of experience you bring — particularly your work in {specialties}.\n\nThis is a highly sensitive search and I would welcome the chance to share more details in a private conversation.\n\nWarm regards,\n{sender_name}\n{sender_title}\n{sender_phone}\n{sender_email}",
        },
    };

    // ---- Drag-to-resize panels ----
    let isDragging = false;
    panelDivider.addEventListener("mousedown", (e) => {
        isDragging = true;
        panelDivider.classList.add("dragging");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        const containerRect = appContainer.getBoundingClientRect();
        const available = containerRect.width - 5;
        const chatW = e.clientX - containerRect.left;
        const pct = Math.max(15, Math.min(70, (chatW / available) * 100));
        chatPanel.style.flex = `0 0 ${pct}%`;
    });
    document.addEventListener("mouseup", () => {
        if (!isDragging) return;
        isDragging = false;
        panelDivider.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
    });

    // ---- Mode toggle ----
    modeToggle.addEventListener("click", () => {
        useAI = !useAI;
        modeLabel.textContent = useAI ? "AI Analysis" : "Quick Match";
        modeToggle.classList.toggle("mode-quick", !useAI);
    });

    // ---- Navigation: view switching ----
    let currentView = "dashboard";

    function navigateTo(viewName) {
        // Hide all views — remove active class AND clear any inline display overrides
        document.querySelectorAll(".view").forEach(v => {
            v.classList.remove("view-active");
            v.style.display = "";
        });
        // Deactivate all tabs
        document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));

        if (viewName === "home" || viewName === "dashboard") {
            // post-login: home → dashboard
            viewName = "dashboard";
        }
        if (viewName === "dashboard") {
            document.getElementById("view-dashboard").classList.add("view-active");
            const tab = document.querySelector('[data-view="dashboard"]');
            if (tab) tab.classList.add("active");
            if (window.JAIDE && window.JAIDE.loadDashboard) window.JAIDE.loadDashboard();
        } else if (viewName === "jobs") {
            document.getElementById("view-search").classList.add("view-active");
            const tab = document.querySelector('[data-view="jobs"]');
            if (tab) tab.classList.add("active");
            if (searchMode !== "job" || currentView !== "jobs") {
                searchMode = "job";
                resetChatToMode("job");
            }
        } else if (viewName === "attorneys") {
            document.getElementById("view-search").classList.add("view-active");
            const tab = document.querySelector('[data-view="attorneys"]');
            if (tab) tab.classList.add("active");
            if (searchMode !== "attorney" || currentView !== "attorneys") {
                searchMode = "attorney";
                resetChatToMode("attorney");
            }
        } else if (viewName === "firms") {
            document.getElementById("view-firms").classList.add("view-active");
            const tab = document.querySelector('[data-view="firms"]');
            if (tab) tab.classList.add("active");
            if (window.JAIDE && window.JAIDE.loadFirms) window.JAIDE.loadFirms();
        } else if (viewName === "pipeline") {
            const pipelineView = document.getElementById("view-pipeline");
            if (pipelineView) pipelineView.classList.add("view-active");
            const tab = document.querySelector('[data-view="pipeline"]');
            if (tab) tab.classList.add("active");
            if (window.JAIDE && window.JAIDE.loadPipeline) window.JAIDE.loadPipeline();
        } else if (viewName === "email") {
            const emailView = document.getElementById("view-email");
            if (emailView) emailView.classList.add("view-active");
            const tab = document.querySelector('[data-view="email"]');
            if (tab) tab.classList.add("active");
            if (window.JAIDE && window.JAIDE.showEmailHub) window.JAIDE.showEmailHub();
        }
        currentView = viewName;
        // Notify dashboard.js when dashboard is activated
        document.dispatchEvent(new CustomEvent("viewActivated", { detail: viewName }));
    }

    // Tab click handlers
    document.querySelectorAll(".nav-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            navigateTo(tab.dataset.view);
        });
    });

    // Logo → dashboard
    const navLogo = document.getElementById("nav-logo");
    if (navLogo) {
        navLogo.addEventListener("click", (e) => {
            e.preventDefault();
            navigateTo("dashboard");
        });
    }

    // Avatar dropdown toggle
    const avatarWrap = document.querySelector(".nav-avatar-wrap");
    const avatarBtn = document.getElementById("nav-avatar");
    if (avatarWrap && avatarBtn) {
        avatarBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            avatarWrap.classList.toggle("open");
        });
        document.addEventListener("click", () => avatarWrap.classList.remove("open"));
    }

    // Dropdown Settings link
    const dropdownSettings = document.getElementById("dropdown-settings");
    if (dropdownSettings) {
        dropdownSettings.addEventListener("click", () => {
            if (avatarWrap) avatarWrap.classList.remove("open");
            openSettings();
        });
    }

    // Logout
    const btnLogout = document.getElementById("btn-logout");
    if (btnLogout) {
        btnLogout.addEventListener("click", () => {
            fetch("/api/logout", { method: "POST" })
                .then(() => window.location.reload())
                .catch(() => window.location.reload());
        });
    }

    // Pipeline empty → attorney search
    const btnPipelineNewSearch = document.getElementById("btn-pipeline-new-search");
    if (btnPipelineNewSearch) {
        btnPipelineNewSearch.addEventListener("click", () => navigateTo("attorneys"));
    }

    // ---- Reset chat to mode ----
    function resetChatToMode(mode) {
        chatMessages.innerHTML = "";
        if (mode === "job") {
            chatMessages.appendChild(jsWelcome);
            jsWelcome.style.display = "flex";
            welcome.style.display = "none";
            chips.style.display = "none";
            if (jsChips) jsChips.style.display = "flex";
            chatInput.placeholder = "Search for legal jobs — e.g. 'Corporate M&A in New York'...";
        } else {
            chatMessages.appendChild(welcome);
            welcome.style.display = "flex";
            if (jsWelcome) jsWelcome.style.display = "none";
            chips.style.display = "flex";
            if (jsChips) jsChips.style.display = "none";
            chatInput.placeholder = "Describe the role you're hiring for, or paste a job description...";
        }

        resultsContent.style.display = "none";
        resultsPlaceholder.style.display = mode === "attorney" ? "flex" : "none";
        $("#sent-emails-view").style.display = "none";
        const jobResults = document.getElementById("job-results-content");
        if (jobResults) jobResults.style.display = "none";
        document.querySelectorAll(".ats-view").forEach(v => v.style.display = "none");
        const jobFab = document.getElementById("job-floating-bar");
        if (jobFab) jobFab.style.display = "none";

        chatInput.value = "";
        chatInput.focus();
        hasResults = false;
        currentCandidates = [];
        currentSortedCandidates = [];
        selectedCandidates.clear();
        updateFloatingBar();
        chatPanel.style.flex = "0 0 35%";
    }

    // ---- Auto-resize textarea ----
    chatInput.addEventListener("input", () => {
        chatInput.style.height = "auto";
        chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
    });

    // ---- Send on Enter (Shift+Enter for newline) ----
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    btnSend.addEventListener("click", sendMessage);

    // ---- Suggestion chips ----
    $$(".chip:not(.job-chip)").forEach((chip) => {
        chip.addEventListener("click", () => {
            chatInput.value = chip.dataset.query;
            chatInput.dispatchEvent(new Event("input"));
            sendMessage();
        });
    });
    $$(".job-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            chatInput.value = chip.dataset.query;
            chatInput.dispatchEvent(new Event("input"));
            sendMessage();
        });
    });

    // ---- Table search/filter ----
    tableSearch.addEventListener("input", () => {
        const q = tableSearch.value.toLowerCase();
        tierTables.querySelectorAll("tbody tr").forEach((row) => {
            row.style.display = row.textContent.toLowerCase().includes(q) ? "" : "none";
        });
    });

    // ---- Export ----
    btnExport.addEventListener("click", exportHTML);

    // ---- Core: send message ----
    function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        welcome.style.display = "none";
        chips.style.display = "none";
        if (jsWelcome) jsWelcome.style.display = "none";
        if (jsChips) jsChips.style.display = "none";

        addBubble(text, "user");
        chatInput.value = "";
        chatInput.style.height = "auto";

        addHistory(text);

        if (searchMode === "job") {
            if (window.JobSearch) {
                window.JobSearch.search(text);
            }
        } else if (hasResults) {
            sendFollowUp(text);
        } else {
            currentJdText = text;
            _exactFirmName = "";  // Manual search — use fuzzy matching
            _skipPatterns = false;
            sendSearch(text);
        }
    }

    function sendSearch(text) {
        // If firm is already known (from job listings), skip preflight
        if (_exactFirmName || _skipPatterns) {
            _doSearch(text);
            return;
        }
        // Preflight: check if JD mentions a firm
        fetch("/api/search/preflight", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jd: text }),
        })
            .then((r) => r.json())
            .then((pf) => {
                if (pf.firm_detected) {
                    _doSearch(text);
                } else {
                    showFirmPrompt(text);
                }
            })
            .catch(() => {
                // On preflight failure, proceed without prompt
                _doSearch(text);
            });
    }

    function _doSearch(text) {
        if (useAI) {
            sendSearchStreaming(text);
        } else {
            sendSearchQuick(text);
        }
    }

    function showFirmPrompt(text) {
        const bubble = addBubble(
            "I didn't detect a specific hiring firm in your description. " +
            "**Is this search for a particular law firm?**",
            "assistant"
        );
        const wrap = document.createElement("div");
        wrap.className = "firm-prompt-buttons";
        wrap.innerHTML = `
            <button class="firm-prompt-btn firm-prompt-yes">Yes — let me specify</button>
            <button class="firm-prompt-btn firm-prompt-no">No — search without firm</button>`;
        bubble.appendChild(wrap);

        const yesBtn = wrap.querySelector(".firm-prompt-yes");
        const noBtn = wrap.querySelector(".firm-prompt-no");

        yesBtn.addEventListener("click", () => {
            wrap.innerHTML = `
                <div class="firm-prompt-input">
                    <input type="text" placeholder="Enter firm name..." class="firm-input-field" />
                    <button class="firm-prompt-btn firm-prompt-go">Search</button>
                </div>`;
            const input = wrap.querySelector(".firm-input-field");
            const goBtn = wrap.querySelector(".firm-prompt-go");
            input.focus();
            function submitFirm() {
                const firm = input.value.trim();
                if (!firm) return;
                wrap.remove();
                _exactFirmName = firm;
                _skipPatterns = false;
                addBubble("Searching for firm: **" + firm + "**", "user");
                sendSearch(text);
            }
            goBtn.addEventListener("click", submitFirm);
            input.addEventListener("keydown", (e) => {
                if (e.key === "Enter") submitFirm();
            });
        });

        noBtn.addEventListener("click", () => {
            wrap.remove();
            _skipPatterns = true;
            sendSearch(text);
        });

        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function sendSearchQuick(text) {
        const loader = addLoader();
        const payload = { jd: text, use_ai: false };
        if (_exactFirmName) payload.firm_name = _exactFirmName;
        if (_skipPatterns) payload.skip_patterns = true;
        fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then((r) => r.json())
            .then((data) => {
                loader.remove();
                if (data.error) { addBubble(data.error, "assistant"); return; }
                addBubble(data.chat_response, "assistant");
                renderResults(data);
                hasResults = true;
            })
            .catch((err) => {
                loader.remove();
                addBubble("Something went wrong — please try again.", "assistant");
                console.error(err);
            });
    }

    function sendSearchStreaming(text) {
        const loader = addAILoader();
        const progressEl = loader.querySelector(".ai-loading-sub");
        let charCount = 0;

        const streamPayload = { jd: text };
        if (_exactFirmName) streamPayload.firm_name = _exactFirmName;
        if (_skipPatterns) streamPayload.skip_patterns = true;
        fetch("/api/search/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(streamPayload),
        }).then((response) => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let metaData = null;

            function pump() {
                return reader.read().then(({ done, value }) => {
                    if (done) {
                        loader.remove();
                        if (!hasResults) {
                            addBubble("No response received — please try again.", "assistant");
                        }
                        return;
                    }
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split("\n");
                    buffer = lines.pop();
                    for (const line of lines) {
                        if (!line.startsWith("data: ")) continue;
                        let evt;
                        try { evt = JSON.parse(line.slice(6)); } catch { continue; }

                        if (evt.type === "meta") {
                            metaData = evt;
                            resultsPlaceholder.style.display = "none";
                            resultsContent.style.display = "block";
                            const meta = evt.meta || {};
                            currentMeta = meta;
                            const displayFirm = meta.matched_firm || meta.firm_name;
                            resultsTitle.textContent = displayFirm ? `Results — ${displayFirm}` : "Search Results";
                            modeBadge.textContent = "AI Analysis";
                            modeBadge.className = "results-mode-badge badge-ai";
                            renderBarCharts(evt.hiring_patterns);
                            renderScoringAlgorithm();
                            tierTables.innerHTML = '<p class="streaming-note">Analyzing candidates...</p>';
                        } else if (evt.type === "chunk") {
                            charCount += evt.text.length;
                            if (progressEl) progressEl.textContent = `Received ${charCount} chars...`;
                        } else if (evt.type === "done") {
                            loader.remove();
                            const result = evt.result;
                            const chatSummary = result.chat_summary || "";
                            addBubble(chatSummary, "assistant");
                            const rawCandidates = result.candidates || [];
                            const profiles = (metaData && metaData.profiles) || [];
                            const profileMap = {};
                            profiles.forEach(p => {
                                const key = (p.name || "").trim().toLowerCase();
                                if (key) profileMap[key] = p;
                            });
                            currentCandidates = rawCandidates.map(c => {
                                const key = (c.name || "").trim().toLowerCase();
                                const orig = profileMap[key];
                                return orig ? { ...orig, ...c } : c;
                            });
                            selectedCandidates.clear();
                            renderCandidateTable(currentCandidates);
                            hasResults = true;
                            collapseForResults();
                        } else if (evt.type === "error") {
                            loader.remove();
                            addBubble("AI analysis failed: " + (evt.message || "Unknown error") + ". Falling back to Quick Match.", "assistant");
                            sendSearchQuick(text);
                        }
                    }
                    return pump();
                });
            }
            return pump();
        }).catch((err) => {
            loader.remove();
            addBubble("Connection error — falling back to Quick Match.", "assistant");
            console.error(err);
            sendSearchQuick(text);
        });
    }

    function sendFollowUp(text) {
        const loader = addLoader();

        fetch("/api/followup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: text }),
        })
            .then((r) => r.json())
            .then((data) => {
                loader.remove();
                if (data.error) {
                    addBubble(data.error, "assistant");
                    return;
                }
                addBubble(data.chat_response, "assistant");
                if (data.updated_candidates) {
                    currentCandidates = data.updated_candidates;
                    selectedCandidates.clear();
                    renderCandidateTable(currentCandidates);
                }
            })
            .catch((err) => {
                loader.remove();
                addBubble("Something went wrong — please try again.", "assistant");
                console.error(err);
            });
    }

    // ---- Chat helpers ----
    function addBubble(text, role) {
        const div = document.createElement("div");
        div.className = `chat-bubble ${role}`;
        div.innerHTML = text
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return div;
    }

    function addLoader() {
        const div = document.createElement("div");
        div.className = "chat-loading";
        div.innerHTML = "<span></span><span></span><span></span>";
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return div;
    }

    function addAILoader() {
        const div = document.createElement("div");
        div.className = "chat-bubble assistant ai-loading";
        div.innerHTML = `
            <div class="ai-loading-content">
                <div class="ai-spinner"></div>
                <span>Analyzing candidates with AI...</span>
            </div>
            <div class="ai-loading-sub">This may take 15-30 seconds for large candidate pools.</div>`;
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return div;
    }

    function addHistory(text) {
        // Search history stored in-memory only (no sidebar)
    }

    // ---- Render results ----
    let currentMeta = null;
    let currentJdText = "";
    let _exactFirmName = "";
    let _skipPatterns = false;

    function renderResults(data) {
        resultsPlaceholder.style.display = "none";
        resultsContent.style.display = "block";
        $("#sent-emails-view").style.display = "none";
        // Hide ATS views and job results
        document.querySelectorAll(".ats-view").forEach(v => v.style.display = "none");
        const jobResultsEl = document.getElementById("job-results-content");
        if (jobResultsEl) jobResultsEl.style.display = "none";

        const meta = data.meta || {};
        currentMeta = meta;
        const displayFirm = meta.matched_firm || meta.firm_name;
        resultsTitle.textContent = displayFirm ? `Results — ${displayFirm}` : "Search Results";

        const isAI = data.mode === "ai";
        modeBadge.textContent = isAI ? "AI Analysis" : "Quick Match";
        modeBadge.className = "results-mode-badge " + (isAI ? "badge-ai" : "badge-quick");

        renderBarCharts(data.hiring_patterns);
        renderScoringAlgorithm();
        currentCandidates = data.candidates || [];
        selectedCandidates.clear();
        renderCandidateTable(currentCandidates);

        // Show Save as Job button
        const saveJobBtn = $("#btn-save-job");
        if (saveJobBtn) {
            saveJobBtn.style.display = "flex";
            saveJobBtn._savedJobId = null;
        }

        collapseForResults();
    }

    // Expose functions globally for ats.js and jobsearch.js
    window.JAIDE = window.JAIDE || {};
    window.JAIDE.getCurrentCandidates = () => currentSortedCandidates;
    window.JAIDE.getSelectedCandidateObjects = getSelectedCandidateObjects;
    window.JAIDE.getCurrentMeta = () => currentMeta;
    window.JAIDE.getCurrentJdText = () => currentJdText;
    window.JAIDE.openEmailComposer = openEmailComposer;
    window.JAIDE.openProfile = openProfile;
    window.JAIDE.showSentEmails = showSentEmails;
    window.JAIDE.addBubble = addBubble;
    window.JAIDE.addLoader = addLoader;
    window.JAIDE.addAILoader = addAILoader;
    window.JAIDE.esc = esc;
    window.JAIDE.collapseForResults = collapseForResults;
    window.JAIDE.getSearchMode = () => searchMode;
    window.JAIDE.setHasResults = (v) => { hasResults = v; };
    window.JAIDE.showSearchView = () => {
        navigateTo(searchMode === "job" ? "jobs" : "attorneys");
    };
    window.JAIDE.navigateTo = navigateTo;
    window.JAIDE.hideAllViews = () => {
        resultsPlaceholder.style.display = "none";
        resultsContent.style.display = "none";
        $("#sent-emails-view").style.display = "none";
        $("#floating-bar").style.display = "none";
        const jobResults = document.getElementById("job-results-content");
        if (jobResults) jobResults.style.display = "none";
        const jobFab = document.getElementById("job-floating-bar");
        if (jobFab) jobFab.style.display = "none";
        const simView = document.getElementById("similar-results-view");
        if (simView) simView.style.display = "none";
        document.querySelectorAll(".ats-view").forEach(v => v.style.display = "none");
    };
    window.JAIDE.showResultsView = () => {
        resultsPlaceholder.style.display = hasResults ? "none" : "flex";
        resultsContent.style.display = hasResults ? "block" : "none";
        document.querySelectorAll(".ats-view").forEach(v => v.style.display = "none");
        $("#sent-emails-view").style.display = "none";
        const jobResults = document.getElementById("job-results-content");
        if (jobResults) jobResults.style.display = "none";
        const simView = document.getElementById("similar-results-view");
        if (simView) simView.style.display = "none";
    };
    window.JAIDE.triggerAttorneySearch = (text, firmName) => {
        // Navigate to attorney search view
        navigateTo("attorneys");

        // Reset chat
        chatMessages.innerHTML = "";
        welcome.style.display = "none";
        chips.style.display = "none";
        if (jsWelcome) jsWelcome.style.display = "none";
        if (jsChips) jsChips.style.display = "none";
        chatInput.placeholder = "Describe the role you're hiring for, or paste a job description...";
        const jobResults = document.getElementById("job-results-content");
        if (jobResults) jobResults.style.display = "none";
        const jobFab = document.getElementById("job-floating-bar");
        if (jobFab) jobFab.style.display = "none";

        // Trigger the search
        hasResults = false;
        currentJdText = text;
        // Store firm name for exact matching (from job listings)
        _exactFirmName = firmName || "";
        _skipPatterns = false;
        addBubble(text.length > 300 ? text.substring(0, 300) + "..." : text, "user");
        addHistory(text);
        sendSearch(text);
    };

    function collapseForResults() {
        chatPanel.style.flex = "0 0 22%";
    }

    // ---- Scoring algorithm display ----
    function renderScoringAlgorithm() {
        scoringBars.innerHTML = "";
        const hasFirm = currentMeta && currentMeta.matched_firm;
        const components = hasFirm ? [
            { label: "Contextual Match",    pts: 50, color: "#2563eb", desc: "JD keywords found in attorney bio, summary, and matters" },
            { label: "Feeder Firm",         pts: 14, color: "#0891b2", desc: "Candidate is at or from a firm the hiring firm recruits from" },
            { label: "Practice Area",       pts: 14, color: "#7c3aed", desc: "Specialty and practice area overlap with JD" },
            { label: "Feeder School",       pts: 10, color: "#8b5cf6", desc: "Attended a top feeder school for the hiring firm" },
            { label: "Credential Bonus",    pts:  8, color: "#059669", desc: "Top 200 firm, Vault 50, clerkships, accolades" },
            { label: "Specialty Match",     pts:  4, color: "#dc2626", desc: "Matches the firm's most common hire specialties" },
        ] : [
            { label: "Contextual Match",    pts: 64, color: "#2563eb", desc: "JD keywords found in attorney bio, summary, and matters" },
            { label: "Practice Area",       pts: 22, color: "#7c3aed", desc: "Specialty and practice area overlap with JD" },
            { label: "Credential Bonus",    pts: 14, color: "#059669", desc: "Top 200 firm, Vault 50, clerkships, accolades" },
        ];
        const maxPts = hasFirm ? 50 : 64;
        components.forEach((c) => {
            const pct = Math.round((c.pts / maxPts) * 100);
            const row = document.createElement("div");
            row.className = "scoring-row";
            row.title = c.desc;
            row.innerHTML = `
                <div class="scoring-label">${esc(c.label)}</div>
                <div class="scoring-track"><div class="scoring-fill" style="width:${pct}%;background:${c.color}"></div></div>
                <div class="scoring-pts">${c.pts} pts</div>`;
            scoringBars.appendChild(row);
        });
    }

    // ---- Bar charts ----
    function renderBarCharts(patterns) {
        chartsFirms.innerHTML = "";
        chartsSchools.innerHTML = "";

        if (!patterns) {
            chartsRow.style.display = "none";
            return;
        }

        const firmItems = patterns.feeder_firms_chart || [];
        const schoolItems = patterns.feeder_schools_chart || [];

        if (!firmItems.length && !schoolItems.length) {
            chartsRow.style.display = "none";
            return;
        }

        chartsRow.style.display = "grid";
        renderBars(chartsFirms, firmItems, "bar-firm");
        renderBars(chartsSchools, schoolItems, "bar-school");
    }

    function renderBars(container, items, fillClass) {
        if (!items.length) {
            container.innerHTML = '<span class="no-data">No data available</span>';
            return;
        }
        const maxCount = Math.max(...items.map((d) => d.count), 1);
        items.forEach((d) => {
            const pct = maxCount > 0 ? Math.round((d.count / maxCount) * 100) : 0;
            const row = document.createElement("div");
            row.className = "bar-row";
            row.innerHTML = `
                <div class="bar-label" title="${esc(d.name)}">${esc(d.name)}</div>
                <div class="bar-track"><div class="bar-fill ${fillClass}" style="width:${pct}%"></div></div>
                ${d.count ? '<div class="bar-value">' + d.count + '</div>' : '<div class="bar-value"></div>'}`;
            container.appendChild(row);
        });
    }

    // ---- Source filter ----
    const attySourceFilterEl = document.getElementById("atty-source-filter");
    if (attySourceFilterEl) {
        attySourceFilterEl.addEventListener("sourceFilterChange", (e) => {
            attySourceFilter = e.detail.source;
            const filtered = attySourceFilter === "all"
                ? currentCandidates
                : currentCandidates.filter(c => (c.source || "fp") === attySourceFilter);
            renderCandidateTable(filtered);
        });
    }

    // Listen for custom record saved/deleted to refresh table
    window.addEventListener("customRecordSaved", () => {
        if (hasResults) renderCandidateTable(
            attySourceFilter === "all" ? currentCandidates : currentCandidates.filter(c => (c.source || "fp") === attySourceFilter)
        );
    });
    window.addEventListener("customRecordDeleted", (e) => {
        if (e.detail.type === "attorney") {
            const deletedId = `custom_${e.detail.id}`;
            currentCandidates = currentCandidates.filter(c => String(c.id) !== deletedId);
            const filtered = attySourceFilter === "all" ? currentCandidates : currentCandidates.filter(c => (c.source || "fp") === attySourceFilter);
            renderCandidateTable(filtered);
        }
    });

    // ---- Candidate table (with checkboxes) ----
    const TIER_ORDER = ["Tier 1+", "Tier 1", "Tier 2", "Tier 3"];

    function renderCandidateTable(candidates) {
        tierTables.innerHTML = "";
        if (!candidates.length) { updateFloatingBar(); return; }

        const tierRank = { "Tier 1+": 0, "Tier 1": 1, "Tier 2": 2, "Tier 3": 3 };
        const sorted = [...candidates].sort((a, b) => {
            const ta = tierRank[a.tier] ?? 99;
            const tb = tierRank[b.tier] ?? 99;
            if (ta !== tb) return ta - tb;
            return (a.rank || 999) - (b.rank || 999);
        });
        currentSortedCandidates = sorted;

        const wrapper = document.createElement("div");
        wrapper.className = "table-wrapper";
        wrapper.innerHTML = `
            <table class="candidate-table">
                <thead>
                    <tr>
                        <th class="col-check"><input type="checkbox" id="select-all" title="Select all"></th>
                        <th class="col-rank">#</th>
                        <th class="col-tier">Tier</th>
                        <th class="col-name">Name</th>
                        <th class="col-why">Assessment</th>
                        <th class="col-firm">Current Firm</th>
                        <th class="col-year">Year</th>
                        <th class="col-school">Law School</th>
                        <th class="col-bar">Bar</th>
                        <th class="col-spec">Specialties</th>
                        <th class="col-actions"></th>
                    </tr>
                </thead>
                <tbody></tbody>
            </table>`;

        const tbody = wrapper.querySelector("tbody");
        sorted.forEach((c, i) => {
            const tr = document.createElement("tr");
            if (selectedCandidates.has(i)) tr.classList.add("row-selected");
            const assessment = c.qualifications_summary || c.rationale || "";
            const bar = c.bar_admission || c.barAdmissions || "";
            const specs = c.specialties || c.specialty || "";
            const firm = c.current_firm || c.firm_name || "";
            const year = c.graduation_year || c.graduationYear || "";
            const school = c.law_school || c.lawSchool || "";
            const name = c.name || `${c.first_name || ""} ${c.last_name || ""}`;
            const priorFirms = c.prior_firms || c.prior_experience || "";
            const tier = c.tier || "Tier 3";
            const tierKey = normalizeTier(tier);

            const isBoomerang = c.is_boomerang === true;
            tr.innerHTML = `
                <td class="cell-check"><input type="checkbox" class="row-cb" data-idx="${i}" ${selectedCandidates.has(i) ? "checked" : ""}></td>
                <td class="cell-rank">${i + 1}</td>
                <td><span class="tier-badge tb-${tierKey}">${esc(tier)}</span>${isBoomerang ? '<span class="boomerang-badge" title="Previously worked at the hiring firm">Boomerang</span>' : ''}${c.source === 'custom' ? '<span class="source-badge source-badge-custom">Custom</span>' : '<span class="source-badge source-badge-fp">FP</span>'}</td>
                <td class="cell-name">
                    <div class="name-primary"><a class="name-link" data-idx="${i}">${esc(name)}</a></div>
                    ${priorFirms ? '<div class="name-prior" title="' + esc(priorFirms) + '">Prior: ' + esc(priorFirms) + '</div>' : ''}
                </td>
                <td class="cell-assessment">${esc(assessment)}</td>
                <td>${firm ? '<a class="firm-link" data-firm="' + esc(firm) + '">' + esc(firm) + '</a>' : ''}</td>
                <td class="cell-center">${esc(year)}</td>
                <td>${esc(school)}</td>
                <td class="cell-center">${esc(bar)}</td>
                <td class="cell-spec" title="${esc(specs)}">${esc(specs)}</td>
                <td class="cell-actions"><button class="btn-pitch" data-idx="${i}" title="Generate Pitch PDF"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></button><button class="btn-find-similar" data-idx="${i}" title="Find Similar Attorneys"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M20 8v6M23 11h-6"/></svg></button><button class="btn-add-worklist" data-idx="${i}" title="Add to Worklist"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg></button>${c.source === 'custom' ? `<button class="btn-edit-custom" data-idx="${i}" title="Edit"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button><button class="btn-delete-custom" data-idx="${i}" title="Delete"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg></button>` : ''}</td>`;

            // Wire checkbox
            const cb = tr.querySelector(".row-cb");
            cb.addEventListener("change", () => {
                if (cb.checked) {
                    selectedCandidates.add(i);
                    tr.classList.add("row-selected");
                } else {
                    selectedCandidates.delete(i);
                    tr.classList.remove("row-selected");
                }
                updateSelectAll(wrapper);
                updateFloatingBar();
            });

            tr.querySelector(".name-link").addEventListener("click", (e) => {
                e.preventDefault();
                openProfile(sorted[i]);
            });
            const firmLink = tr.querySelector(".firm-link");
            if (firmLink) {
                firmLink.addEventListener("click", (e) => {
                    e.preventDefault();
                    if (window.JAIDE && window.JAIDE.showFirmByName) window.JAIDE.showFirmByName(firmLink.dataset.firm);
                });
            }
            const simBtn = tr.querySelector(".btn-find-similar");
            if (simBtn) {
                simBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    findSimilarAttorney(sorted[i]);
                });
            }
            const pitchBtn = tr.querySelector(".btn-pitch");
            if (pitchBtn) {
                pitchBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (window.JAIDE && window.JAIDE.openPitchModal) window.JAIDE.openPitchModal(sorted[i]);
                });
            }
            const addWorklistBtn = tr.querySelector(".btn-add-worklist");
            if (addWorklistBtn) {
                addWorklistBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const cand = sorted[parseInt(addWorklistBtn.dataset.idx)];
                    if (window.JAIDE && window.JAIDE.openAddToWorklist) window.JAIDE.openAddToWorklist(cand);
                });
            }
            const editCustomBtn = tr.querySelector(".btn-edit-custom");
            if (editCustomBtn) {
                editCustomBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const cand = sorted[parseInt(editCustomBtn.dataset.idx)];
                    const rawId = String(cand.id || "").replace("custom_", "");
                    fetch(`/api/custom/attorneys/${rawId}`)
                        .then(r => r.json())
                        .then(data => {
                            if (data.attorney && window.JAIDE && window.JAIDE.openCustomAttorneyModal) {
                                window.JAIDE.openCustomAttorneyModal(data.attorney);
                            }
                        });
                });
            }
            const deleteCustomBtn = tr.querySelector(".btn-delete-custom");
            if (deleteCustomBtn) {
                deleteCustomBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const cand = sorted[parseInt(deleteCustomBtn.dataset.idx)];
                    const rawId = String(cand.id || "").replace("custom_", "");
                    if (window.JAIDE && window.JAIDE.deleteCustomRecord) {
                        window.JAIDE.deleteCustomRecord("attorneys", rawId, cand.name || "this candidate");
                    }
                });
            }
            tbody.appendChild(tr);
        });

        // Select-all handler
        const selectAll = wrapper.querySelector("#select-all");
        selectAll.addEventListener("change", () => {
            const cbs = wrapper.querySelectorAll(".row-cb");
            cbs.forEach((cb) => {
                const idx = parseInt(cb.dataset.idx);
                cb.checked = selectAll.checked;
                if (selectAll.checked) {
                    selectedCandidates.add(idx);
                    cb.closest("tr").classList.add("row-selected");
                } else {
                    selectedCandidates.delete(idx);
                    cb.closest("tr").classList.remove("row-selected");
                }
            });
            updateFloatingBar();
        });

        tierTables.appendChild(wrapper);
        updateFloatingBar();
    }

    function updateSelectAll(wrapper) {
        const selectAll = wrapper.querySelector("#select-all");
        if (!selectAll) return;
        const cbs = wrapper.querySelectorAll(".row-cb");
        const allChecked = cbs.length > 0 && Array.from(cbs).every(cb => cb.checked);
        selectAll.checked = allChecked;
    }

    // ---- Floating action bar ----
    function updateFloatingBar() {
        const bar = $("#floating-bar");
        const count = selectedCandidates.size;
        if (count === 0) {
            bar.style.display = "none";
            return;
        }
        bar.style.display = "flex";
        $("#fab-count").textContent = `${count} selected`;
        const compareBtn = document.getElementById("fab-compare");
        if (compareBtn) compareBtn.style.display = (count >= 2 && count <= 4) ? "" : "none";
    }

    function getSelectedCandidateObjects() {
        return Array.from(selectedCandidates)
            .sort((a, b) => a - b)
            .map(i => currentSortedCandidates[i])
            .filter(Boolean);
    }

    // Floating bar buttons
    $("#fab-send-email").addEventListener("click", () => {
        openEmailComposer(getSelectedCandidateObjects());
    });

    $("#fab-export").addEventListener("click", () => {
        const selected = getSelectedCandidateObjects();
        if (selected.length) exportHTMLForCandidates(selected);
    });

    $("#fab-clear").addEventListener("click", () => {
        selectedCandidates.clear();
        tierTables.querySelectorAll(".row-cb").forEach(cb => {
            cb.checked = false;
            cb.closest("tr").classList.remove("row-selected");
        });
        const selectAll = tierTables.querySelector("#select-all");
        if (selectAll) selectAll.checked = false;
        updateFloatingBar();
    });

    document.getElementById("fab-compare")?.addEventListener("click", () => {
        const selected = getSelectedCandidateObjects();
        if (selected.length >= 2 && window.JAIDE && window.JAIDE.openCompareModal) {
            window.JAIDE.openCompareModal(selected, window._compareDefaultJobId || null);
        }
    });

    // ---- Tier helpers ----
    function normalizeTier(tier) {
        if (!tier) return "3";
        const t = tier.replace(/^Tier\s*/i, "").trim();
        if (t === "1+") return "1plus";
        if (t === "1") return "1";
        if (t === "2") return "2";
        return "3";
    }

    function tierClass(key) {
        return {
            "1plus": "tier-1plus",
            "1": "tier-1",
            "2": "tier-2",
            "3": "tier-3",
        }[key] || "tier-3";
    }

    // ---- Export ----
    function exportHTML() {
        exportHTMLForCandidates(currentCandidates);
    }

    function exportHTMLForCandidates(candidates) {
        const tierRank = { "Tier 1+": 0, "Tier 1": 1, "Tier 2": 2, "Tier 3": 3 };
        const sorted = [...candidates].sort((a, b) => {
            const ta = tierRank[a.tier] ?? 99;
            const tb = tierRank[b.tier] ?? 99;
            if (ta !== tb) return ta - tb;
            return (a.rank || 999) - (b.rank || 999);
        });
        let rows = "";
        sorted.forEach((c, i) => {
            const name = c.name || `${c.first_name || ""} ${c.last_name || ""}`;
            const firm = c.current_firm || c.firm_name || "";
            const year = c.graduation_year || c.graduationYear || "";
            const school = c.law_school || c.lawSchool || "";
            const bar = c.bar_admission || c.barAdmissions || "";
            const specs = c.specialties || c.specialty || "";
            const assess = c.qualifications_summary || c.rationale || "";
            const tier = c.tier || "Tier 3";
            rows += `<tr><td>${i + 1}</td><td>${esc(tier)}</td><td><strong>${esc(name)}</strong></td><td class="assess">${esc(assess)}</td><td>${esc(firm)}</td><td>${esc(year)}</td><td>${esc(school)}</td><td>${esc(bar)}</td><td>${esc(specs)}</td></tr>`;
        });
        const html = `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>JAIDE ATS Report</title>
<style>
body{font-family:'Inter',system-ui,sans-serif;margin:40px auto;max-width:1200px;color:#151515;background:#fff;font-size:13px}
h1{color:#0059FF;font-size:22px;margin-bottom:4px}
.meta{color:#696969;font-size:13px;margin-bottom:24px}
table{width:100%;border-collapse:collapse;margin-bottom:20px}
th{background:#F6F6F6;padding:8px 10px;text-align:left;border-bottom:2px solid #EDEDED;font-weight:600;font-size:12px}
td{padding:8px 10px;border-bottom:1px solid #F6F6F6;vertical-align:top;font-size:12px}
.assess{font-size:12px;color:#696969;max-width:300px;line-height:1.5}
</style></head><body>
<h1>JAIDE ATS — Candidate Report</h1>
<p class="meta">Generated ${new Date().toLocaleString()}</p>
<table><thead><tr><th>#</th><th>Tier</th><th>Name</th><th>Assessment</th><th>Firm</th><th>Year</th><th>Law School</th><th>Bar</th><th>Specialties</th></tr></thead><tbody>${rows}</tbody></table>
</body></html>`;
        const blob = new Blob([html], { type: "text/html" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "jaide-ats-report.html";
        a.click();
        URL.revokeObjectURL(a.href);
    }

    // ---- Profile modal ----
    profileOverlay.addEventListener("click", (e) => {
        if (e.target === profileOverlay) closeProfile();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            if ($("#composer-overlay").classList.contains("open")) closeEmailComposer();
            else if ($("#settings-overlay").classList.contains("open")) closeSettings();
            else if (profileOverlay.classList.contains("open")) closeProfile();
        }
    });

    function closeProfile() {
        profileOverlay.classList.remove("open");
        profileCard.innerHTML = "";
    }

    function avatarColor(name) {
        let h = 0;
        for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
        const colors = ["#2563eb","#0891b2","#7c3aed","#059669","#0d9488","#4f46e5","#0369a1","#15803d"];
        return colors[Math.abs(h) % colors.length];
    }

    function formatLocation(loc) {
        if (!loc) return "";
        const parts = loc.split("-");
        if (parts.length === 2) return parts[1].trim() + ", " + parts[0].trim();
        return loc;
    }

    function shortYear(y) {
        if (!y) return "";
        const s = String(y);
        return s.length === 4 ? "'" + s.slice(2) : s;
    }

    function openProfile(c) {
        const name = c.name || `${c.first_name || ""} ${c.last_name || ""}`.trim();
        const initials = ((c.first_name || name.split(" ")[0] || "").charAt(0) + (c.last_name || name.split(" ").pop() || "").charAt(0)).toUpperCase();
        const yr = c.graduation_year || c.graduationYear || "";
        const firm = c.current_firm || c.firm_name || "";
        const titleRole = c.title || "";
        const photo = c.photo_url || "";
        const email = c.email || "";
        const phone = c.phone_primary || "";
        const linkedin = c.linkedinURL || "";
        const profileURL = c.profileURL || "";
        const bio = c.attorneyBio || "";
        const location = formatLocation(c.location || "");
        const lawSchool = c.law_school || c.lawSchool || "";
        const undergrad = c.undergraduate || "";
        const llmSchool = c.llm_school || "";
        const llmSpec = c.llm_specialty || "";
        const llmYear = c.llm_year || "";
        const honors = c.raw_acknowledgements || "";
        const bar = c.bar_admission || c.barAdmissions || "";
        const langs = c.languages || "";
        const clerkships = c.clerkships || "";
        const prior = c.prior_firms || c.prior_experience || "";
        const practiceAreas = c.practice_areas || "";
        const specs = c.specialties || c.specialty || "";
        const syncDate = c.scraped_on || "";
        const aid = String(c.id || c.attorney_id || "");

        const photoHtml = photo
            ? `<img class="profile-photo" src="${esc(photo)}" alt="${esc(name)}" onerror="this.outerHTML='<div class=\\'profile-avatar\\' style=\\'background:${avatarColor(name)}\\'>${esc(initials)}</div>'">`
            : `<div class="profile-avatar" style="background:${avatarColor(name)}">${esc(initials)}</div>`;

        let contactHtml = "";
        if (phone) contactHtml += `<div class="profile-contact-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.79 19.79 0 012.12 4.18 2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/></svg>${esc(phone)}</div>`;
        if (email) contactHtml += `<div class="profile-contact-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-10 7L2 7"/></svg><a href="mailto:${esc(email)}">${esc(email)}</a></div>`;
        if (location) contactHtml += `<div class="profile-contact-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>${esc(location)}</div>`;
        if (linkedin) contactHtml += `<div class="profile-contact-row"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg><a href="${esc(linkedin)}" target="_blank">LinkedIn Profile</a></div>`;

        function pills(str) {
            if (!str) return "";
            return str.split(/[,;]+/).map(s => s.trim()).filter(Boolean).map(s => `<span class="profile-pill">${esc(s)}</span>`).join("");
        }

        // Profile tab: fields + bio
        let fieldsHtml = "";
        if (practiceAreas) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Practice Areas</div><div class="profile-pills">${pills(practiceAreas)}</div></div>`;
        if (specs) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Specialties</div><div class="profile-pills">${pills(specs)}</div></div>`;
        if (lawSchool) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Law School</div><div class="profile-field-value">${esc(lawSchool)}${yr ? " " + shortYear(yr) : ""}</div></div>`;
        if (undergrad) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Undergraduate</div><div class="profile-field-value">${esc(undergrad)}</div></div>`;
        if (llmSchool) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">LLM</div><div class="profile-field-value">${esc(llmSchool)}${llmSpec ? " — " + esc(llmSpec) : ""}${llmYear ? " " + shortYear(llmYear) : ""}</div></div>`;
        if (honors) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Honors / Accolades</div><div class="profile-field-value">${esc(honors)}</div></div>`;
        if (bar) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Bar Admissions</div><div class="profile-pills">${pills(bar)}</div></div>`;
        if (langs) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Languages</div><div class="profile-field-value">${esc(langs)}</div></div>`;
        if (clerkships) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Clerkships</div><div class="profile-field-value">${esc(clerkships)}</div></div>`;
        if (prior) fieldsHtml += `<div class="profile-field"><div class="profile-field-label">Prior Experience</div><div class="profile-field-value">${esc(prior)}</div></div>`;

        // Bio — full display; expand button if >2000 chars
        let bioHtml = "";
        if (bio) {
            const BIO_LIMIT = 2000, BIO_SHOW = 1500;
            if (bio.length > BIO_LIMIT) {
                bioHtml = `
                    <div class="profile-section">
                        <div class="profile-field-label">Biography</div>
                        <div class="profile-bio-full">${esc(bio.slice(0, BIO_SHOW))}<span id="profile-bio-rest" style="display:none">${esc(bio.slice(BIO_SHOW))}</span></div>
                        <button class="profile-bio-toggle" id="profile-bio-toggle">Show full bio &#9660;</button>
                    </div>`;
            } else {
                bioHtml = `
                    <div class="profile-section">
                        <div class="profile-field-label">Biography</div>
                        <div class="profile-bio-full">${esc(bio)}</div>
                    </div>`;
            }
        }

        profileCard.innerHTML = `
            <button class="profile-close" id="profile-close-btn">&times;</button>
            <div class="profile-body">
                <div class="profile-left">
                    <div class="profile-photo-center">${photoHtml}</div>
                    <div class="profile-name-center">
                        <div class="profile-name">${esc(name)}${yr ? ' <span class="year">' + shortYear(yr) + '</span>' : ''}</div>
                        <div class="profile-firm-row">
                            ${profileURL ? '<a class="profile-firm-link" href="' + esc(profileURL) + '" target="_blank">' + esc(firm) + '</a>' : (firm ? '<span class="profile-firm-link">' + esc(firm) + '</span>' : '')}
                            ${titleRole ? '<span class="profile-title-badge">' + esc(titleRole) + '</span>' : ''}
                            ${c.is_boomerang === true ? '<span class="boomerang-badge" title="Previously worked at the hiring firm">Boomerang</span>' : ''}
                        </div>
                    </div>
                    <div class="profile-action-buttons">
                        <button class="btn-add-pipeline-profile" id="btn-profile-add-pipeline">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                            Add to Pipeline
                        </button>
                        <button class="btn-find-similar-profile" id="btn-profile-find-similar">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M20 8v6M23 11h-6"/></svg>
                            Find Similar
                        </button>
                        <button class="btn-pitch btn-pitch-profile" id="btn-profile-pitch">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                            Generate Pitch
                        </button>
                        <button class="btn-secondary btn-sm btn-pitch-firm" id="btn-profile-pitch-firm">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16"/></svg>
                            Pitch a Firm
                        </button>
                        ${email ? `<button class="btn-secondary btn-sm" id="btn-profile-send-email">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-10 7L2 7"/></svg>
                            Send Email
                        </button>` : ""}
                        <button class="btn-secondary btn-sm" id="btn-profile-add-worklist">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
                            Add to Worklist
                        </button>
                        <button class="btn-secondary btn-sm" id="btn-profile-create-task">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18M9 16l2 2 4-4"/></svg>
                            Create Task
                        </button>
                    </div>
                    ${contactHtml ? '<div class="profile-contact">' + contactHtml + '</div>' : ''}
                    <div class="profile-email-history" id="profile-email-history-compact">
                        <div class="profile-email-history-header">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-10 7L2 7"/></svg>
                            Recent Emails
                        </div>
                        <div class="profile-email-history-body">Loading...</div>
                    </div>
                </div>
                <div class="profile-right">
                    <div class="profile-tabs-bar">
                        <button class="profile-tab active" data-tab="profile">Profile</button>
                        <button class="profile-tab" data-tab="experience">Experience</button>
                        <button class="profile-tab" data-tab="correspondence">Correspondence</button>
                        <button class="profile-tab" data-tab="matched-jobs">Matched Jobs</button>
                    </div>
                    <div class="profile-tab-panels">
                        <div class="profile-tab-panel active" data-panel="profile">
                            ${fieldsHtml || ""}
                            ${bioHtml}
                            ${!fieldsHtml && !bioHtml ? '<p class="no-data">No additional details available</p>' : ""}
                            ${syncDate ? '<div class="profile-sync-date">Last synced: ' + esc(syncDate) + '</div>' : ''}
                        </div>
                        <div class="profile-tab-panel" data-panel="experience">
                            <div class="profile-experience-placeholder">
                                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#B4B4B4" stroke-width="1.5"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/></svg>
                                <p>Employment history not yet available.</p>
                                <p class="profile-exp-sub">Connect to LinkedIn or upload a resume to populate work history.</p>
                            </div>
                        </div>
                        <div class="profile-tab-panel" data-panel="correspondence">
                            <div class="tab-loading">Loading correspondence…</div>
                        </div>
                        <div class="profile-tab-panel" data-panel="matched-jobs">
                            <div class="tab-loading">Loading matched jobs…</div>
                        </div>
                    </div>
                </div>
            </div>`;

        // Tab switching with lazy load
        profileCard.querySelectorAll(".profile-tab").forEach(tab => {
            tab.onclick = function () {
                profileCard.querySelectorAll(".profile-tab").forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                const panelName = tab.dataset.tab;
                profileCard.querySelectorAll(".profile-tab-panel").forEach(p => p.classList.remove("active"));
                profileCard.querySelector(`[data-panel="${panelName}"]`).classList.add("active");
                if (panelName === "correspondence" && !tab._loaded) {
                    tab._loaded = true;
                    _loadCorrespondenceTab(aid, email);
                } else if (panelName === "matched-jobs" && !tab._loaded) {
                    tab._loaded = true;
                    _loadMatchedJobsTab(aid);
                }
            };
        });

        // Bio expand
        const bioToggle = profileCard.querySelector("#profile-bio-toggle");
        if (bioToggle) {
            bioToggle.addEventListener("click", () => {
                const rest = profileCard.querySelector("#profile-bio-rest");
                if (rest) {
                    const visible = rest.style.display !== "none";
                    rest.style.display = visible ? "none" : "inline";
                    bioToggle.innerHTML = visible ? "Show full bio &#9660;" : "Show less &#9650;";
                }
            });
        }

        // Compact email history
        _loadCompactEmailHistory(aid, email);

        $("#profile-close-btn").addEventListener("click", closeProfile);

        $("#btn-profile-add-pipeline").addEventListener("click", () => {
            document.getElementById("pipeline-add-overlay").classList.add("open");
            document.getElementById("pipeline-add-title").textContent = "Add " + name + " to Pipeline";
            if (window.JAIDE && window.JAIDE.loadJobOptions) window.JAIDE.loadJobOptions(document.getElementById("pipeline-add-job"));
            window._pipelineCandidate = { id: c.id || c.attorney_id || 0, name, current_firm: firm, email };
        });

        $("#btn-profile-find-similar").addEventListener("click", () => {
            closeProfile();
            findSimilarAttorney(c);
        });

        $("#btn-profile-pitch").addEventListener("click", () => {
            closeProfile();
            if (window.JAIDE && window.JAIDE.openPitchModal) window.JAIDE.openPitchModal(c);
        });

        $("#btn-profile-pitch-firm").addEventListener("click", () => {
            closeProfile();
            if (window.JAIDE && window.JAIDE.openFirmPitchModal) {
                window.JAIDE.openFirmPitchModal({
                    candidate: {
                        id: c.id || c.attorney_id || "",
                        name: name,
                        practice_areas: c.practice_areas || c.practiceArea || "",
                    },
                });
            }
        });

        const sendEmailBtn = profileCard.querySelector("#btn-profile-send-email");
        if (sendEmailBtn) {
            sendEmailBtn.addEventListener("click", () => {
                closeProfile();
                // Open compose modal pre-populated with this attorney
                const composeOverlay = document.getElementById("compose-overlay");
                if (composeOverlay) {
                    composeOverlay.classList.add("open");
                    const toField = document.getElementById("compose-to");
                    if (toField) toField.value = email;
                } else {
                    // Fallback: open email client
                    window.location.href = `mailto:${encodeURIComponent(email)}`;
                }
            });
        }

        const addWorklistBtn = profileCard.querySelector("#btn-profile-add-worklist");
        if (addWorklistBtn) {
            addWorklistBtn.addEventListener("click", () => {
                closeProfile();
                if (window.JAIDE && window.JAIDE.openAddToWorklist) {
                    window.JAIDE.openAddToWorklist({ id: aid, name, email, current_firm: firm });
                }
            });
        }

        const createTaskBtn = profileCard.querySelector("#btn-profile-create-task");
        if (createTaskBtn) {
            createTaskBtn.addEventListener("click", () => {
                closeProfile();
                if (window.JAIDE && window.JAIDE.openTaskModal) {
                    window.JAIDE.openTaskModal({ prefillTitle: `Follow up with ${name}` });
                }
            });
        }

        profileOverlay.classList.add("open");
    }

    function _loadCompactEmailHistory(aid, email) {
        const container = document.getElementById("profile-email-history-compact");
        if (!container) return;
        const bodyEl = container.querySelector(".profile-email-history-body");
        if (!bodyEl) return;
        if (!aid && !email) {
            bodyEl.innerHTML = '<span class="profile-email-none">No emails sent yet</span>';
            return;
        }
        const url = `/api/email/history/${encodeURIComponent(String(aid))}` +
            (email ? `?email=${encodeURIComponent(email)}` : "");
        fetch(url)
            .then(r => r.json())
            .then(data => {
                const entries = (data.entries || []).slice(0, 5);
                if (!entries.length) {
                    bodyEl.innerHTML = '<span class="profile-email-none">No emails sent yet</span>';
                    return;
                }
                bodyEl.innerHTML = entries.map(e => {
                    const d = (e.sent_at || "").slice(0, 10);
                    const opened = e.opened_count > 0;
                    const replied = !!e.replied_at;
                    const statusDot = e.status === "sent"
                        ? (opened ? '<span class="peh-dot peh-dot-opened" title="Opened">●</span>'
                                  : '<span class="peh-dot peh-dot-sent" title="Sent">●</span>')
                        : '<span class="peh-dot peh-dot-failed" title="Failed">●</span>';
                    return `<div class="profile-email-row">
                        ${statusDot}
                        <span class="peh-date">${esc(d)}</span>
                        <span class="peh-subject">${esc(e.subject || "(no subject)")}</span>
                        ${opened ? '<span class="peh-tag peh-tag-opened">Opened</span>' : ''}
                        ${replied ? '<span class="peh-tag peh-tag-replied">Replied</span>' : ''}
                    </div>`;
                }).join("");
            })
            .catch(() => {
                if (bodyEl) bodyEl.innerHTML = '<span class="profile-email-none">—</span>';
            });
    }

    function _loadCorrespondenceTab(aid, email) {
        const panel = profileCard.querySelector('[data-panel="correspondence"]');
        if (!panel) return;
        if (!aid && !email) {
            panel.innerHTML = '<p class="no-data">No emails logged for this attorney.</p>';
            return;
        }
        const url = `/api/email/history/${encodeURIComponent(String(aid))}` +
            (email ? `?email=${encodeURIComponent(email)}` : "");
        fetch(url)
            .then(r => r.json())
            .then(data => {
                const entries = data.entries || [];
                if (!entries.length) {
                    panel.innerHTML = `
                        <p class="no-data">No outbound emails logged for this attorney yet.</p>
                        <p class="nylas-tracking-note" style="margin-top:8px">Inbound email tracking requires Nylas integration.</p>`;
                    return;
                }
                const rows = entries.map(e => {
                    const d = (e.sent_at || "").slice(0, 10);
                    const statusBadge = e.status === "sent"
                        ? '<span class="hub-status-badge sent">Sent</span>'
                        : `<span class="hub-status-badge failed">${esc(e.status)}</span>`;
                    return `<div class="corr-row">
                        <div class="corr-row-top">
                            <span class="corr-subject">${esc(e.subject || "(no subject)")}</span>
                            ${statusBadge}
                        </div>
                        <div class="corr-row-meta">
                            <span class="corr-date">${esc(d)}</span>
                            ${e.job_title ? '<span class="corr-job">' + esc(e.job_title) + '</span>' : ''}
                            ${e.opened_count > 0 ? '<span class="peh-tag peh-tag-opened">Opened</span>' : ''}
                            ${e.replied_at ? '<span class="peh-tag peh-tag-replied">Replied</span>' : ''}
                        </div>
                    </div>`;
                }).join("");
                panel.innerHTML = `
                    <div class="corr-list">${rows}</div>
                    <p class="nylas-tracking-note" style="margin-top:12px">Inbound email tracking (opens, clicks, replies) requires Nylas integration.</p>`;
            })
            .catch(() => {
                panel.innerHTML = '<p class="no-data">Failed to load correspondence.</p>';
            });
    }

    function _loadMatchedJobsTab(aid) {
        const panel = profileCard.querySelector('[data-panel="matched-jobs"]');
        if (!panel) return;
        fetch(`/api/attorneys/${encodeURIComponent(String(aid))}/full-profile`)
            .then(r => r.json())
            .then(data => {
                const pipeline = data.pipeline || [];
                if (!pipeline.length) {
                    panel.innerHTML = '<p class="no-data">This attorney is not currently on any job pipelines.</p>';
                    return;
                }
                const rows = pipeline.map(p => `
                    <div class="matched-job-row">
                        <div class="matched-job-title">${esc(p.job_title || "—")}</div>
                        <div class="matched-job-meta">
                            ${p.employer_name ? '<span class="matched-job-firm">' + esc(p.employer_name) + '</span>' : ''}
                            <span class="pipeline-stage-chip">${esc(p.stage || "—")}</span>
                        </div>
                    </div>`).join("");
                panel.innerHTML = `<div class="matched-jobs-list">${rows}</div>`;
            })
            .catch(() => {
                panel.innerHTML = '<p class="no-data">Failed to load pipeline data.</p>';
            });
    }

    // ================================================================
    // Email Settings
    // ================================================================
    const settingsOverlay = $("#settings-overlay");
    const settingsForm = $("#settings-form");

    $("#btn-settings").addEventListener("click", openSettings);
    $("#settings-close").addEventListener("click", closeSettings);
    settingsOverlay.addEventListener("click", (e) => {
        if (e.target === settingsOverlay) closeSettings();
    });

    // Toggle SMTP fields visibility
    $("#set-mode").addEventListener("change", () => {
        $("#smtp-fields").style.display = $("#set-mode").value === "smtp" ? "block" : "none";
    });
    $("#set-provider").addEventListener("change", () => {
        $("#custom-smtp-fields").style.display = $("#set-provider").value === "custom" ? "block" : "none";
    });

    function openSettings() {
        fetch("/api/email/settings")
            .then(r => r.json())
            .then(s => {
                $("#set-mode").value = s.mode || "mailto";
                $("#set-provider").value = s.provider || "gmail";
                $("#set-email").value = s.email || "";
                $("#set-display-name").value = s.display_name || "";
                $("#set-title").value = s.title || "";
                $("#set-phone").value = s.phone || "";
                $("#set-custom-host").value = s.custom_host || "";
                $("#set-custom-port").value = s.custom_port || 587;
                $("#set-password").value = "";
                $("#set-password").placeholder = s.has_password ? "Password saved (re-enter to change)" : "Enter password (stored in memory only)";
                $("#smtp-fields").style.display = s.mode === "smtp" ? "block" : "none";
                $("#custom-smtp-fields").style.display = s.provider === "custom" ? "block" : "none";
                $("#settings-status").textContent = "";
                settingsOverlay.classList.add("open");
            });
    }

    function closeSettings() {
        settingsOverlay.classList.remove("open");
    }

    settingsForm.addEventListener("submit", (e) => {
        e.preventDefault();
        saveSettings();
    });

    function saveSettings() {
        const payload = {
            mode: $("#set-mode").value,
            provider: $("#set-provider").value,
            email: $("#set-email").value,
            display_name: $("#set-display-name").value,
            title: $("#set-title").value,
            phone: $("#set-phone").value,
            custom_host: $("#set-custom-host").value,
            custom_port: parseInt($("#set-custom-port").value) || 587,
        };
        const pw = $("#set-password").value;
        if (pw) payload.password = pw;
        const status = $("#settings-status");
        status.textContent = "Saving...";
        status.className = "form-status";
        fetch("/api/email/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then(r => r.json())
            .then(data => {
                status.textContent = "Settings saved.";
                status.className = "form-status status-ok";
            })
            .catch(() => {
                status.textContent = "Failed to save.";
                status.className = "form-status status-err";
            });
    }

    $("#btn-test-email").addEventListener("click", () => {
        const status = $("#settings-status");
        status.textContent = "Sending test email...";
        status.className = "form-status";
        const payload = {};
        const pw = $("#set-password").value;
        if (pw) payload.password = pw;
        // Save settings first, then test
        saveSettings();
        setTimeout(() => {
            fetch("/api/email/test", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            })
                .then(r => r.json())
                .then(data => {
                    if (data.ok) {
                        status.textContent = "Test email sent successfully!";
                        status.className = "form-status status-ok";
                    } else {
                        status.textContent = "Test failed: " + (data.error || "Unknown error");
                        status.className = "form-status status-err";
                    }
                })
                .catch(() => {
                    status.textContent = "Connection error.";
                    status.className = "form-status status-err";
                });
        }, 500);
    });

    // ================================================================
    // Email Composer
    // ================================================================
    const composerOverlay = $("#composer-overlay");
    let composerRecipients = []; // candidates with email
    let composerNoEmail = [];    // candidates without email
    let composerSettings = {};

    $("#composer-close").addEventListener("click", closeEmailComposer);
    composerOverlay.addEventListener("click", (e) => {
        if (e.target === composerOverlay) closeEmailComposer();
    });

    function openEmailComposer(candidates) {
        fetch("/api/email/settings")
            .then(r => r.json())
            .then(settings => {
                composerSettings = settings;
                composerRecipients = [];
                composerNoEmail = [];

                candidates.forEach(c => {
                    const email = c.email || "";
                    if (email) {
                        composerRecipients.push(c);
                    } else {
                        composerNoEmail.push(c);
                    }
                });

                // Render recipient pills
                const pillsEl = $("#recipient-pills");
                pillsEl.innerHTML = "";
                composerRecipients.forEach((c, i) => {
                    const name = c.name || `${c.first_name || ""} ${c.last_name || ""}`.trim();
                    const pill = document.createElement("span");
                    pill.className = "recipient-pill";
                    pill.innerHTML = `${esc(name)} <button class="pill-remove" data-idx="${i}">&times;</button>`;
                    pill.querySelector(".pill-remove").addEventListener("click", () => {
                        composerRecipients.splice(i, 1);
                        openEmailComposer([...composerRecipients, ...composerNoEmail]);
                    });
                    pillsEl.appendChild(pill);
                });

                // No-email warning
                const warnEl = $("#no-email-warning");
                if (composerNoEmail.length) {
                    const names = composerNoEmail.map(c => c.name || `${c.first_name || ""} ${c.last_name || ""}`.trim()).join(", ");
                    warnEl.textContent = `${composerNoEmail.length} candidate(s) skipped (no email): ${names}`;
                    warnEl.style.display = "block";
                } else {
                    warnEl.style.display = "none";
                }

                // From field
                const fromName = settings.display_name || "";
                const fromEmail = settings.email || "";
                $("#composer-from").value = fromName ? `${fromName} <${fromEmail}>` : fromEmail || "(not configured — open Settings)";

                // Reset fields
                $("#composer-subject").value = "";
                $("#composer-body").value = "";
                $("#composer-cc").value = "";
                $("#composer-bcc").value = "";
                $("#composer-template").value = "";
                $("#preview-section").style.display = "none";
                $("#composer-progress").style.display = "none";
                $("#composer-status").textContent = "";
                $("#cc-fields").style.display = "none";

                // Single-recipient detection: show/hide Personalize button + hint
                const personalizeBtn = $("#btn-personalize");
                const personalizeHint = $("#personalize-hint");
                if (personalizeBtn) {
                    if (composerRecipients.length === 1) {
                        personalizeBtn.style.display = "";
                        if (personalizeHint && !$("#composer-body").value) {
                            personalizeHint.style.display = "block";
                        }
                    } else {
                        personalizeBtn.style.display = "none";
                        if (personalizeHint) personalizeHint.style.display = "none";
                    }
                }

                composerOverlay.classList.add("open");
            });
    }

    function closeEmailComposer() {
        composerOverlay.classList.remove("open");
    }

    // Template selection
    $("#composer-template").addEventListener("change", () => {
        const key = $("#composer-template").value;
        const tmpl = EMAIL_TEMPLATES[key];
        if (tmpl) {
            $("#composer-subject").value = tmpl.subject;
            $("#composer-body").value = tmpl.body;
        }
    });

    // AI Draft button
    const aiDraftBtn = $("#btn-ai-draft");
    if (aiDraftBtn) {
        aiDraftBtn.addEventListener("click", () => {
            if (!currentJdText && !currentMeta) {
                $("#composer-status").textContent = "Run a search first so AI can draft based on the job description.";
                $("#composer-status").className = "form-status status-err";
                return;
            }
            aiDraftBtn.disabled = true;
            aiDraftBtn.textContent = "Drafting...";
            const payload = {
                jd: currentJdText || "",
                firm_name: currentMeta ? (currentMeta.matched_firm || currentMeta.firm_name || "") : "",
                meta: currentMeta || {},
            };
            fetch("/api/email/draft", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            })
            .then(r => r.json())
            .then(data => {
                aiDraftBtn.disabled = false;
                aiDraftBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2l2 7h7l-5.5 4 2 7L12 16l-5.5 4 2-7L3 9h7z"/></svg> AI Draft';
                if (data.error) {
                    $("#composer-status").textContent = "AI draft failed: " + data.error;
                    $("#composer-status").className = "form-status status-err";
                    return;
                }
                $("#composer-subject").value = data.subject || "";
                $("#composer-body").value = data.body || "";
                $("#composer-template").value = "";
                $("#composer-status").textContent = "AI draft generated — review and edit before sending.";
                $("#composer-status").className = "form-status status-ok";
            })
            .catch(err => {
                aiDraftBtn.disabled = false;
                aiDraftBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2l2 7h7l-5.5 4 2 7L12 16l-5.5 4 2-7L3 9h7z"/></svg> AI Draft';
                $("#composer-status").textContent = "AI draft failed — check connection.";
                $("#composer-status").className = "form-status status-err";
                console.error(err);
            });
        });
    }

    // Personalize button
    const personalizeBtn = $("#btn-personalize");
    if (personalizeBtn) {
        personalizeBtn.addEventListener("click", () => {
            if (composerRecipients.length !== 1) return;
            if (!currentJdText && !currentMeta) {
                $("#composer-status").textContent = "Run a search first so AI can personalize based on the job description.";
                $("#composer-status").className = "form-status status-err";
                return;
            }
            personalizeBtn.disabled = true;
            personalizeBtn.textContent = "Personalizing...";
            const attorney = composerRecipients[0];
            const payload = {
                attorney: attorney,
                jd: currentJdText || "",
                firm_name: currentMeta ? (currentMeta.matched_firm || currentMeta.firm_name || "") : "",
                meta: currentMeta || {},
            };
            fetch("/api/email/draft-personalized", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            })
            .then(r => r.json())
            .then(data => {
                personalizeBtn.disabled = false;
                personalizeBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3l1.5 4.5H18l-3.7 2.7 1.4 4.3L12 11.8l-3.7 2.7 1.4-4.3L6 7.5h4.5z"/><path d="M5 2l.6 1.8H7.4L6 5l.6 1.8L5 5.6 3.4 6.8 4 5 2.6 3.8H4.4z"/><path d="M19 12l.6 1.8h1.8L20 15l.6 1.8-1.6-1.2-1.6 1.2.6-1.8-1.4-1.2h1.8z"/></svg> Personalize';
                if (data.error) {
                    $("#composer-status").textContent = "Personalization failed: " + data.error;
                    $("#composer-status").className = "form-status status-err";
                    return;
                }
                const name = attorney.name || `${attorney.first_name || ""} ${attorney.last_name || ""}`.trim();
                $("#composer-subject").value = data.subject || "";
                $("#composer-body").value = data.body || "";
                $("#composer-template").value = "";
                $("#composer-status").textContent = `Personalized draft generated for ${name} — review and edit before sending.`;
                $("#composer-status").className = "form-status status-ok";
                const hint = $("#personalize-hint");
                if (hint) hint.style.display = "none";
            })
            .catch(err => {
                personalizeBtn.disabled = false;
                personalizeBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3l1.5 4.5H18l-3.7 2.7 1.4 4.3L12 11.8l-3.7 2.7 1.4-4.3L6 7.5h4.5z"/><path d="M5 2l.6 1.8H7.4L6 5l.6 1.8L5 5.6 3.4 6.8 4 5 2.6 3.8H4.4z"/><path d="M19 12l.6 1.8h1.8L20 15l.6 1.8-1.6-1.2-1.6 1.2.6-1.8-1.4-1.2h1.8z"/></svg> Personalize';
                $("#composer-status").textContent = "Personalization failed — check connection.";
                $("#composer-status").className = "form-status status-err";
                console.error(err);
            });
        });
    }

    // CC/BCC toggle
    $("#cc-toggle").addEventListener("click", () => {
        const fields = $("#cc-fields");
        fields.style.display = fields.style.display === "none" ? "block" : "none";
    });

    // Preview toggle
    $("#btn-preview-toggle").addEventListener("click", togglePreview);

    function togglePreview() {
        const section = $("#preview-section");
        if (section.style.display === "none") {
            // Populate recipient dropdown
            const sel = $("#preview-recipient");
            sel.innerHTML = "";
            composerRecipients.forEach((c, i) => {
                const name = c.name || `${c.first_name || ""} ${c.last_name || ""}`.trim();
                const opt = document.createElement("option");
                opt.value = i;
                opt.textContent = name;
                sel.appendChild(opt);
            });
            renderPreview();
            sel.addEventListener("change", renderPreview);
            section.style.display = "block";
        } else {
            section.style.display = "none";
        }
    }

    function renderPreview() {
        const idx = parseInt($("#preview-recipient").value) || 0;
        const c = composerRecipients[idx];
        if (!c) return;
        const body = $("#composer-body").value;
        const resolved = resolveMergeFieldsClient(body, c);
        $("#preview-rendered").innerHTML = esc(resolved).replace(/\n/g, "<br>");
    }

    function resolveMergeFieldsClient(template, candidate) {
        const mapping = {
            first_name: candidate.first_name || (candidate.name || "").split(" ")[0] || "",
            last_name: candidate.last_name || (candidate.name || "").split(" ").pop() || "",
            name: candidate.name || `${candidate.first_name || ""} ${candidate.last_name || ""}`.trim(),
            firm: candidate.current_firm || candidate.firm_name || "",
            title: candidate.title || "",
            law_school: candidate.law_school || candidate.lawSchool || "",
            graduation_year: String(candidate.graduation_year || candidate.graduationYear || ""),
            specialties: candidate.specialties || candidate.specialty || "",
            location: candidate.location || "",
            sender_name: composerSettings.display_name || "",
            sender_title: composerSettings.title || "",
            sender_phone: composerSettings.phone || "",
            sender_email: composerSettings.email || "",
        };
        let result = template;
        for (const [key, val] of Object.entries(mapping)) {
            result = result.split("{" + key + "}").join(val);
        }
        return result;
    }

    // Send all
    $("#btn-send-all").addEventListener("click", sendAllEmails);

    function sendAllEmails() {
        if (!composerRecipients.length) {
            $("#composer-status").textContent = "No recipients with email addresses.";
            $("#composer-status").className = "form-status status-err";
            return;
        }

        const mode = composerSettings.mode || "mailto";
        const subject = $("#composer-subject").value;
        const body = $("#composer-body").value;

        if (mode === "mailto") {
            // Open mailto links
            composerRecipients.forEach((c, i) => {
                setTimeout(() => {
                    const resolvedSubject = resolveMergeFieldsClient(subject, c);
                    const resolvedBody = resolveMergeFieldsClient(body, c);
                    const email = c.email;
                    const mailto = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(resolvedSubject)}&body=${encodeURIComponent(resolvedBody)}`;
                    window.open(mailto, "_blank");
                }, i * 800);
            });
            $("#composer-status").textContent = `Opened ${composerRecipients.length} mailto link(s).`;
            $("#composer-status").className = "form-status status-ok";
            return;
        }

        // SMTP mode
        const progressEl = $("#composer-progress");
        const fillEl = $("#progress-fill");
        const textEl = $("#progress-text");
        progressEl.style.display = "block";
        fillEl.style.width = "0%";
        textEl.textContent = "Preparing...";

        const recipients = composerRecipients.map(c => ({
            email: c.email,
            name: c.name || `${c.first_name || ""} ${c.last_name || ""}`.trim(),
            first_name: c.first_name || (c.name || "").split(" ")[0] || "",
            last_name: c.last_name || (c.name || "").split(" ").pop() || "",
            current_firm: c.current_firm || c.firm_name || "",
            firm_name: c.firm_name || "",
            title: c.title || "",
            law_school: c.law_school || c.lawSchool || "",
            graduation_year: c.graduation_year || c.graduationYear || "",
            specialties: c.specialties || c.specialty || "",
            location: c.location || "",
        }));

        fetch("/api/email/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                recipients,
                subject,
                body,
                cc: $("#composer-cc").value,
                bcc: $("#composer-bcc").value,
            }),
        })
            .then(r => r.json())
            .then(data => {
                const results = data.results || [];
                const sent = results.filter(r => r.status === "sent").length;
                const failed = results.filter(r => r.status === "failed").length;
                const skipped = results.filter(r => r.status === "skipped").length;
                fillEl.style.width = "100%";
                textEl.textContent = `Done: ${sent} sent, ${failed} failed, ${skipped} skipped`;
                const status = $("#composer-status");
                if (failed > 0) {
                    const errs = results.filter(r => r.status === "failed").map(r => `${r.name}: ${r.error}`).join("; ");
                    status.textContent = "Some emails failed: " + errs;
                    status.className = "form-status status-err";
                } else {
                    status.textContent = "All emails sent successfully!";
                    status.className = "form-status status-ok";
                }
            })
            .catch(() => {
                textEl.textContent = "Error sending emails.";
                $("#composer-status").textContent = "Connection error.";
                $("#composer-status").className = "form-status status-err";
            });
    }

    // Send test to self
    $("#btn-send-test").addEventListener("click", () => {
        const subject = $("#composer-subject").value || "Test Email";
        const body = $("#composer-body").value || "Test body";
        const testRecip = composerRecipients[0] || {};
        const resolvedSubject = resolveMergeFieldsClient(subject, testRecip);
        const resolvedBody = resolveMergeFieldsClient(body, testRecip);
        const status = $("#composer-status");
        status.textContent = "Sending test...";
        status.className = "form-status";

        fetch("/api/email/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                recipients: [{
                    email: composerSettings.email,
                    name: "Test",
                    first_name: testRecip.first_name || "Test",
                    last_name: testRecip.last_name || "User",
                }],
                subject: "[TEST] " + resolvedSubject,
                body: resolvedBody,
            }),
        })
            .then(r => r.json())
            .then(data => {
                const r = (data.results || [])[0];
                if (r && r.status === "sent") {
                    status.textContent = "Test email sent to " + composerSettings.email;
                    status.className = "form-status status-ok";
                } else {
                    status.textContent = "Test failed: " + (r ? r.error : "Unknown");
                    status.className = "form-status status-err";
                }
            })
            .catch(() => {
                status.textContent = "Connection error.";
                status.className = "form-status status-err";
            });
    });

    // ================================================================
    // Sent Emails View
    // ================================================================
    const btnSentEmails = $("#btn-sent-emails");
    if (btnSentEmails) {
        btnSentEmails.addEventListener("click", () => {
            document.querySelectorAll(".ats-view").forEach(v => v.style.display = "none");
            const jobResults = document.getElementById("job-results-content");
            if (jobResults) jobResults.style.display = "none";
            showSentEmails();
        });
    }
    // "Back" button in Email Hub — delegate to hub module if available
    const _sentBackBtn = $("#btn-sent-back");
    if (_sentBackBtn) {
        _sentBackBtn.addEventListener("click", () => {
            const view = $("#sent-emails-view");
            if (view) view.style.display = "none";
            if (hasResults) {
                resultsContent.style.display = "block";
            } else {
                resultsPlaceholder.style.display = "flex";
            }
        });
    }

    function showSentEmails() {
        if (window.JAIDE && window.JAIDE.showEmailHub) {
            window.JAIDE.showEmailHub();
        }
    }

    // Wire Email Settings button in the Email Hub header
    document.addEventListener("click", function (e) {
        if (e.target && e.target.id === "btn-email-settings") {
            openSettings();
        }
    });

    // ================================================================
    // Find Similar Attorneys
    // ================================================================
    let _previousResultsState = null;

    function findSimilarAttorney(attorney) {
        const name = attorney.name || `${attorney.first_name || ""} ${attorney.last_name || ""}`.trim();
        const aid = attorney.id || attorney.attorney_id || "";
        if (!aid) {
            addBubble("Cannot find similar attorneys — no attorney ID available.", "assistant");
            return;
        }

        // Navigate to search view if needed
        navigateTo(searchMode === "job" ? "jobs" : "attorneys");

        // Save current results state for "Back" navigation
        _previousResultsState = {
            resultsVisible: resultsContent.style.display !== "none",
            placeholderVisible: resultsPlaceholder.style.display !== "none",
        };

        // Show loading in chat
        const loaderMsg = document.createElement("div");
        loaderMsg.className = "chat-bubble assistant ai-loading";
        loaderMsg.innerHTML = `
            <div class="ai-loading-content">
                <div class="ai-spinner"></div>
                <span>Finding attorneys similar to <strong>${esc(name)}</strong>...</span>
            </div>
            <div class="ai-loading-sub">Analyzing practice focus, firm tier, and career stage.</div>`;
        chatMessages.appendChild(loaderMsg);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // Show skeleton loading in results panel
        resultsPlaceholder.style.display = "none";
        resultsContent.style.display = "none";
        document.querySelectorAll(".ats-view").forEach(v => v.style.display = "none");
        const simView = document.getElementById("similar-results-view");
        if (simView) {
            simView.style.display = "block";
            simView.innerHTML = buildSimilarSkeleton(name);
        }
        collapseForResults();

        fetch("/api/attorneys/similar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ attorney_id: aid }),
        })
            .then(r => r.json())
            .then(data => {
                loaderMsg.remove();
                if (data.error) {
                    addBubble(`Could not find similar attorneys: ${data.error}`, "assistant");
                    if (simView) simView.innerHTML = `<p class="no-data" style="padding:20px">${esc(data.error)}</p>`;
                    return;
                }
                renderSimilarResults(data, simView);
                renderSimilarChatMessage(data);
            })
            .catch(err => {
                loaderMsg.remove();
                addBubble("Failed to find similar attorneys. Please try again.", "assistant");
                if (simView) simView.innerHTML = '<p class="no-data" style="padding:20px">Request failed.</p>';
            });
    }

    function buildSimilarSkeleton(name) {
        const cards = Array.from({ length: 6 }, (_, i) => `
            <div class="sim-card sim-skeleton">
                <div class="sim-rank-col"><span class="sim-rank">#${i + 1}</span></div>
                <div class="sim-card-body">
                    <div class="sim-skel-line" style="width:60%"></div>
                    <div class="sim-skel-line" style="width:40%"></div>
                    <div class="sim-skel-line" style="width:80%"></div>
                </div>
            </div>`).join("");
        return `
            <div class="sim-results">
                <div class="sim-header">
                    <button class="btn-back" id="sim-back">&larr; Back to Results</button>
                    <h2 class="sim-title">Attorneys Similar to ${esc(name)}</h2>
                    <p class="sim-loading-text">Analyzing profiles...</p>
                </div>
                <div class="sim-cards">${cards}</div>
            </div>`;
    }

    function renderSimilarResults(data, container) {
        const source = data.source || {};
        const similar = data.similar || [];
        const elapsed = data.elapsed_seconds || 0;
        const sourceName = source.name || source.current_firm || "Unknown";
        const sourceFirm = source.current_firm || "";
        const sourceYear = source.graduation_year || "";
        const sourcePractice = source.practice_areas || source.specialties || "";
        const sourceSchool = source.law_school || "";

        const cardsHtml = similar.length ? similar.map(s => {
            const score = s.similarity_score || 0;
            const scoreCls = score >= 80 ? "sim-score-high" : score >= 60 ? "sim-score-mid" : "sim-score-low";
            const pipelineBadge = s.in_pipeline ? '<span class="sim-pipeline-badge">In Pipeline</span>' : '';
            return `<div class="sim-card" data-attorney-id="${esc(String(s.id || ""))}">
                <div class="sim-rank-col">
                    <span class="sim-rank">#${s.similarity_rank || 0}</span>
                    <span class="sim-score ${scoreCls}">${score}</span>
                </div>
                <div class="sim-card-body">
                    <div class="sim-card-top">
                        <a class="sim-name" data-attorney-id="${esc(String(s.id || ""))}">${esc(s.name || "")}</a>
                        ${pipelineBadge}
                    </div>
                    <div class="sim-card-firm">${esc(s.current_firm || "")}${s.title ? " \u2014 " + esc(s.title) : ""}</div>
                    <div class="sim-card-detail">${esc(s.graduation_year || "")}${s.law_school ? " \u00B7 " + esc(s.law_school) : ""}</div>
                    <div class="sim-reason">${esc(s.similarity_reason || "")}</div>
                    <div class="sim-card-actions">
                        <button class="sim-action-btn sim-view-profile" data-idx="${s.similarity_rank - 1}">View Profile</button>
                        <button class="sim-action-btn sim-send-email" data-idx="${s.similarity_rank - 1}">Send Email</button>
                        <button class="sim-action-btn sim-add-pipeline" data-idx="${s.similarity_rank - 1}">Add to Pipeline</button>
                    </div>
                </div>
            </div>`;
        }).join("") : '<p class="no-data" style="padding:20px">No similar attorneys found.</p>';

        container.innerHTML = `
            <div class="sim-results">
                <div class="sim-header">
                    <button class="btn-back" id="sim-back">&larr; Back to Results</button>
                    <div class="sim-header-content">
                        <h2 class="sim-title">Attorneys Similar to ${esc(sourceName)}</h2>
                        <div class="sim-source-info">
                            ${sourceFirm ? esc(sourceFirm) : ''}${sourceYear ? " \u00B7 Class of " + esc(sourceYear) : ""}${sourcePractice ? " \u00B7 " + esc(sourcePractice) : ""}${sourceSchool ? " \u00B7 " + esc(sourceSchool) : ""}
                        </div>
                        ${data.source_summary ? '<div class="sim-source-summary">' + esc(data.source_summary) + '</div>' : ''}
                    </div>
                    <div class="sim-header-right">
                        <span class="sim-elapsed">${elapsed}s</span>
                        <button class="btn-export sim-export" id="sim-export">
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 2v8M4 7l4 4 4-4M2 12v2h12v-2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            Export
                        </button>
                    </div>
                </div>
                <div class="sim-cards">${cardsHtml}</div>
            </div>`;

        // Wire back button
        const backBtn = container.querySelector("#sim-back");
        if (backBtn) {
            backBtn.addEventListener("click", () => {
                container.style.display = "none";
                if (_previousResultsState) {
                    resultsContent.style.display = _previousResultsState.resultsVisible ? "block" : "none";
                    resultsPlaceholder.style.display = _previousResultsState.placeholderVisible ? "flex" : "none";
                } else {
                    resultsPlaceholder.style.display = hasResults ? "none" : "flex";
                    resultsContent.style.display = hasResults ? "block" : "none";
                }
            });
        }

        // Wire name clicks and action buttons
        container.querySelectorAll(".sim-name").forEach(link => {
            link.addEventListener("click", (e) => {
                e.preventDefault();
                const aid = link.dataset.attorneyId;
                const match = similar.find(s => String(s.id || "") === aid);
                if (match) openProfile(match);
            });
        });

        container.querySelectorAll(".sim-view-profile").forEach(btn => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.idx);
                if (similar[idx]) openProfile(similar[idx]);
            });
        });

        container.querySelectorAll(".sim-send-email").forEach(btn => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.idx);
                if (similar[idx]) openEmailComposer([similar[idx]]);
            });
        });

        container.querySelectorAll(".sim-add-pipeline").forEach(btn => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.idx);
                const s = similar[idx];
                if (s) {
                    document.dispatchEvent(new CustomEvent("jaide:addToPipeline", {
                        detail: [{
                            id: s.id || s.attorney_id || 0,
                            name: s.name || "",
                            current_firm: s.current_firm || "",
                            email: s.email || "",
                        }]
                    }));
                }
            });
        });

        // Wire export
        const exportBtn = container.querySelector("#sim-export");
        if (exportBtn) {
            exportBtn.addEventListener("click", () => {
                const rows = similar.map(s =>
                    `<tr><td>${s.similarity_rank}</td><td>${s.similarity_score}</td><td>${esc(s.name || "")}</td><td>${esc(s.current_firm || "")}</td><td>${esc(s.graduation_year || "")}</td><td>${esc(s.law_school || "")}</td><td>${esc(s.similarity_reason || "")}</td></tr>`
                ).join("");
                const html = `<html><head><style>table{border-collapse:collapse;width:100%;font-family:sans-serif}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f4f4f4}tr:nth-child(even){background:#fafafa}</style></head><body><h2>Attorneys Similar to ${esc(sourceName)}</h2><table><thead><tr><th>#</th><th>Score</th><th>Name</th><th>Firm</th><th>Year</th><th>School</th><th>Reason</th></tr></thead><tbody>${rows}</tbody></table></body></html>`;
                const blob = new Blob([html], { type: "text/html" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `similar-to-${sourceName.replace(/\s+/g, "-")}.html`;
                a.click();
                URL.revokeObjectURL(url);
            });
        }
    }

    function renderSimilarChatMessage(data) {
        const source = data.source || {};
        const similar = data.similar || [];
        const sourceName = source.name || "this attorney";

        if (!similar.length) {
            addBubble(`I couldn't find any attorneys closely similar to **${sourceName}** in the database.`, "assistant");
            return;
        }

        const top1 = similar[0];
        const top2 = similar[1];
        const top3 = similar[2];
        let msg = `I found **${similar.length}** attorneys similar to **${sourceName}**.`;
        msg += ` The closest match is **${top1.name}** at ${top1.current_firm || "their firm"} \u2014 ${top1.similarity_reason || "strong profile match"}.`;
        if (top2 && top3) {
            msg += ` Other strong matches include **${top2.name}** and **${top3.name}**.`;
        }
        msg += ` The results are ranked by how closely they match ${sourceName}'s practice focus, firm caliber, and career stage.`;
        addBubble(msg, "assistant");
    }

    // Expose findSimilarAttorney globally (for ats.js pipeline cards)
    window.JAIDE.findSimilarAttorney = findSimilarAttorney;

    // ================================================================
    // Pitch PDF Modal
    // ================================================================
    const pitchOverlay = $("#pitch-modal-overlay");
    const pitchForm = $("#pitch-form");
    const pitchJobSelect = $("#pitch-job-select");
    const pitchLoading = $("#pitch-loading");

    function openPitchModal(candidate, pipelineId, preselectedJobId) {
        const name = candidate.name || `${candidate.first_name || ""} ${candidate.last_name || ""}`.trim();
        const aid = candidate.id || candidate.attorney_id || "";
        $("#pitch-candidate-name").value = name;
        $("#pitch-attorney-id").value = aid;
        $("#pitch-pipeline-id").value = pipelineId || "";

        // Pre-fill recruiter info from email settings
        fetch("/api/email/settings").then(r => r.json()).then(s => {
            if (s.display_name) $("#pitch-recruiter-name").value = s.display_name;
            if (s.title) $("#pitch-recruiter-title").value = s.title;
            if (s.email) $("#pitch-recruiter-contact").value = s.email;
        }).catch(() => {});

        // Load ATS jobs into dropdown
        pitchJobSelect.innerHTML = '<option value="">-- Loading jobs... --</option>';
        fetch("/api/jobs").then(r => r.json()).then(data => {
            const jobs = data.jobs || [];
            pitchJobSelect.innerHTML = '<option value="">-- Select a job --</option>';
            jobs.forEach(j => {
                const opt = document.createElement("option");
                opt.value = `ats:${j.id}`;
                opt.textContent = `${j.title}${j.employer_name ? " @ " + j.employer_name : ""}${j.location ? " (" + j.location + ")" : ""}`;
                pitchJobSelect.appendChild(opt);
            });
            // Pre-select if provided
            if (preselectedJobId) {
                pitchJobSelect.value = `ats:${preselectedJobId}`;
            }
        }).catch(() => {
            pitchJobSelect.innerHTML = '<option value="">-- No jobs available --</option>';
        });

        pitchLoading.style.display = "none";
        pitchForm.style.display = "block";
        pitchOverlay.classList.add("open");
    }

    function closePitchModal() {
        pitchOverlay.classList.remove("open");
    }

    $("#pitch-modal-close").addEventListener("click", closePitchModal);
    $("#pitch-cancel").addEventListener("click", closePitchModal);
    pitchOverlay.addEventListener("click", (e) => { if (e.target === pitchOverlay) closePitchModal(); });

    // Logo upload
    $("#pitch-logo-upload").addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append("logo", file);
        fetch("/api/pitch/logo", { method: "POST", body: fd })
            .then(r => r.json())
            .then(d => { if (d.ok) console.log("Logo uploaded"); })
            .catch(() => {});
    });

    // Form submit
    pitchForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const jobVal = pitchJobSelect.value;
        if (!jobVal) { alert("Please select a job."); return; }

        const [jobSource, jobId] = jobVal.split(":");
        const sections = {};
        pitchForm.querySelectorAll('input[name="pitch-sec"]').forEach(cb => {
            sections[cb.value] = cb.checked;
        });

        const payload = {
            attorney_id: $("#pitch-attorney-id").value,
            job_id: parseInt(jobId),
            job_source: jobSource,
            anonymize: $("#pitch-anonymize").checked,
            focus_angle: $("#pitch-focus").value.trim(),
            sections,
            recruiter_name: $("#pitch-recruiter-name").value.trim(),
            recruiter_title: $("#pitch-recruiter-title").value.trim(),
            recruiter_contact: $("#pitch-recruiter-contact").value.trim(),
            pipeline_id: $("#pitch-pipeline-id").value || null,
        };

        pitchForm.style.display = "none";
        pitchLoading.style.display = "flex";

        fetch("/api/pitch/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        }).then(r => {
            if (!r.ok) {
                const ct = r.headers.get("content-type") || "";
                if (ct.includes("application/json")) {
                    return r.json().then(d => { throw new Error(d.error || "Generation failed"); });
                }
                throw new Error(`Server error (${r.status})`);
            }
            return r.blob();
        }).then(blob => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `pitch-${Date.now()}.pdf`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            closePitchModal();
        }).catch(err => {
            alert("Pitch generation failed: " + err.message);
            pitchForm.style.display = "block";
            pitchLoading.style.display = "none";
        });
    });

    window.JAIDE.openPitchModal = openPitchModal;

    // ---- Util ----
    function esc(s) {
        if (s == null) return "";
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
})();
