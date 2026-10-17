const SLOT_ORDER = {
    petit_dejeuner: 1,
    dejeuner: 2,
    collation: 3,
    diner: 4,
};

const SLOT_SHORT = {
    petit_dejeuner: "Matin",
    dejeuner: "Midi",
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

function normalizeUserSlug(raw) {
    if (!raw) return "default";
    const cleaned = String(raw).trim().toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 32);
    return cleaned || "default";
}

function getCurrentUserId() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("user");
    if (fromUrl) {
        const slug = normalizeUserSlug(fromUrl);
        localStorage.setItem("cadence_user_id", slug);
        return slug;
    }
    const stored = localStorage.getItem("cadence_user_id");
    return stored ? normalizeUserSlug(stored) : "default";
}

function setCurrentUserId(newId) {
    const slug = normalizeUserSlug(newId);
    localStorage.setItem("cadence_user_id", slug);
    const url = new URL(window.location.href);
    if (slug === "default") {
        url.searchParams.delete("user");
    } else {
        url.searchParams.set("user", slug);
    }
    window.history.replaceState({}, "", url.toString());
    return slug;
}

function buildShareUrl(userId) {
    const slug = normalizeUserSlug(userId);
    const base = window.location.origin + window.location.pathname;
    return slug === "default" ? base : `${base}?user=${encodeURIComponent(slug)}`;
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

function initPageNavigationAndDrawers() {
    document.querySelectorAll(".seg-tab").forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.page;
            document.querySelectorAll(".seg-tab").forEach((b) => b.classList.toggle("active", b === btn));
            document.querySelectorAll(".page-view").forEach((v) => v.classList.toggle("active", v.id === `page-${target}`));
        });
    });

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

