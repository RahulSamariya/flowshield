"""dashboard_server.py -- Runs Python HTTP backend for FlowShield dashboard.

Serves backend state and exposes ingest/reset APIs.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.parse
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# Add src parent directory to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.engine.optimizer_request import DEFAULT_CAPABILITIES, OptimizationRequest
from src.engine.priority_context import IncidentContext
from src.models import Action, Outcome, SituationState
from src.models.action import ActionStatus
from src.models.incident import IncidentStatus
from src.models.resource import ResourceStatus
from src.orchestrate.tool_contracts import IngestIncidentInput
from src.orchestrate.tools import ingest_incident
from src.workflow.scenario_ward12 import (
    CITY,
    DISTANCES,
    INCIDENT_CONTEXT,
    make_events,
    make_resources,
)
from src.workflow.workflow import FloodResponseWorkflow

# Static assets directory
STATIC_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "src", "dashboard")
)


# Helper to convert Pydantic/dataclass models to JSON-safe dictionary
def to_json_dict(obj):
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "value"):  # StrEnum / Enum
        return to_json_dict(obj.value)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        # Enforce AGENTS.md rule: overall_severity is a helper property on SituationState
        try:
            res = obj.model_dump(mode="json")
        except Exception:
            res = obj.model_dump()
        
        res = to_json_dict(res)
        
        if isinstance(obj, SituationState):
            res["overall_severity"] = str(obj.overall_severity)
            res["zones"] = {zid: to_json_dict(z) for zid, z in obj.zones.items()}
        return res
    if hasattr(obj, "__dict__"):
        res = {}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            res[k] = to_json_dict(v)
        return res
    if isinstance(obj, (list, tuple, set)):
        return [to_json_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): to_json_dict(v) for k, v in obj.items()}
    return obj


class DashboardStateManager:
    def __init__(self):
        self.reset()

    def reset(self):
        self.wf = FloodResponseWorkflow(
            scenario_name="Ward 12 Heavy Rain -- July 2025",
            city=CITY,
            events=make_events(),
            resources=make_resources(),
            incident_context=INCIDENT_CONTEXT,
            distances=DISTANCES,
            max_travel_minutes=60.0,
        )
        self.result = self.wf.run()
        self.engine = self.wf._engine

        # Record manual reports separately on the timeline
        self.timeline = []
        for i, rec in enumerate(self.result.engine_records, 1):
            self.timeline.append({
                "id": rec.id,
                "occurred_at": (
                    rec.occurred_at.isoformat()
                    if rec.occurred_at
                    else datetime.now(UTC).isoformat()
                ),
                "type": "event_ingestion",
                "title": "Scenario Event Ingested",
                "details": (
                    f"Type: {rec.raw_event_type} | Zone: {rec.zone_id} | "
                    f"Severity After: {rec.zone_severity_after or 'normal'}"
                ),
                "severity": rec.zone_severity_after or "normal"
            })

    def ingest_report(self, report_text: str, zone_id_hint: str | None = None):
        print(f"Ingesting report: '{report_text}' with hint: '{zone_id_hint}'")
        inp = IngestIncidentInput(
            city=CITY,
            report_text=report_text,
            zone_id_hint=zone_id_hint,
        )
        out = ingest_incident(inp)
        if not out.success or out.incident_id is None:
            return {
                "success": False,
                "errors": out.errors or ["Agent failed to parse citizen report."],
                "warnings": out.warnings
            }

        # Create a raw event based on confidence extraction
        from datetime import datetime

        from src.models.event import RawEvent, RawEventType

        event_type = RawEventType.WATERLOGGING
        lower_report = report_text.lower()
        if "rain" in lower_report:
            event_type = RawEventType.RAINFALL
        elif "drain" in lower_report or "clog" in lower_report:
            event_type = RawEventType.DRAIN_BLOCKED

        # Calculate a default water level from severity
        p_val = 0.5
        if out.severity == "critical":
            p_val = 2.2
        elif out.severity == "high":
            p_val = 1.4
        elif out.severity == "medium":
            p_val = 0.7

        payload = {}
        if event_type == RawEventType.RAINFALL:
            if out.severity == "critical":
                payload["rainfall_mm_hr"] = 70.0
            elif out.severity == "high":
                payload["rainfall_mm_hr"] = 40.0
            elif out.severity == "medium":
                payload["rainfall_mm_hr"] = 20.0
            else:
                payload["rainfall_mm_hr"] = 5.0
        else:
            payload["water_level_m"] = p_val
            payload["affected_people"] = 500

        evt = RawEvent(
            event_type=event_type,
            city=CITY,
            zone_id=out.zone_id or zone_id_hint or "W12-C",
            source="citizen_dashboard",
            occurred_at=datetime.now(UTC),
            payload=payload,
        )

        # Process in engine (this mutates state & creates/updates incident)
        rec = self.engine.process(evt)
        self.result.engine_records.append(rec)
        if rec.evidence_id:
            self.result.evidence_ids.append(rec.evidence_id)

        # Add to timeline
        self.timeline.append({
            "id": rec.id,
            "occurred_at": rec.occurred_at.isoformat(),
            "type": "citizen_report",
            "title": f"Citizen Incident: {out.title}",
            "details": (
                f"Report: \"{report_text}\" | Extracted Zone: {out.zone_id} | "
                f"Severity: {out.severity}"
            ),
            "severity": out.severity
        })

        # Re-run pipeline stages
        # 1. SituationState
        self.result.situation_state = self.engine.state

        # 2. Collect Open Incidents
        self.result.incidents = [
            inc for inc in self.engine.incidents.values()
            if inc.status == IncidentStatus.OPEN
        ]

        # 3. Score priorities
        contexts = []
        for inc in self.result.incidents:
            ctx_kwargs = INCIDENT_CONTEXT.get(inc.zone_id, {})
            ctx = IncidentContext(incident=inc, **ctx_kwargs)
            contexts.append(ctx)
        ranked = self.wf._priority_engine.rank(contexts)
        self.result.priority_results = ranked

        # 4. Allocate resources
        available = [
            r for r in self.engine.resources.values()
            if r.status in (ResourceStatus.AVAILABLE, ResourceStatus.STANDBY)
        ]
        self.result.resources_used = available

        incident_zones = {inc.id: inc.zone_id for inc in self.result.incidents}
        resource_zones = {
            r.id: (r.current_zone_id or r.home_zone_id)
            for r in available
        }

        request = OptimizationRequest(
            prioritized_incidents=self.result.priority_results,
            available_resources=available,
            incident_zones=incident_zones,
            resource_zones=resource_zones,
            capabilities=list(DEFAULT_CAPABILITIES),
            distances=DISTANCES,
            max_travel_minutes=60.0,
        )
        self.result.optimization_result = self.wf._optimizer.optimize(request)

        # 5. Generate Action objects
        actions = []
        for assignment in self.result.optimization_result.assignments:
            action = Action(
                id=str(uuid.uuid4()),
                incident_id=assignment.incident_id,
                resource_id=assignment.resource_id,
                decided_by="flowshield_greedy_v1",
                decision_rationale=(
                    f"Assigned by GreedyResourceOptimizer. "
                    f"Reason: {', '.join(assignment.reason_codes)}. "
                    f"Fit score: {assignment.fit_score:.3f}. "
                    f"ETA: {assignment.estimated_travel_minutes} min."
                ),
                priority=1,
                status=ActionStatus.PENDING,
            )
            actions.append(action)
        self.result.actions = actions

        # 6. Granite Reasoning
        self.result.reasoning_situation = self.wf._reasoning.summarize_situation(
            self.result.situation_state, self.result.incidents
        )
        self.result.reasoning_priorities = self.wf._reasoning.explain_priorities(
            self.result.priority_results, self.result.incidents
        )
        if self.result.optimization_result is not None:
            self.result.reasoning_assignments = self.wf._reasoning.explain_assignments(
                self.result.optimization_result, self.result.resources_used
            )
            self.result.operator_response = self.wf._reasoning.generate_response_plan(
                self.result.optimization_result,
                self.result.priority_results,
                self.result.incidents
            )

        # 7. Persist Outcomes
        outcomes = []
        inc_map = {inc.id: inc for inc in self.result.incidents}
        pr_map = {pr.incident_id: pr for pr in self.result.priority_results}

        for action in self.result.actions:
            inc = inc_map.get(action.incident_id)
            pr = pr_map.get(action.incident_id)
            severity_before = inc.severity if inc else "unknown"
            level = pr.level if pr else "unknown"
            outcome = Outcome(
                id=str(uuid.uuid4()),
                action_id=action.id,
                incident_id=action.incident_id,
                success=True,
                severity_after=severity_before,
                notes=(
                    f"Action dispatched by workflow. "
                    f"Priority level: {level}. "
                    f"Awaiting field confirmation."
                ),
                effectiveness_score=None,
            )
            outcomes.append(outcome)
        self.result.outcomes = outcomes

        return {
            "success": True,
            "incident_id": out.incident_id,
            "title": out.title,
            "severity": out.severity,
            "zone_id": out.zone_id
        }


# Global state manager instance
manager = DashboardStateManager()


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to suppress spam in backend logs
        pass

    def end_headers(self):
        # CORS Headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/state":
            # Expose dashboard state
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            payload = {
                "scenario_name": manager.result.scenario_name,
                "city": manager.result.city,
                "overall_severity": getattr(
                    manager.result.situation_state, "overall_severity", "normal"
                ),
                "incidents": to_json_dict(manager.result.incidents),
                "priority_results": to_json_dict(manager.result.priority_results),
                "resources_used": to_json_dict(manager.result.resources_used),
                "optimization_result": to_json_dict(manager.result.optimization_result),
                "actions": to_json_dict(manager.result.actions),
                "outcomes": to_json_dict(manager.result.outcomes),
                "why_panel": {
                    "reasoning_situation": to_json_dict(manager.result.reasoning_situation),
                    "reasoning_priorities": to_json_dict(manager.result.reasoning_priorities),
                    "reasoning_assignments": to_json_dict(manager.result.reasoning_assignments),
                    "operator_response": to_json_dict(manager.result.operator_response),
                },
                "timeline": manager.timeline,
                "situation_summary": to_json_dict(manager.result.situation_state),
            }

            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        # Serve static dashboard files
        if path == "/":
            file_path = os.path.join(STATIC_DIR, "index.html")
            content_type = "text/html"
        else:
            # Strip leading slash
            rel_file = path.lstrip("/")
            file_path = os.path.join(STATIC_DIR, rel_file)
            if file_path.endswith(".css"):
                content_type = "text/css"
            elif file_path.endswith(".js"):
                content_type = "application/javascript"
            elif file_path.endswith(".png"):
                content_type = "image/png"
            elif file_path.endswith(".svg"):
                content_type = "image/svg+xml"
            else:
                content_type = "text/plain"

        # Security check - restrict to STATIC_DIR
        file_path = os.path.normpath(file_path)
        if not file_path.startswith(STATIC_DIR):
            self.send_error(403, "Access Denied")
            return

        if os.path.exists(file_path) and os.path.isfile(file_path):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, f"File Not Found: {path}")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/reset":
            manager.reset()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"success": True, "message": "Simulation reset successfully"}
                ).encode("utf-8")
            )
            return

        if path == "/api/ingest":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_error(400, "Missing request body")
                return

            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except Exception:
                self.send_error(400, "Invalid JSON body")
                return

            report_text = data.get("report_text")
            zone_id_hint = data.get("zone_id_hint")

            if not report_text or not report_text.strip():
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"success": False, "errors": ["Report text is required."]}
                    ).encode("utf-8")
                )
                return

            try:
                res = manager.ingest_report(report_text, zone_id_hint)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                traceback.print_exc()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "errors": [str(e)]}).encode("utf-8"))
            return

        self.send_error(404, "Endpoint Not Found")


def run(port=8000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, DashboardHTTPHandler)
    print(f"FlowShield Dashboard Server started at http://localhost:{port}/")
    print(f"Serving static assets from: {STATIC_DIR}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    port_val = 8000
    if len(sys.argv) > 1:
        try:
            port_val = int(sys.argv[1])
        except ValueError:
            pass
    run(port=port_val)
