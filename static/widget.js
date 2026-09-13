/**
 * FlyRank Embeddable Lead-Capture Widget
 * Version: 1.0.0 (Immutable CDN Bundle)
 * Author: Deepak R
 */
(function () {
    // 1. Extract widget ID and host from current script tag
    const currentScript = document.currentScript || (function () {
        const scripts = document.getElementsByTagName('script');
        return scripts[scripts.length - 1];
    })();

    if (!currentScript) {
        console.error("[FlyRank Widget] Could not locate current script element.");
        return;
    }

    const scriptUrl = new URL(currentScript.src);
    const widgetId = scriptUrl.searchParams.get("id");
    const apiHost = scriptUrl.origin;

    if (!widgetId) {
        console.error("[FlyRank Widget] Missing required 'id' query parameter.");
        return;
    }

    // 2. Fetch public widget configuration
    fetch(`${apiHost}/widgets/${widgetId}/config`, {
        method: "GET",
        headers: { "Accept": "application/json" }
    })
    .then(res => {
        if (!res.ok) throw new Error(`Config fetch failed with status ${res.status}`);
        return res.json();
    })
    .then(config => {
        if (!config.is_active) return;
        renderWidget(config);
    })
    .catch(err => {
        console.warn("[FlyRank Widget] Initialization error:", err);
    });

    // 3. Render Widget Form in the DOM
    function renderWidget(config) {
        // Container element or insert before script
        const container = document.createElement("div");
        container.id = `flyrank-widget-${config.id}`;
        container.className = "flyrank-embed-container";

        // Scoped inline CSS for complete style isolation
        const style = document.createElement("style");
        style.textContent = `
            .flyrank-embed-container {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                max-width: 440px;
                margin: 20px auto;
                padding: 24px;
                border-radius: 12px;
                background: #ffffff;
                border: 1px solid #e2e8f0;
                box-shadow: 0 4px 14px rgba(0,0,0,0.08);
                color: #0f172a;
                box-sizing: border-box;
            }
            .flyrank-embed-container * { box-sizing: border-box; }
            .flyrank-embed-title {
                font-size: 1.25rem;
                font-weight: 700;
                margin: 0 0 16px 0;
                color: #1e293b;
            }
            .flyrank-embed-field {
                margin-bottom: 12px;
            }
            .flyrank-embed-field label {
                display: block;
                font-size: 0.85rem;
                font-weight: 600;
                margin-bottom: 4px;
                color: #475569;
            }
            .flyrank-embed-field input {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 0.95rem;
                outline: none;
                transition: border-color 0.2s;
            }
            .flyrank-embed-field input:focus {
                border-color: #2563eb;
            }
            /* Hidden honeypot trap field for bot defense */
            .flyrank-hp-trap {
                display: none !important;
                visibility: hidden !important;
                position: absolute !important;
                left: -9999px !important;
            }
            .flyrank-embed-btn {
                width: 100%;
                background: #2563eb;
                color: #ffffff;
                border: none;
                padding: 11px;
                border-radius: 6px;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
                transition: background 0.2s;
                margin-top: 6px;
            }
            .flyrank-embed-btn:hover { background: #1d4ed8; }
            .flyrank-embed-btn:disabled { background: #94a3b8; cursor: not-allowed; }
            .flyrank-feedback {
                margin-top: 12px;
                font-size: 0.9rem;
                padding: 10px;
                border-radius: 6px;
                display: none;
            }
            .flyrank-feedback.success {
                background: #dcfce7;
                color: #15803d;
                border: 1px solid #bbf7d0;
                display: block;
            }
            .flyrank-feedback.error {
                background: #fee2e2;
                color: #b91c1c;
                border: 1px solid #fecaca;
                display: block;
            }
        `;
        document.head.appendChild(style);

        container.innerHTML = `
            <h3 class="flyrank-embed-title">${escapeHtml(config.title)}</h3>
            <form id="flyrank-form-${config.id}">
                <div class="flyrank-embed-field">
                    <label for="flyrank-name-${config.id}">Your Name</label>
                    <input type="text" id="flyrank-name-${config.id}" name="name" placeholder="Alex Rivers">
                </div>
                <div class="flyrank-embed-field">
                    <label for="flyrank-email-${config.id}">Email Address *</label>
                    <input type="email" id="flyrank-email-${config.id}" name="email" placeholder="alex@company.com" required>
                </div>
                
                <!-- Anti-Spam Honeypot: invisible to humans, filled by automated scrapers -->
                <div class="flyrank-hp-trap" aria-hidden="true">
                    <label>Leave this field blank</label>
                    <input type="text" name="_hp_trap" tabindex="-1" autocomplete="off">
                </div>

                <button type="submit" class="flyrank-embed-btn" id="flyrank-submit-${config.id}">
                    ${escapeHtml(config.button_text)}
                </button>
                <div class="flyrank-feedback" id="flyrank-feedback-${config.id}"></div>
            </form>
        `;

        // Insert container into DOM
        currentScript.parentNode.insertBefore(container, currentScript.nextSibling);

        // Bind cross-origin submit handler
        const form = container.querySelector(`#flyrank-form-${config.id}`);
        const submitBtn = container.querySelector(`#flyrank-submit-${config.id}`);
        const feedback = container.querySelector(`#flyrank-feedback-${config.id}`);

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            submitBtn.disabled = true;
            submitBtn.textContent = "Submitting...";
            feedback.className = "flyrank-feedback";
            feedback.style.display = "none";

            const formData = new FormData(form);
            const payload = {
                name: formData.get("name") ? formData.get("name").trim() : null,
                email: formData.get("email") ? formData.get("email").trim() : "",
                _hp_trap: formData.get("_hp_trap") || ""
            };

            fetch(`${apiHost}/widgets/${config.id}/submissions`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                body: JSON.stringify(payload)
            })
            .then(async res => {
                const data = await res.json().catch(() => ({}));
                if (res.status === 201) {
                    feedback.className = "flyrank-feedback success";
                    feedback.textContent = "Thank you! Your submission has been securely recorded.";
                    form.reset();
                } else if (res.status === 429) {
                    feedback.className = "flyrank-feedback error";
                    feedback.textContent = "Too many requests. Please wait a moment before trying again.";
                } else {
                    feedback.className = "flyrank-feedback error";
                    feedback.textContent = data.detail || "Submission could not be processed. Please check your input.";
                }
            })
            .catch(err => {
                feedback.className = "flyrank-feedback error";
                feedback.textContent = "Network error. Please try again.";
            })
            .finally(() => {
                submitBtn.disabled = false;
                submitBtn.textContent = config.button_text;
            });
        });
    }

    function escapeHtml(str) {
        if (!str) return "";
        return str.replace(/[&<>'"]/g, tag => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        }[tag] || tag));
    }
})();