function renderState(state) {
    const dash = state.dashboard || {};
    const catalogMap = {};
    (state.peripherals_catalog || []).forEach((p) => {
        catalogMap[p.id] = p.label;
    });

    // 1. Carte Assistant en haut
    const messages = state.chat_messages || [];
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    const actionTagEl = document.getElementById("ai-last-action-tag");
    const responseTextEl = document.getElementById("ai-last-response-text");

    if (lastAssistant) {
        actionTagEl.textContent = lastAssistant.actions_summary || "Point 7j";
        responseTextEl.textContent = lastAssistant.content;
    } else {
        actionTagEl.textContent = "Synthèse 7j";
        responseTextEl.textContent = dash.editorial?.body || "Prêt.";
    }

    const chatDrawer = document.getElementById("chat-history-drawer");
    chatDrawer.innerHTML = "";
    messages.slice(0, -1).reverse().forEach((m) => {
        const div = document.createElement("div");
        div.className = `history-msg-row role-${m.role}`;
        div.textContent = (m.role === "user" ? "Vous : " : "Cadence : ") + m.content;
        chatDrawer.appendChild(div);
    });

    // 2. Les 10 Barres d'indicateurs (Moyenne 7j)
    const leftCol = document.getElementById("gauges-col-left");
    const rightCol = document.getElementById("gauges-col-right");
    leftCol.innerHTML = "";
    rightCol.innerHTML = "";

    const MAX_SCALE_PCT = 140;
    const gauges = dash.gauges || [];

    gauges.forEach((g, idx) => {
        const row = document.createElement("div");
        row.className = "indicator-row";

        const fillWidth = Math.min(100, Math.max(2, (g.percentage / MAX_SCALE_PCT) * 100));
        const eqLeft = (g.eq_min_pct / MAX_SCALE_PCT) * 100;
        const eqWidth = ((g.eq_max_pct - g.eq_min_pct) / MAX_SCALE_PCT) * 100;

        row.title = `${g.label} : ${g.average} / ${g.adjusted_target} ${g.unit} (${g.percentage}% de la cible, dont +${g.sport_bonus} ${g.unit} liés au sport)`;

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
    });

    // 3. Bas Gauche : Historique des Repas deroulant, groupe et trie par jour
    const mealsList = document.getElementById("meals-history-list");
    const mealsCountLbl = document.getElementById("meals-count-label");
    mealsList.innerHTML = "";
    const meals = state.meals || [];
    mealsCountLbl.textContent = `${meals.length} repas`;

    if (!meals.length) {
        mealsList.innerHTML = `<div class="empty-note">Aucun repas enregistré.</div>`;
    } else {
        const mealsByDay = {};
        meals.forEach((m) => {
            if (!mealsByDay[m.meal_date]) mealsByDay[m.meal_date] = [];
            mealsByDay[m.meal_date].push(m);
        });

        // Trier les jours du plus recent au plus ancien
        const sortedDays = Object.keys(mealsByDay).sort().reverse();
        sortedDays.forEach((dayIso) => {
            const dayMeals = mealsByDay[dayIso];
            // Trier a l'interieur du jour : Matin -> Midi -> Collation -> Soir
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
                const row = document.createElement("div");
                row.className = "item-row";
                const n = m.nutrients || {};
                const periphNames = (m.peripherals || []).map((pid) => catalogMap[pid] || pid);
                const periphSub = periphNames.length ? `<span class="item-sub">+ ${periphNames.join(", ")}</span>` : "";
                const portionSub = m.portion_size && m.portion_size !== "normal" ? `<span class="item-sub">[${m.portion_size}]</span>` : "";

                row.title = `${Math.round(n.calories || 0)} kcal · ${Math.round(n.proteins || 0)}g P · ${Math.round(n.carbs || 0)}g G · ${Math.round(n.lipids || 0)}g L · ${n.fiber || 0}g Fibres · ${n.omega3 || 0}g Oméga-3`;

                row.innerHTML = `
                    <span class="item-slot">${SLOT_SHORT[m.meal_type] || m.meal_type}</span>
                    <span class="item-main">${m.dish_text}${periphSub}${portionSub}</span>
                    <div class="item-right">
                        <span class="item-kcal">${Math.round(n.calories || 0)} kcal</span>
                        <button type="button" class="item-del" title="Supprimer">×</button>
                    </div>
                `;

                row.querySelector(".item-del").addEventListener("click", async () => {
                    const updated = await apiCall(`/api/meals/${m.id}`, { method: "DELETE" });
                    renderState(updated);
                });
                boxEl.appendChild(row);
            });

            mealsList.appendChild(groupEl);
        });
    }

    // 4. Bas Droite : Historique & Planning Sport deroulant, groupe et trie par jour
    const workoutsList = document.getElementById("workouts-history-list");
    const workoutsCountLbl = document.getElementById("workouts-count-label");
    workoutsList.innerHTML = "";
    const workouts = state.workouts || [];
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
                row.title = `Dépense : +${Math.round(exp.calories || 0)} kcal · +${Math.round(exp.carbs || 0)}g Glucides · +${Math.round(exp.water_ml || 0)}ml Eau`;

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
                    const nextStatus = isDone ? "prevue" : "realisee";
                    const updated = await apiCall(`/api/workouts/${w.id}/status`, {
                        method: "PATCH",
                        body: JSON.stringify({ status: nextStatus }),
                    });
                    renderState(updated);
                });

                row.querySelector(".item-del").addEventListener("click", async () => {
                    const updated = await apiCall(`/api/workouts/${w.id}`, { method: "DELETE" });
                    renderState(updated);
                });

                boxEl.appendChild(row);
            });

            workoutsList.appendChild(groupEl);
        });
    }

    // 5. Page Reglages & Espace actif
    const prof = state.profile || {};
    const activeUid = state.user_id || getCurrentUserId();
    const badgeEl = document.getElementById("active-user-badge");
    if (badgeEl) {
        badgeEl.textContent = activeUid === "default" ? "principal" : activeUid;
    }
    const spaceInputEl = document.getElementById("user-space-input");
    const sharePreviewEl = document.getElementById("share-link-preview");
    if (spaceInputEl && document.activeElement !== spaceInputEl) {
        spaceInputEl.value = activeUid;
    }
    if (sharePreviewEl) {
        sharePreviewEl.value = buildShareUrl(spaceInputEl ? spaceInputEl.value : activeUid);
    }

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

async function sendChatMessage(messageText) {
    const input = document.getElementById("chat-input");
    const submitBtn = document.getElementById("chat-submit-btn");
    const responseTextEl = document.getElementById("ai-last-response-text");

    submitBtn.disabled = true;
    responseTextEl.textContent = "Mise à jour en cours...";
    try {
        const updated = await apiCall("/api/chat", {
            method: "POST",
            body: JSON.stringify({ message: messageText }),
        });
        input.value = "";
        renderState(updated);
    } catch (err) {
        responseTextEl.textContent = "Erreur : " + err.message;
    } finally {
        submitBtn.disabled = false;
    }
}

