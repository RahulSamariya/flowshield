// FlowShield Command Dashboard Javascript Interface

document.addEventListener("DOMContentLoaded", () => {
    // API base URL - relative to facilitate deployment
    const API_BASE = "";

    // DOM Elements
    const overallSeverityBadge = document.getElementById("overall-severity-badge");
    const statusPulse = document.getElementById("status-pulse");
    const currentCity = document.getElementById("current-city");
    
    const summaryMonitoredZones = document.getElementById("summary-monitored-zones");
    const summaryOpenIncidents = document.getElementById("summary-open-incidents");
    const summaryCriticalZones = document.getElementById("summary-critical-zones");
    
    const activeIncidentsCount = document.getElementById("active-incidents-count");
    const activeIncidentsList = document.getElementById("active-incidents-list");
    const priorityRankingList = document.getElementById("priority-ranking-list");
    
    const availableResourcesCount = document.getElementById("available-resources-count");
    const availableResourcesList = document.getElementById("available-resources-list");
    
    const optimizationAssignmentsList = document.getElementById("optimization-assignments-list");
    const optimizationGapsList = document.getElementById("optimization-gaps-list");
    
    const responseActionsTbody = document.getElementById("response-actions-tbody");
    
    const timelineFlowList = document.getElementById("timeline-flow-list");
    
    // WHY panel elements
    const whySituationText = document.getElementById("why-situation-text");
    const whySituationSource = document.getElementById("why-situation-source");
    const whyPrioritiesText = document.getElementById("why-priorities-text");
    const whyPrioritiesSource = document.getElementById("why-priorities-source");
    const whyAssignmentsText = document.getElementById("why-assignments-text");
    const whyAssignmentsSource = document.getElementById("why-assignments-source");
    const whyResponsePlanText = document.getElementById("why-response-plan-text");
    const whyResponsePlanSource = document.getElementById("why-response-plan-source");
    
    // Ingest Inputs
    const reportInputText = document.getElementById("report-input-text");
    const zoneHintSelect = document.getElementById("zone-hint-select");
    const submitReportBtn = document.getElementById("submit-report-btn");
    const resetScenarioBtn = document.getElementById("reset-scenario-btn");
    
    // Fetch and redraw state
    async function fetchDashboardState() {
        try {
            const resp = await fetch(`${API_BASE}/api/state`);
            if (!resp.ok) {
                throw new Error(`State API returned HTTP error ${resp.status}`);
            }
            const data = await resp.json();
            renderDashboard(data);
        } catch (err) {
            console.error("Error fetching dashboard state:", err);
        }
    }

    // Main render router
    function renderDashboard(data) {
        // 1. Header & Overall status
        const severity = (data.overall_severity || "normal").toLowerCase();
        overallSeverityBadge.innerText = (data.overall_severity || "NORMAL").toUpperCase();
        
        // Remove existing severity classes
        overallSeverityBadge.className = "status-value";
        overallSeverityBadge.classList.add(`${severity}-text`);
        
        statusPulse.className = "pulse-indicator";
        statusPulse.classList.add(`status-${severity}`);
        
        if (severity === "critical") {
            document.getElementById("system-status-container").classList.add("pulse-glow-critical");
        } else {
            document.getElementById("system-status-container").classList.remove("pulse-glow-critical");
        }
        
        currentCity.innerText = (data.city || "AHMEDABAD").toUpperCase();
        
        // 2. Metrics & Open Incidents
        const incidents = data.incidents || [];
        activeIncidentsCount.innerText = incidents.length;
        summaryOpenIncidents.innerText = incidents.length;
        
        let monitoredZones = new Set();
        let criticalZonesVal = 0;
        if (data.situation_summary && data.situation_summary.zones) {
            Object.entries(data.situation_summary.zones).forEach(([zid, zone]) => {
                monitoredZones.add(zid);
                if (zone.severity === "critical" || zone.severity === "warning") {
                    criticalZonesVal++;
                }
            });
        }
        summaryMonitoredZones.innerText = monitoredZones.size || 3;
        summaryCriticalZones.innerText = criticalZonesVal;
        
        renderIncidentsList(incidents);
        
        // 3. Priorities Table
        renderPriorities(data.priority_results || [], incidents);
        
        // 4. Resources
        const resources = data.resources_used || [];
        availableResourcesCount.innerText = resources.length;
        renderResources(resources);
        
        // 5. Allocations & Gaps
        const opt = data.optimization_result || {};
        renderAllocations(opt.assignments || [], opt.unassigned_incidents || [], incidents, resources);
        
        // 6. Actions Log
        renderActions(data.actions || [], incidents);
        
        // 7. Why panel Granite AI explanations
        const why = data.why_panel || {};
        renderWhyPanelItem(why.reasoning_situation, whySituationText, whySituationSource);
        renderWhyPanelItem(why.reasoning_priorities, whyPrioritiesText, whyPrioritiesSource);
        renderWhyPanelItem(why.reasoning_assignments, whyAssignmentsText, whyAssignmentsSource);
        renderWhyPanelItem(why.operator_response, whyResponsePlanText, whyResponsePlanSource);
        
        // 8. Timeline
        renderTimeline(data.timeline || []);
    }

    // Render Incidents Tab
    function renderIncidentsList(incidents) {
        if (incidents.length === 0) {
            activeIncidentsList.innerHTML = `<div class="empty-placeholder">No active open incidents detected in Ahmedabad.</div>`;
            return;
        }
        
        activeIncidentsList.innerHTML = incidents.map(inc => {
            const sevLower = (inc.severity || "low").toLowerCase();
            const riskPercent = Math.min(100, Math.max(0, Math.round(inc.risk_score * 100)));
            return `
                <div class="incident-card card-${sevLower}">
                    <div class="incident-header">
                        <span class="incident-title">${inc.title}</span>
                        <span class="incident-severity-badge badge-${sevLower}">${inc.severity}</span>
                    </div>
                    <div class="incident-info">
                        <div>
                            <span class="incident-id-lbl">ID:</span> ${inc.id.substring(0, 8)}... | 
                            <span class="incident-id-lbl">Zone:</span> <strong>${inc.zone_id}</strong>
                        </div>
                        <div class="incident-risk-section">
                            <span class="incident-id-lbl">Risk:</span>
                            <div class="risk-bar-container">
                                <div class="risk-bar" style="width: ${riskPercent}%; background-color: ${getRiskBarColor(inc.risk_score)}"></div>
                            </div>
                            <span class="risk-val">${inc.risk_score.toFixed(2)}</span>
                        </div>
                    </div>
                    <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.25rem;">
                        <strong>Impacted:</strong> ${inc.affected_people || 0} residents | 
                        <strong>Deadline:</strong> ${inc.response_deadline_elapsed_seconds ? inc.response_deadline_elapsed_seconds + "s remaining" : "none"}
                    </div>
                </div>
            `;
        }).join("");
    }

    function getRiskBarColor(score) {
        if (score >= 0.75) return "var(--color-danger)";
        if (score >= 0.50) return "var(--color-warning)";
        if (score >= 0.25) return "var(--color-accent)";
        return "var(--color-success)";
    }

    // Render Priority Breakdown
    function renderPriorities(priorities, incidents) {
        if (priorities.length === 0) {
            priorityRankingList.innerHTML = `<div class="empty-placeholder">No priorities calculated yet. Ingest an incident report first.</div>`;
            return;
        }
        
        const incMap = new Map(incidents.map(i => [i.id, i]));
        
        priorityRankingList.innerHTML = priorities.map((pr, index) => {
            const inc = incMap.get(pr.incident_id) || { title: `Incident ${pr.incident_id.substring(0, 8)}` };
            const levelClass = (pr.level || "low").toLowerCase();
            const scorePercent = Math.min(100, Math.round(pr.score * 100));
            
            // Build Factor details
            const factorsHTML = (pr.factors || []).map(f => {
                const isZero = f.contribution === 0;
                const weightPercent = Math.round(f.weight * 100);
                const contribPercent = Math.round(f.contribution * 100);
                
                return `
                    <div class="factor-row ${isZero ? 'zero' : ''}">
                        <span class="factor-name">${f.name}</span>
                        <div class="factor-bar-outer">
                            <div class="factor-bar-inner" style="width: ${contribPercent}%"></div>
                        </div>
                        <span class="factor-contrib">${f.contribution.toFixed(2)} (w:${f.weight})</span>
                    </div>
                `;
            }).join("");
            
            const reasonsHTML = (pr.reason_codes || []).map(code => {
                return `<span class="reason-code-tag">${code}</span>`;
            }).join("");

            return `
                <div class="priority-item-card">
                    <div class="priority-item-title">
                        <span>${inc.title}</span>
                        <span class="priority-rank-chip">Rank #${index + 1}</span>
                    </div>
                    <div class="priority-metrics-row">
                        <span>Level: <strong class="${levelClass}-text" style="text-transform: uppercase;">${pr.level}</strong></span>
                        <span>Combined Priority Score: <strong>${pr.score.toFixed(3)}</strong></span>
                    </div>
                    <div class="priority-factors-container">
                        ${factorsHTML}
                    </div>
                    ${reasonsHTML ? `
                        <div class="reason-codes-tag-list">
                            ${reasonsHTML}
                        </div>
                    ` : ""}
                </div>
            `;
        }).join("");
    }

    // Render Resources list
    function renderResources(resources) {
        if (resources.length === 0) {
            availableResourcesList.innerHTML = `<div class="empty-placeholder">No active resources stored in Gujarat list.</div>`;
            return;
        }
        
        availableResourcesList.innerHTML = resources.map(res => {
            const statusLower = (res.status || "available").toLowerCase();
            return `
                <div class="resource-card">
                    <div class="resource-header">
                        <span class="resource-name">${res.name}</span>
                        <span class="resource-badge ${statusLower}">${res.status}</span>
                    </div>
                    <div class="resource-details">
                        <div><strong>Type:</strong> ${res.type}</div>
                        <div><strong>Capacity:</strong> ${res.capacity}</div>
                        <div><strong>Current Location:</strong> ${res.current_zone_id || res.home_zone_id}</div>
                        <div><strong>Depot:</strong> ${res.home_zone_id}</div>
                        ${res.notes ? `<div class="resource-notes">"${res.notes}"</div>` : ""}
                    </div>
                </div>
            `;
        }).join("");
    }

    // Render Allocations card (Assignments & Gaps)
    function renderAllocations(assignments, gaps, incidents, resources) {
        const incMap = new Map(incidents.map(i => [i.id, i]));
        const resMap = new Map(resources.map(r => [r.id, r]));
        
        if (assignments.length === 0) {
            optimizationAssignmentsList.innerHTML = `<div class="empty-placeholder">No resources currently assigned to resolved incidents.</div>`;
        } else {
            optimizationAssignmentsList.innerHTML = assignments.map(a => {
                const inc = incMap.get(a.incident_id) || { title: `Incident ${a.incident_id.substring(0,8)}` };
                const res = resMap.get(a.resource_id) || { name: `Resource ${a.resource_id.substring(0,8)}`, type: 'Utility' };
                const reasonCodes = (a.reason_codes || []).join(", ");
                return `
                    <div class="assignment-card">
                        <div class="assign-header">
                            <span>🛠️ Dispatch: ${res.name} ➡️ ${inc.title}</span>
                            <span class="assign-fit">Fit: ${a.fit_score.toFixed(2)}</span>
                        </div>
                        <div class="assign-details">
                            Zone Link: <strong>${a.resource_zone}</strong> to <strong>${a.incident_zone}</strong> | 
                            Travel ETA: <strong>${a.estimated_travel_minutes.toFixed(1)} mins</strong>
                            ${reasonCodes ? `<br>Rationale Codes: <code style="font-size:0.7rem">${reasonCodes}</code>` : ""}
                        </div>
                    </div>
                `;
            }).join("");
        }
        
        if (gaps.length === 0) {
            optimizationGapsList.innerHTML = `<div class="empty-placeholder">No resource gaps found. All incidents addressed!</div>`;
        } else {
            optimizationGapsList.innerHTML = gaps.map(g => {
                const inc = incMap.get(g.incident_id) || { title: `Incident ${g.incident_id.substring(0,8)}` };
                const reasons = (g.reason_codes || []).join(", ");
                return `
                    <div class="gap-card">
                        <div class="gap-card-title">⚠️ Escalate: ${inc.title}</div>
                        <div class="gap-details">
                            Priority Gap Score: <strong>${g.priority_score.toFixed(3)}</strong><br>
                            Unassigned Reason: <code style="font-weight:bold; color:var(--color-danger);font-size:0.7rem">${reasons}</code>
                        </div>
                    </div>
                `;
            }).join("");
        }
    }

    // Render Actions List Table
    function renderActions(actions, incidents) {
        if (actions.length === 0) {
            responseActionsTbody.innerHTML = `<tr><td colspan="5" class="empty-placeholder" style="text-align:center">No pending response actions generated.</td></tr>`;
            return;
        }
        
        const incMap = new Map(incidents.map(i => [i.id, i]));
        
        responseActionsTbody.innerHTML = actions.map(act => {
            const inc = incMap.get(act.incident_id) || { title: `Incident ${act.incident_id.substring(0,8)}` };
            const statusLower = (act.status || "pending").toLowerCase();
            return `
                <tr>
                    <td style="font-family: var(--font-mono); font-size: 0.72rem;">${act.id.substring(0,8)}</td>
                    <td><strong>${inc.title}</strong></td>
                    <td style="font-family: var(--font-mono); font-size: 0.72rem;">${act.resource_id ? act.resource_id.substring(0,8) : "None (Gap)"}</td>
                    <td><span class="table-status-badge ${statusLower}">${act.status || "pending"}</span></td>
                    <td style="font-size: 0.75rem; color: var(--text-secondary); max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${act.decision_rationale}">
                        ${act.decision_rationale}
                    </td>
                </tr>
            `;
        }).join("");
    }

    // Render Why Panel individual AI explanation
    function renderWhyPanelItem(reasoningItem, textElement, sourceElement) {
        if (!reasoningItem) {
            textElement.innerText = "No AI analysis performed.";
            sourceElement.innerText = "SOURCE: --";
            return;
        }
        
        sourceElement.innerText = `SOURCE: ${(reasoningItem.source || "Deterministic Fallback").toUpperCase()}`;
        
        let textContent = reasoningItem.text || "";
        if (reasoningItem.structured && reasoningItem.structured.steps) {
            textContent += "\n\nPlan Action Steps:\n" + reasoningItem.structured.steps.map((st, i) => `${i+1}. ${st.action || st}`).join("\n");
        }
        textElement.innerText = textContent.trim();
    }

    // Render Timeline Flow
    function renderTimeline(timeline) {
        if (timeline.length === 0) {
            timelineFlowList.innerHTML = `<div class="empty-placeholder">No events ingested into FlowShield history logs yet.</div>`;
            return;
        }
        
        // Sort descending by occurred_at for real-time visibility
        const sorted = [...timeline].sort((a,b) => new Date(b.occurred_at) - new Date(a.occurred_at));
        
        timelineFlowList.innerHTML = sorted.map(evt => {
            const date = new Date(evt.occurred_at);
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
            const itemClass = (evt.severity || "normal").toLowerCase();
            
            return `
                <div class="timeline-item ${itemClass}">
                    <span class="timeline-time">${timeStr} | ${evt.type.replace("_", " ").toUpperCase()}</span>
                    <div class="timeline-title">${evt.title}</div>
                    <div class="timeline-details">${evt.details}</div>
                </div>
            `;
        }).join("");
    }

    // Tab Switch Controller
    const tabButtons = document.querySelectorAll(".card-tabs .tab-btn");
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const parent = btn.closest(".grid-card");
            // Deactivate other tabs in this card
            parent.querySelectorAll(".card-tabs .tab-btn").forEach(b => b.classList.remove("active"));
            parent.querySelectorAll(".tab-content").forEach(c => c.classList.add("hidden"));
            
            // Activate current tab
            btn.classList.add("active");
            const targetId = btn.getAttribute("data-target");
            document.getElementById(targetId).classList.remove("hidden");
        });
    });

    // WHY Panel Tab Switch Controller
    const whyTabButtons = document.querySelectorAll(".why-tabs .why-tab-btn");
    whyTabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            whyTabButtons.forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".why-tab-content").forEach(c => c.classList.add("hidden"));
            
            btn.classList.add("active");
            const targetId = btn.getAttribute("data-target");
            document.getElementById(targetId).classList.remove("hidden");
        });
    });

    // Preset buttons clicks helper
    const presetButtons = document.querySelectorAll(".preset-btn");
    presetButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            reportInputText.value = btn.getAttribute("data-text");
            reportInputText.focus();
        });
    });

    // Report Ingestion Submit
    submitReportBtn.addEventListener("click", async () => {
        const text = reportInputText.value.trim();
        if (!text) return;
        
        submitReportBtn.disabled = true;
        submitReportBtn.innerHTML = `<span class="btn-spinner"></span> Ingesting...`;
        
        const zoneHint = zoneHintSelect.value || null;
        
        try {
            const resp = await fetch(`${API_BASE}/api/ingest`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: jsonStringify({
                    report_text: text,
                    zone_id_hint: zoneHint
                })
            });
            const data = await resp.json();
            if (data.success) {
                reportInputText.value = "";
                // Re-fetch state
                await fetchDashboardState();
            } else {
                alert("Agent Error: " + (data.errors ? data.errors.join("\n") : "Ingest failed"));
            }
        } catch (e) {
            console.error("Failed to ingest report:", e);
            alert("Network error: Could not contact command server.");
        } finally {
            submitReportBtn.disabled = false;
            submitReportBtn.innerText = "Ingest Incident";
        }
    });

    // Helper JSON stringify to avoid security blocks
    function jsonStringify(obj) {
        return JSON.stringify(obj);
    }

    // Reset workflow Scenario
    resetScenarioBtn.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to reset simulation and timeline logs back to standard Ward 12 Heavy Rain scenario?")) {
            return;
        }
        
        try {
            const resp = await fetch(`${API_BASE}/api/reset`, { method: "POST" });
            const data = await resp.json();
            if (data.success) {
                await fetchDashboardState();
            }
        } catch (e) {
            console.error("Scenario Reset Failed:", e);
        }
    });

    // Onboot load
    fetchDashboardState();
    
    // Poll state every 8 seconds for real-time live synchronization
    setInterval(fetchDashboardState, 8000);
});
