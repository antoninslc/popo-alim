const SLOT_ORDER = {
    petit_dejeuner: 1,
    dejeuner: 2,
    gouter: 3,
    collation: 4,
    diner: 5,
};

const SLOT_SHORT = {
    petit_dejeuner: "Petit-déj",
    dejeuner: "Midi",
    gouter: "Goûter",
    collation: "Collation",
    diner: "Soir",
};

function formatDayHeader(isoDate) {
    if (!isoDate) return "";
    const today = new Date();
    const todayIso = today.toISOString().split("T")[0];

    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const yesterdayIso = yesterday.toISOString().split("T")[0];

    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    const tomorrowIso = tomorrow.toISOString().split("T")[0];

    const parts = isoDate.split("-");
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    const days = ["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"];
    const months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
    const formatted = `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;

    if (isoDate === todayIso) return `Aujourd'hui · ${formatted}`;
    if (isoDate === yesterdayIso) return `Hier · ${formatted}`;
    if (isoDate === tomorrowIso) return `Demain · ${formatted}`;
    return formatted;
}

const VALID_PROFILES = ["pauline", "antonin", "dev"];
const STORAGE_KEY_PROFILE = "cadence_selected_profile";
const SESSION_KEY_LOCAL_OVERRIDE = "cadence_localhost_override";
const STORAGE_KEY_STATE_PREFIX = "cadence_cached_state_v1_";

let currentRenderedState = null;
let sectionSignatures = {
    assistant: null,
    gauges: null,
    meals: null,
    workouts: null,
    profile: null,
};
let syncIntervalId = null;
let isMutating = false;

function getStateCacheKey(profileId) {
    return `${STORAGE_KEY_STATE_PREFIX}${profileId || "default"}`;
}

function loadCachedState(profileId) {
    try {
        const raw = localStorage.getItem(getStateCacheKey(profileId));
        if (!raw) return null;
        return JSON.parse(raw);
    } catch (_) {
        return null;
    }
}

function saveCachedState(profileId, state) {
    try {
        if (!state) return;
        localStorage.setItem(getStateCacheKey(profileId), JSON.stringify(state));
    } catch (_) {}
}

function resetSectionSignatures() {
    sectionSignatures = {
        assistant: null,
        gauges: null,
        meals: null,
        workouts: null,
        profile: null,
    };
}