function initInteractions() {
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
            physioBtn.disabled = false;
        }
    });

    document.getElementById("settings-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const saveBtn = document.getElementById("save-settings-btn");
        const feedbackEl = document.getElementById("settings-save-feedback");
        saveBtn.disabled = true;
        saveBtn.textContent = "Vérification...";
        feedbackEl.className = "settings-feedback";
        feedbackEl.textContent = "Enregistrement et test de la clé API en cours...";

        try {
            const updated = await apiCall("/api/profile", {
                method: "PUT",
                body: JSON.stringify(collectProfilePayload(true)),
            });
            renderState(updated);
            const verif = updated.llm_verification || {};
            feedbackEl.className = `settings-feedback ${verif.ok === false ? "is-warning" : "is-success"}`;
            feedbackEl.textContent = verif.message || "Réglages enregistrés avec succès.";
            saveBtn.textContent = "Enregistré";
            setTimeout(() => {
                saveBtn.textContent = "Enregistrer";
            }, 2200);
        } catch (err) {
            feedbackEl.className = "settings-feedback is-warning";
            feedbackEl.textContent = "Erreur lors de l'enregistrement : " + err.message;
            saveBtn.textContent = "Enregistrer";
        } finally {
            saveBtn.disabled = false;
        }
    });

    document.getElementById("reset-demo-btn").addEventListener("click", async () => {
        const updated = await apiCall("/api/demo/reset", { method: "POST" });
        renderState(updated);
    });

    document.getElementById("clear-data-btn").addEventListener("click", async () => {
        const updated = await apiCall("/api/demo/clear", { method: "POST" });
        renderState(updated);
    });

    const badgeEl = document.getElementById("active-user-badge");
    const spaceInputEl = document.getElementById("user-space-input");
    const sharePreviewEl = document.getElementById("share-link-preview");
    const switchSpaceBtn = document.getElementById("switch-space-btn");
    const copyLinkBtn = document.getElementById("copy-share-link-btn");
    const spaceFeedbackEl = document.getElementById("space-share-feedback");

    if (badgeEl) {
        badgeEl.addEventListener("click", () => {
            const settingsTab = document.querySelector(".seg-tab[data-page='settings']");
            if (settingsTab) settingsTab.click();
            if (spaceInputEl) spaceInputEl.focus();
        });
    }

    if (spaceInputEl && sharePreviewEl) {
        spaceInputEl.addEventListener("input", () => {
            sharePreviewEl.value = buildShareUrl(spaceInputEl.value);
        });
    }

    if (switchSpaceBtn && spaceInputEl) {
        switchSpaceBtn.addEventListener("click", async () => {
            const nextUid = setCurrentUserId(spaceInputEl.value);
            spaceInputEl.value = nextUid;
            if (sharePreviewEl) sharePreviewEl.value = buildShareUrl(nextUid);
            const updated = await apiCall("/api/state");
            renderState(updated);
            if (spaceFeedbackEl) {
                spaceFeedbackEl.className = "settings-feedback is-success";
                spaceFeedbackEl.textContent = `Espace actif bascule sur "${nextUid}".`;
            }
        });
    }

    if (copyLinkBtn && spaceInputEl) {
        copyLinkBtn.addEventListener("click", async () => {
            const targetSlug = normalizeUserSlug(spaceInputEl.value);
            const urlToShare = buildShareUrl(targetSlug);
            if (sharePreviewEl) sharePreviewEl.value = urlToShare;
            try {
                await navigator.clipboard.writeText(urlToShare);
                if (spaceFeedbackEl) {
                    spaceFeedbackEl.className = "settings-feedback is-success";
                    spaceFeedbackEl.textContent = `Lien copie pour l'espace "${targetSlug}" : envoyez-lui simplement cette URL.`;
                }
            } catch (_) {
                if (sharePreviewEl) {
                    sharePreviewEl.select();
                }
                if (spaceFeedbackEl) {
                    spaceFeedbackEl.className = "settings-feedback";
                    spaceFeedbackEl.textContent = `Lien pret a copier : ${urlToShare}`;
                }
            }
        });
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    initPageNavigationAndDrawers();
    initInteractions();
    const initial = await apiCall("/api/state");
    renderState(initial);
});
