// JAIDE ATS – Marketing Page
(function () {
    "use strict";

    // ── Smooth scroll for anchor links ──────────────────────────────────────
    document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
        anchor.addEventListener("click", function (e) {
            var target = document.querySelector(this.getAttribute("href"));
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: "smooth" });
            }
        });
    });

    // ── Login modal ──────────────────────────────────────────────────────────
    var overlay = document.getElementById("mkt-login-overlay");
    var loginForm = document.getElementById("mkt-login-form");
    var loginError = document.getElementById("mkt-login-error");
    var emailInput = document.getElementById("mkt-email");
    var passwordInput = document.getElementById("mkt-password");
    var togglePw = document.getElementById("mkt-toggle-pw");

    function openLogin() {
        if (!overlay) return;
        overlay.style.display = "flex";
        if (emailInput) emailInput.focus();
        if (loginError) loginError.textContent = "";
    }

    function closeLogin() {
        if (!overlay) return;
        overlay.style.display = "none";
    }

    // Open triggers
    document.querySelectorAll("[data-action='open-login']").forEach(function (el) {
        el.addEventListener("click", openLogin);
    });

    // Close on backdrop click
    if (overlay) {
        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) closeLogin();
        });
    }

    // Close on Escape
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") closeLogin();
    });

    // Password visibility toggle
    if (togglePw && passwordInput) {
        togglePw.addEventListener("click", function () {
            var isText = passwordInput.type === "text";
            passwordInput.type = isText ? "password" : "text";
            togglePw.innerHTML = isText
                ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'
                : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
        });
    }

    // Form submission
    if (loginForm) {
        loginForm.addEventListener("submit", function (e) {
            e.preventDefault();
            if (loginError) loginError.textContent = "";

            var email = emailInput ? emailInput.value.trim() : "";
            var password = passwordInput ? passwordInput.value : "";
            var submitBtn = loginForm.querySelector('button[type="submit"]');

            if (!email || !password) {
                if (loginError) loginError.textContent = "Please enter your email and password.";
                return;
            }

            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = "Signing in…";
            }

            fetch("/api/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: email, password: password }),
            })
                .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, data: d }; }); })
                .then(function (result) {
                    if (result.ok && result.data.success) {
                        window.location.reload();
                    } else {
                        if (loginError) loginError.textContent = result.data.error || "Login failed. Please try again.";
                        if (submitBtn) {
                            submitBtn.disabled = false;
                            submitBtn.textContent = "Sign In";
                        }
                    }
                })
                .catch(function () {
                    if (loginError) loginError.textContent = "Network error. Please try again.";
                    if (submitBtn) {
                        submitBtn.disabled = false;
                        submitBtn.textContent = "Sign In";
                    }
                });
        });
    }
})();