function isLocalhostEnv() {
    const host = (window.location.hostname || "").toLowerCase();
    return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function getSelectedProfile() {
    if (isLocalhostEnv()) {
        const override = (sessionStorage.getItem(SESSION_KEY_LOCAL_OVERRIDE) || "").trim().toLowerCase();
        if (VALID_PROFILES.includes(override)) {
            return override;
        }
        return "dev";
    }
    const stored = (localStorage.getItem(STORAGE_KEY_PROFILE) || "").trim().toLowerCase();
    if (VALID_PROFILES.includes(stored)) {
        return stored;
    }
    return null;
}

function getCurrentUserId() {
    return getSelectedProfile() || (isLocalhostEnv() ? "dev" : "pauline");
}

function setSelectedProfile(profileId) {
    const clean = VALID_PROFILES.includes(profileId) ? profileId : "pauline";
    if (isLocalhostEnv()) {
        sessionStorage.setItem(SESSION_KEY_LOCAL_OVERRIDE, clean);
    } else {
        localStorage.setItem(STORAGE_KEY_PROFILE, clean);
    }
    applyHeaderProfileBranding(clean);
    return clean;
}

function applyHeaderProfileBranding(profileId) {
    const greetingEl = document.getElementById("hero-greeting");
    const settingsBadgeEl = document.getElementById("settings-active-profile-label");
    const isAntonin = profileId === "antonin";
    const isDev = profileId === "dev";
    const firstName = isDev ? "Dev (Local)" : isAntonin ? "Antonin" : "Pauline";

    if (greetingEl) {
        greetingEl.textContent = isDev ? "Mode Developpement" : `Bonjour ${firstName}`;
    }
    if (settingsBadgeEl) {
        settingsBadgeEl.textContent = `Profil : ${firstName}`;
    }
    document.title = isDev ? "Nutrition [Dev Local]" : "Nutrition";
}

async function apiCall(path, options = {}) {
    const currentUser = getCurrentUserId();
    const mergedHeaders = {
        "Content-Type": "application/json",
        "X-User-Id": currentUser,
        ...(options.headers || {}),
    };
    const resp = await fetch(path, {
        ...options,
        headers: mergedHeaders,
    });
    if (!resp.ok) {
        let msg = "Erreur serveur";
        try {
            const err = await resp.json();
            if (err.detail) msg = err.detail;
        } catch (_) {}
        throw new Error(msg);
    }
    return resp.json();
}

function showPage(pageName) {
    document.querySelectorAll(".page-view").forEach((v) => {
        v.classList.toggle("active", v.id === `page-${pageName}`);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
}

function initPageNavigationAndDrawers() {
    const openSettingsBtn = document.getElementById("open-settings-btn");
    const closeSettingsBtn = document.getElementById("close-settings-btn");

    if (openSettingsBtn) {
        openSettingsBtn.addEventListener("click", () => showPage("settings"));
    }
    if (closeSettingsBtn) {
        closeSettingsBtn.addEventListener("click", () => showPage("main"));
    }

    // Historique du chat
    const toggleChatHistoryBtn = document.getElementById("toggle-chat-history-btn");
    const chatDrawer = document.getElementById("chat-history-drawer");
    toggleChatHistoryBtn.addEventListener("click", () => {
        chatDrawer.classList.toggle("hidden");
    });

    // Tiroir Repas (ferme par defaut)
    const mealsCard = document.getElementById("meals-drawer-card");
    const mealsTrigger = document.getElementById("toggle-meals-drawer");
    const mealsBody = document.getElementById("meals-drawer-body");
    mealsTrigger.addEventListener("click", () => {
        const isOpen = mealsCard.classList.toggle("open");
        mealsBody.classList.toggle("hidden", !isOpen);
        mealsTrigger.setAttribute("aria-expanded", String(isOpen));
    });

    // Tiroir Sport (ferme par defaut)
    const workoutsCard = document.getElementById("workouts-drawer-card");
    const workoutsTrigger = document.getElementById("toggle-workouts-drawer");
    const workoutsBody = document.getElementById("workouts-drawer-body");
    workoutsTrigger.addEventListener("click", () => {
        const isOpen = workoutsCard.classList.toggle("open");
        workoutsBody.classList.toggle("hidden", !isOpen);
        workoutsTrigger.setAttribute("aria-expanded", String(isOpen));
    });
}

let assistantTypingTimer = null;
let lastRenderedResponseText = null;

function stopAssistantTyping() {
    if (assistantTypingTimer) {
        clearInterval(assistantTypingTimer);
        assistantTypingTimer = null;
    }
}

function animateAssistantResponse(el, fullText, forceAnimate = false) {
    const target = String(fullText || "");
    if (!forceAnimate && target === lastRenderedResponseText) {
        el.textContent = target;
        el.classList.remove("is-streaming", "is-loading");
        return;
    }

    lastRenderedResponseText = target;
    stopAssistantTyping();

    el.classList.remove("is-loading");
    el.classList.add("is-streaming");
    el.textContent = "";

    const chars = Array.from(target);
    let idx = 0;
    const step = chars.length > 260 ? 3 : chars.length > 120 ? 2 : 1;

    assistantTypingTimer = setInterval(() => {
        idx = Math.min(chars.length, idx + step);
        el.textContent = chars.slice(0, idx).join("");
        if (idx >= chars.length) {
            stopAssistantTyping();
            el.classList.remove("is-streaming");
        }
    }, 16);
}

function renderState(state, options = {}) {
    if (!state) return;

    const activeUid = state.user_id || getCurrentUserId();
    if (!options.skipCacheSave) {
        saveCachedState(activeUid, state);
    }

    if (
        !options.force &&
        currentRenderedState &&
        currentRenderedState.user_id === activeUid &&
        currentRenderedState.version &&
        state.version &&
        currentRenderedState.version === state.version &&
        !options.animateResponse
    ) {
        return;
    }

    currentRenderedState = state;

    const dash = state.dashboard || {};
    const catalogMap = {};
    (state.peripherals_catalog || []).forEach((p) => {
        catalogMap[p.id] = p.label;
    });

    // 1. Carte Assistant en haut (mise a jour uniquement si modifiee)
    const messages = state.chat_messages || [];
    const assistantSig = JSON.stringify({
        messages,
        editorial: dash.editorial?.body || "",
    });
    if (options.force || options.animateResponse || sectionSignatures.assistant !== assistantSig) {
        sectionSignatures.assistant = assistantSig;
        const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
        const actionTagEl = document.getElementById("ai-last-action-tag");
        const responseTextEl = document.getElementById("ai-last-response-text");

        let targetResponseText = "Prêt.";
        if (lastAssistant) {
            actionTagEl.textContent = lastAssistant.actions_summary || "Point 7j";
            targetResponseText = lastAssistant.content;
        } else {
            actionTagEl.textContent = "Synthèse 7j";
            targetResponseText = dash.editorial?.body || "Prêt.";
        }
        if (options.instantText) {
            stopAssistantTyping();
            lastRenderedResponseText = String(targetResponseText || "");
            responseTextEl.classList.remove("is-streaming", "is-loading");
            responseTextEl.textContent = lastRenderedResponseText;
        } else {
            animateAssistantResponse(responseTextEl, targetResponseText, Boolean(options.animateResponse));
        }

        const chatDrawer = document.getElementById("chat-history-drawer");
        chatDrawer.innerHTML = "";
        messages.slice(0, -1).reverse().forEach((m) => {
            const div = document.createElement("div");
            div.className = `history-msg-row role-${m.role}`;
            div.textContent = (m.role === "user" ? "Vous : " : "Cadence : ") + m.content;
            chatDrawer.appendChild(div);
        });
    }

    // 2. Les 10 Barres d'indicateurs (mise a jour en place sans effacer le DOM)
    const gauges = dash.gauges || [];
    const gaugesSig = JSON.stringify(gauges);
    if (options.force || sectionSignatures.gauges !== gaugesSig) {
        sectionSignatures.gauges = gaugesSig;
        const leftCol = document.getElementById("gauges-col-left");
        const rightCol = document.getElementById("gauges-col-right");
        const MAX_SCALE_PCT = 140;

        const existingRows = [
            ...Array.from(leftCol.querySelectorAll(".indicator-row")),
            ...Array.from(rightCol.querySelectorAll(".indicator-row")),
        ];
        const canPatchInPlace = existingRows.length === gauges.length && gauges.length > 0;

        if (!canPatchInPlace) {
            leftCol.innerHTML = "";
            rightCol.innerHTML = "";
        }

        gauges.forEach((g, idx) => {
            const fillWidth = Math.min(100, Math.max(2, (g.percentage / MAX_SCALE_PCT) * 100));
            const eqLeft = (g.eq_min_pct / MAX_SCALE_PCT) * 100;
            const eqWidth = ((g.eq_max_pct - g.eq_min_pct) / MAX_SCALE_PCT) * 100;
            const tooltip = `${g.label} : ${g.average} / ${g.adjusted_target} ${g.unit} (${g.percentage}% de la cible, dont +${g.sport_bonus} ${g.unit} liés au sport)`;

            if (canPatchInPlace) {
                const row = existingRows[idx];
                row.title = tooltip;
                const lblEl = row.querySelector(".ind-label");
                if (lblEl && lblEl.textContent !== g.label) lblEl.textContent = g.label;
                const eqEl = row.querySelector(".ind-eq-zone");
                if (eqEl) {
                    eqEl.style.left = `${eqLeft.toFixed(1)}%`;
                    eqEl.style.width = `${eqWidth.toFixed(1)}%`;
                }
                const fillEl = row.querySelector(".ind-fill");
                if (fillEl) {
                    fillEl.className = `ind-fill status-${g.status}`;
                    fillEl.style.width = `${fillWidth.toFixed(1)}%`;
                }
                const valEl = row.querySelector(".ind-values");
                if (valEl) {
                    valEl.innerHTML = `<strong>${g.average}</strong> / ${g.adjusted_target} ${g.unit}`;
                }
            } else {
                const row = document.createElement("div");
                row.className = "indicator-row";
                row.title = tooltip;
                row.innerHTML = `
                    <span class="ind-label">${g.label}</span>
                    <div class="ind-track">
                        <div class="ind-eq-zone" style="left:${eqLeft.toFixed(1)}%; width:${eqWidth.toFixed(1)}%;"></div>
                        <div class="ind-fill status-${g.status}" style="width:${fillWidth.toFixed(1)}%;"></div>
                    </div>
                    <span class="ind-values"><strong>${g.average}</strong> / ${g.adjusted_target} ${g.unit}</span>
                `;
                if (idx < 5) {
                    leftCol.appendChild(row);
                } else {
                    rightCol.appendChild(row);
                }
            }
        });
    }

    // 3. Bas Gauche : Historique des Repas deroulant (reconstruit uniquement si les repas ont change)
    if (!window._expandedMealIds) {
        window._expandedMealIds = new Set();
    }
    const expandedMealIds = window._expandedMealIds;

    const meals = state.meals || [];
    const mealsSig = JSON.stringify(meals);
    if (options.force || sectionSignatures.meals !== mealsSig) {
        sectionSignatures.meals = mealsSig;
        const mealsList = document.getElementById("meals-history-list");
        const mealsCountLbl = document.getElementById("meals-count-label");
        mealsList.innerHTML = "";
        mealsCountLbl.textContent = `${meals.length} repas`;

        if (!meals.length) {
            mealsList.innerHTML = `<div class="empty-note">Aucun repas enregistré.</div>`;
        } else {
            const mealsByDay = {};
            meals.forEach((m) => {
                if (!mealsByDay[m.meal_date]) mealsByDay[m.meal_date] = [];
                mealsByDay[m.meal_date].push(m);
            });

            const sortedDays = Object.keys(mealsByDay).sort().reverse();
            sortedDays.forEach((dayIso) => {
                const dayMeals = mealsByDay[dayIso];
                dayMeals.sort((a, b) => (SLOT_ORDER[a.meal_type] || 9) - (SLOT_ORDER[b.meal_type] || 9));
                const dayTotalKcal = Math.round(
                    dayMeals.reduce((sum, item) => sum + (item.nutrients?.calories || 0), 0)
                );

                const groupEl = document.createElement("div");
                groupEl.className = "day-group";
                groupEl.innerHTML = `
                    <div class="day-group-header">
                        <span>${formatDayHeader(dayIso)}</span>
                        <span>${dayTotalKcal} kcal</span>
                    </div>
                    <div class="day-group-box"></div>
                `;

                const boxEl = groupEl.querySelector(".day-group-box");
                dayMeals.forEach((m) => {
                    const n = m.nutrients || {};
                    const dishTextLower = (m.dish_text || "").toLowerCase();
                    const periphNames = (m.peripherals || [])
                        .map((pid) => catalogMap[pid] || pid)
                        .filter((pname) => !dishTextLower.includes(pname.toLowerCase()));
                    const periphSub = periphNames.length ? `<span class="item-sub">+ ${periphNames.join(", ")}</span>` : "";
                    const portionSub = m.portion_size && m.portion_size !== "normal" ? `<span class="item-sub">[${m.portion_size}]</span>` : "";
                    const isExpanded = expandedMealIds.has(m.id);

                    const fmtVal = (val, dec = 0) => {
                        const num = Number(val || 0);
                        return dec === 0 ? String(Math.round(num)) : num.toFixed(dec).replace(/\.0+$/, "");
                    };

                    const mealSpecs = [
                        { label: "Énergie", val: fmtVal(n.calories, 0), unit: "kcal" },
                        { label: "Protéines", val: fmtVal(n.proteins, 0), unit: "g" },
                        { label: "Glucides", val: fmtVal(n.carbs, 0), unit: "g" },
                        { label: "Lipides", val: fmtVal(n.lipids, 0), unit: "g" },
                        { label: "Fibres", val: fmtVal(n.fiber, 1), unit: "g" },
                        { label: "Oméga-3", val: fmtVal(n.omega3, 2), unit: "g" },
                        { label: "Fer", val: fmtVal(n.iron, 1), unit: "mg" },
                        { label: "Magnésium", val: fmtVal(n.magnesium, 0), unit: "mg" },
                        { label: "Calcium", val: fmtVal(n.calcium, 0), unit: "mg" },
                    ];

                    const detailsPillsHtml = mealSpecs
                        .map(
                            (sp) => `
                            <div class="meal-nutrient-pill">
                                <span class="mnp-label">${sp.label}</span>
                                <span class="mnp-value"><strong>${sp.val}</strong> ${sp.unit}</span>
                            </div>`
                        )
                        .join("");

                    const itemWrap = document.createElement("div");
                    itemWrap.className = `meal-item-wrap${isExpanded ? " is-expanded" : ""}`;

                    itemWrap.innerHTML = `
                        <div class="item-row meal-clickable-row" role="button" tabindex="0" aria-expanded="${isExpanded}">
                            <span class="item-slot">${SLOT_SHORT[m.meal_type] || m.meal_type}</span>
                            <span class="item-main">${m.dish_text}${periphSub}${portionSub}</span>
                            <div class="item-right">
                                <span class="item-kcal">${Math.round(n.calories || 0)} kcal</span>
                                <span class="meal-expand-chevron" aria-hidden="true">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                        <polyline points="6 9 12 15 18 9"></polyline>
                                    </svg>
                                </span>
                                <button type="button" class="item-del" title="Supprimer">×</button>
                            </div>
                        </div>
                        <div class="meal-details-panel${isExpanded ? "" : " hidden"}">
                            <div class="meal-nutrients-grid">
                                ${detailsPillsHtml}
                            </div>
                        </div>
                    `;

                    const rowEl = itemWrap.querySelector(".meal-clickable-row");
                    const detailsEl = itemWrap.querySelector(".meal-details-panel");
                    const delBtn = itemWrap.querySelector(".item-del");

                    const toggleDetails = () => {
                        const nowExpanded = itemWrap.classList.toggle("is-expanded");
                        detailsEl.classList.toggle("hidden", !nowExpanded);
                        rowEl.setAttribute("aria-expanded", String(nowExpanded));
                        if (nowExpanded) {
                            expandedMealIds.add(m.id);
                        } else {
                            expandedMealIds.delete(m.id);
                        }
                    };

                    rowEl.addEventListener("click", (e) => {
                        if (e.target.closest(".item-del")) return;
                        toggleDetails();
                    });

                    rowEl.addEventListener("keydown", (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                            if (e.target.closest(".item-del")) return;
                            e.preventDefault();
                            toggleDetails();
                        }
                    });

                    delBtn.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        isMutating = true;
                        try {
                            expandedMealIds.delete(m.id);
                            const updated = await apiCall(`/api/meals/${m.id}`, { method: "DELETE" });
                            renderState(updated);
                        } finally {
                            isMutating = false;
                        }
                    });
                    boxEl.appendChild(itemWrap);
                });

                mealsList.appendChild(groupEl);
            });
        }
    }

    // 4. Bas Droite : Historique & Planning Sport deroulant (reconstruit uniquement si les seances ont change)
    const workouts = state.workouts || [];
    const workoutsSig = JSON.stringify(workouts);
    if (options.force || sectionSignatures.workouts !== workoutsSig) {
        sectionSignatures.workouts = workoutsSig;
        const workoutsList = document.getElementById("workouts-history-list");
        const workoutsCountLbl = document.getElementById("workouts-count-label");
        workoutsList.innerHTML = "";
        const doneCount = workouts.filter((w) => w.status === "realisee").length;
        const plannedCount = workouts.filter((w) => w.status === "prevue").length;
        workoutsCountLbl.textContent = `${doneCount} faite(s) · ${plannedCount} prévue(s)`;

        if (!workouts.length) {
            workoutsList.innerHTML = `<div class="empty-note">Aucune activité enregistrée.</div>`;
        } else {
            const workoutsByDay = {};
            workouts.forEach((w) => {
                if (!workoutsByDay[w.workout_date]) workoutsByDay[w.workout_date] = [];
                workoutsByDay[w.workout_date].push(w);
            });

            const sortedWorkoutDays = Object.keys(workoutsByDay).sort().reverse();
            sortedWorkoutDays.forEach((dayIso) => {
                const dayWorkouts = workoutsByDay[dayIso];
                const groupEl = document.createElement("div");
                groupEl.className = "day-group";
                groupEl.innerHTML = `
                    <div class="day-group-header">
                        <span>${formatDayHeader(dayIso)}</span>
                    </div>
                    <div class="day-group-box"></div>
                `;

                const boxEl = groupEl.querySelector(".day-group-box");
                dayWorkouts.forEach((w) => {
                    const row = document.createElement("div");
                    row.className = "item-row";
                    const isDone = w.status === "realisee";
                    const exp = w.expenditure || {};
                    row.title = `Dépense : +${Math.round(exp.calories || 0)} kcal · +${Math.round(exp.carbs || 0)}g Glucides · +${Math.round(exp.proteins || 0)}g Protéines`;

                    row.innerHTML = `
                        <span class="item-main">${w.title} <span class="item-sub">${w.duration_min} min · ${w.intensity}</span></span>
                        <div class="item-right">
                            <button type="button" class="apple-status-pill ${isDone ? "is-done" : "is-planned"}" title="Cliquer pour basculer Fait / Prévu">
                                ${isDone ? "Fait" : "Prévu"}
                            </button>
                            <button type="button" class="item-del" title="Supprimer">×</button>
                        </div>
                    `;

                    row.querySelector(".apple-status-pill").addEventListener("click", async () => {
                        isMutating = true;
                        try {
                            const nextStatus = isDone ? "prevue" : "realisee";
                            const updated = await apiCall(`/api/workouts/${w.id}/status`, {
                                method: "PATCH",
                                body: JSON.stringify({ status: nextStatus }),
                            });
                            renderState(updated);
                        } finally {
                            isMutating = false;
                        }
                    });

                    row.querySelector(".item-del").addEventListener("click", async () => {
                        isMutating = true;
                        try {
                            const updated = await apiCall(`/api/workouts/${w.id}`, { method: "DELETE" });
                            renderState(updated);
                        } finally {
                            isMutating = false;
                        }
                    });

                    boxEl.appendChild(row);
                });

                workoutsList.appendChild(groupEl);
            });
        }
    }

    // 5. Page Reglages & Profil actif (mise a jour uniquement si le profil a change)
    const prof = state.profile || {};
    const profileSig = JSON.stringify({ activeUid, prof });
    if (options.force || sectionSignatures.profile !== profileSig) {
        sectionSignatures.profile = profileSig;
        applyHeaderProfileBranding(activeUid);

        document.getElementById("prof-sex").value = prof.sex || "H";
        document.getElementById("prof-age").value = prof.age || 29;
        document.getElementById("prof-height").value = prof.height_cm || 179;
        document.getElementById("prof-weight").value = prof.weight_kg || 74;
        document.getElementById("prof-activity").value = prof.activity_level || "modere";
        document.getElementById("prof-goal").value = prof.goal || "performance";
        document.getElementById("prof-excluded").value = prof.excluded_foods || "";
        document.getElementById("prof-llm-provider").value = prof.llm_provider || "auto";
        document.getElementById("prof-llm-model").value = prof.llm_model || "gemini-2.0-flash";
        const apiKeyInput = document.getElementById("prof-api-key");
        apiKeyInput.value = prof.api_key || "";
        if (prof.env_api_key_active && !prof.api_key) {
            apiKeyInput.placeholder = "Cle GEMINI_API_KEY du serveur active par defaut (optionnel)";
        } else {
            apiKeyInput.placeholder = "Cle AIza... (Gemini), gsk_... (Groq) ou sk-or-...";
        }

        const activeTags = new Set(prof.dietary_tags || []);
        document.querySelectorAll("#prof-diet-tags input[type='checkbox']").forEach((cb) => {
            cb.checked = activeTags.has(cb.value);
        });
    }
}

async function syncWithServerIfChanged(forceFullFetch = false) {
    if (isMutating) return;
    const activeProfile = getSelectedProfile();
    if (!activeProfile) return;

    try {
        if (!forceFullFetch && currentRenderedState && currentRenderedState.version) {
            const verInfo = await apiCall("/api/version");
            if (verInfo && verInfo.version === currentRenderedState.version) {
                return;
            }
        }
        const freshState = await apiCall("/api/state");
        if (!isMutating) {
            renderState(freshState);
        }
    } catch (_) {
        // Silencieux en cas de perte reseau temporaire : on conserve le cache affiche
    }
}

function startLiveSync() {
    if (syncIntervalId) clearInterval(syncIntervalId);
    syncIntervalId = setInterval(() => {
        if (document.visibilityState === "visible") {
            syncWithServerIfChanged(false);
        }
    }, 2500);

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            syncWithServerIfChanged(false);
        }
    });

    window.addEventListener("focus", () => {
        syncWithServerIfChanged(false);
    });

    window.addEventListener("storage", (e) => {
        const uid = getCurrentUserId();
        if (e.key === getStateCacheKey(uid) && e.newValue) {
            try {
                const updated = JSON.parse(e.newValue);
                renderState(updated, { skipCacheSave: true, instantText: true });
            } catch (_) {}
        }
    });
}

async function loadProfileWithCacheFirst(profileId) {
    applyHeaderProfileBranding(profileId);
    const cached = loadCachedState(profileId);
    if (cached) {
        renderState(cached, { skipCacheSave: true, instantText: true });
    }
    await syncWithServerIfChanged(!cached);
}

async function sendChatMessage(messageText) {
    const input = document.getElementById("chat-input");
    const submitBtn = document.getElementById("chat-submit-btn");
    const responseTextEl = document.getElementById("ai-last-response-text");

    isMutating = true;
    submitBtn.disabled = true;
    stopAssistantTyping();
    responseTextEl.classList.remove("is-streaming");
    responseTextEl.classList.add("is-loading");
    responseTextEl.textContent = "Analyse en cours...";
    try {
        const updated = await apiCall("/api/chat", {
            method: "POST",
            body: JSON.stringify({ message: messageText }),
        });
        input.value = "";
        renderState(updated, { animateResponse: true });
    } catch (err) {
        stopAssistantTyping();
        responseTextEl.classList.remove("is-streaming", "is-loading");
        responseTextEl.textContent = "Erreur : " + err.message;
    } finally {
        isMutating = false;
        submitBtn.disabled = false;
    }
}

function initInteractions() {
    const stickyContainer = document.querySelector(".spotlight-sticky-container");
    if (stickyContainer) {
        window.addEventListener("scroll", () => {
            stickyContainer.classList.toggle("is-stuck", window.scrollY > 15);
        }, { passive: true });
    }

    document.getElementById("chat-form").addEventListener("submit", (e) => {
        e.preventDefault();
        const txt = document.getElementById("chat-input").value.trim();
        if (txt) sendChatMessage(txt);
    });

    document.querySelectorAll(".suggestion-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            sendChatMessage(chip.dataset.prompt);
        });
    });

    const providerDefaultModels = {
        opencode: "glm-5.3-flash-free",
        gemini: "gemini-2.0-flash",
        groq: "llama-3.3-70b-versatile",
        openrouter: "meta-llama/llama-3.3-70b-instruct:free",
        openai: "gpt-4o-mini",
    };

    document.getElementById("prof-llm-provider").addEventListener("change", (e) => {
        const selected = e.target.value;
        const modelInput = document.getElementById("prof-llm-model");
        if (providerDefaultModels[selected]) {
            modelInput.value = providerDefaultModels[selected];
        }
    });

    function collectProfilePayload(verifyLlm = true) {
        const dietTags = [];
        document.querySelectorAll("#prof-diet-tags input[type='checkbox']:checked").forEach((cb) => {
            dietTags.push(cb.value);
        });
        return {
            sex: document.getElementById("prof-sex").value,
            age: Number(document.getElementById("prof-age").value),
            height_cm: Number(document.getElementById("prof-height").value),
            weight_kg: Number(document.getElementById("prof-weight").value),
            activity_level: document.getElementById("prof-activity").value,
            goal: document.getElementById("prof-goal").value,
            dietary_tags: dietTags,
            excluded_foods: document.getElementById("prof-excluded").value,
            llm_provider: document.getElementById("prof-llm-provider").value,
            llm_model: document.getElementById("prof-llm-model").value,
            api_key: document.getElementById("prof-api-key").value,
            verify_llm: verifyLlm,
        };
    }

    document.getElementById("save-physio-btn").addEventListener("click", async () => {
        const physioBtn = document.getElementById("save-physio-btn");
        const physioFeedback = document.getElementById("physio-save-feedback");
        isMutating = true;
        physioBtn.disabled = true;
        physioBtn.textContent = "Enregistrement...";
        physioFeedback.className = "settings-feedback";
        physioFeedback.textContent = "Mise à jour du profil physiologique...";

        try {
            const updated = await apiCall("/api/profile", {
                method: "PUT",
                body: JSON.stringify(collectProfilePayload(false)),
            });
            renderState(updated);
            const baseKcal = Math.round(updated.profile?.calculated_baseline?.calories || 0);
            physioFeedback.className = "settings-feedback is-success";
            physioFeedback.textContent = baseKcal
                ? `Profil physiologique enregistré (besoin de base hors sport : ${baseKcal} kcal/j).`
                : "Profil physiologique enregistré avec succès.";
            physioBtn.textContent = "Enregistré";
            setTimeout(() => {
                physioBtn.textContent = "Enregistrer le profil";
            }, 2200);
        } catch (err) {
            physioFeedback.className = "settings-feedback is-warning";
            physioFeedback.textContent = "Erreur lors de l'enregistrement : " + err.message;
            physioBtn.textContent = "Enregistrer le profil";
        } finally {
            isMutating = false;
            physioBtn.disabled = false;
        }
    });

    const savePrefsBtn = document.getElementById("save-prefs-btn");
    if (savePrefsBtn) {
        savePrefsBtn.addEventListener("click", async () => {
            const prefsFeedback = document.getElementById("prefs-save-feedback");
            isMutating = true;
            savePrefsBtn.disabled = true;
            savePrefsBtn.textContent = "Enregistrement...";
            prefsFeedback.className = "settings-feedback";
            prefsFeedback.textContent = "Mise à jour des préférences alimentaires...";

            try {
                const updated = await apiCall("/api/profile", {
                    method: "PUT",
                    body: JSON.stringify(collectProfilePayload(false)),
                });
                renderState(updated);
                prefsFeedback.className = "settings-feedback is-success";
                prefsFeedback.textContent = "Préférences alimentaires enregistrées avec succès.";
                savePrefsBtn.textContent = "Enregistré";
                setTimeout(() => {
                    savePrefsBtn.textContent = "Enregistrer les préférences";
                }, 2200);
            } catch (err) {
                prefsFeedback.className = "settings-feedback is-warning";
                prefsFeedback.textContent = "Erreur lors de l'enregistrement : " + err.message;
                savePrefsBtn.textContent = "Enregistrer les préférences";
            } finally {
                isMutating = false;
                savePrefsBtn.disabled = false;
            }
        });
    }

    document.getElementById("settings-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const saveBtn = document.getElementById("save-settings-btn");
        const feedbackEl = document.getElementById("settings-save-feedback");
        isMutating = true;
        saveBtn.disabled = true;
        saveBtn.textContent = "Vérification...";
        feedbackEl.className = "settings-feedback";
        feedbackEl.textContent = "Enregistrement et test de la connexion IA en cours...";

        try {
            const updated = await apiCall("/api/profile", {
                method: "PUT",
                body: JSON.stringify(collectProfilePayload(true)),
            });
            renderState(updated);
            const verif = updated.llm_verification || {};
            feedbackEl.className = `settings-feedback ${verif.ok === false ? "is-warning" : "is-success"}`;
            feedbackEl.textContent = verif.message || "Configuration IA enregistrée avec succès.";
            saveBtn.textContent = "Enregistré";
            setTimeout(() => {
                saveBtn.textContent = "Tester & Enregistrer l'IA";
            }, 2200);
        } catch (err) {
            feedbackEl.className = "settings-feedback is-warning";
            feedbackEl.textContent = "Erreur lors de l'enregistrement : " + err.message;
            saveBtn.textContent = "Tester & Enregistrer l'IA";
        } finally {
            isMutating = false;
            saveBtn.disabled = false;
        }
    });

    document.getElementById("reset-demo-btn").addEventListener("click", async () => {
        isMutating = true;
        try {
            const updated = await apiCall("/api/demo/reset", { method: "POST" });
            renderState(updated);
        } finally {
            isMutating = false;
        }
    });

    document.getElementById("clear-data-btn").addEventListener("click", async () => {
        isMutating = true;
        try {
            const updated = await apiCall("/api/demo/clear", { method: "POST" });
            renderState(updated);
        } finally {
            isMutating = false;
        }
    });

    const launcherOverlay = document.getElementById("profile-launcher-overlay");
    const logoutProfileBtn = document.getElementById("logout-profile-btn");

    if (logoutProfileBtn && launcherOverlay) {
        logoutProfileBtn.addEventListener("click", () => {
            localStorage.removeItem(STORAGE_KEY_PROFILE);
            sessionStorage.removeItem(SESSION_KEY_LOCAL_OVERRIDE);
            currentRenderedState = null;
            resetSectionSignatures();
            showPage("main");
            launcherOverlay.classList.remove("hidden");
        });
    }

    document.querySelectorAll(".launcher-profile-card").forEach((card) => {
        card.addEventListener("click", async () => {
            const chosen = card.dataset.profile;
            const clean = setSelectedProfile(chosen);
            currentRenderedState = null;
            resetSectionSignatures();
            if (launcherOverlay) launcherOverlay.classList.add("hidden");
            await loadProfileWithCacheFirst(clean);
        });
    });
}

document.addEventListener("DOMContentLoaded", async () => {
    initPageNavigationAndDrawers();
    initInteractions();
    startLiveSync();

    const launcherOverlay = document.getElementById("profile-launcher-overlay");
    const savedProfile = getSelectedProfile();

    if (!savedProfile) {
        if (launcherOverlay) launcherOverlay.classList.remove("hidden");
    } else {
        await loadProfileWithCacheFirst(savedProfile);
    }
});
