"""FlowShield built-in knowledge corpus.

Contains all policy/SOP/guidance chunks for the FlowShield knowledge base.
FLOWSHIELD_KB is a pre-built KnowledgeBase instance ready to inject into agents.

Document categories
-------------------
SOP              — Standard operating procedures per incident type
DRAINAGE         — Drainage infrastructure and dewatering guidance
ESCALATION       — Rules for escalating to higher authority or mutual aid
APPROVAL_POLICY  — Human approval requirements and sign-off thresholds
COMMUNICATION    — Public/inter-agency communication guidance
SAFETY           — Responder safety and no-go conditions

Authoring rules (MUST follow when editing this file)
-----------------------------------------------------
- DO NOT include any live numeric sensor values or resource counts.
- DO NOT name specific individuals; use role titles only.
- Write each chunk so it stands alone without other chunks for context.
- Keep source_ref consistent with the document name / section number.
- Tags must be lowercase single words or short phrases.
"""

from __future__ import annotations

from src.knowledge.knowledge_base import KnowledgeBase
from src.knowledge.knowledge_chunk import KnowledgeCategory, KnowledgeChunk

# ── SOP: Waterlogging Response ─────────────────────────────────────────────────

_SOP_WATERLOGGING = KnowledgeChunk(
    id="sop-waterlogging-response",
    category=KnowledgeCategory.SOP,
    title="Waterlogging First Response SOP",
    text=(
        "Upon detection of waterlogging in any urban zone, the Ward Control Room "
        "must be notified within 5 minutes. The duty engineer must visually confirm "
        "water levels before dispatching dewatering equipment. "
        "Pump units must be deployed to the highest-severity zone first. "
        "If water depth exceeds 0.5 m on a primary road, barricades must be placed "
        "and traffic diverted before dewatering begins. "
        "Dewatering operations must continue until road surface is clear and water "
        "depth falls below 0.1 m. "
        "All dewatering actions must be logged in the AMC Flood Management Portal "
        "within 30 minutes of completion. "
        "Where multiple zones are affected simultaneously, prioritise zones with "
        "critical facilities (hospitals, fire stations, schools) regardless of "
        "absolute water depth."
    ),
    tags=(
        "waterlogging", "dewatering", "pump", "flood", "first response",
        "ward control room", "water depth", "primary road",
    ),
    source_ref="AMC Flood SOP 2023, Sec 3.1 — Waterlogging First Response",
)

_SOP_FLASH_FLOOD = KnowledgeChunk(
    id="sop-flash-flood-response",
    category=KnowledgeCategory.SOP,
    title="Flash Flood Emergency Response SOP",
    text=(
        "A flash flood declaration requires immediate activation of the City EOC. "
        "All rescue teams must be placed on standby within 10 minutes of declaration. "
        "NDRF/SDRF must be notified when water depth exceeds 1.5 m in any ward or "
        "when more than 500 people are displaced. "
        "Road closures must be enforced on all roads with water depth above 0.6 m. "
        "Evacuation of ground-floor residents in affected zones must begin within "
        "30 minutes if water rise rate exceeds 0.2 m/hour. "
        "Helicopter requisition requires written authorisation from the District "
        "Collector. Medical teams must be pre-positioned at designated relief camps "
        "before evacuation begins. "
        "No rescue operation may proceed if current velocity exceeds 1.5 m/s — "
        "wait for velocity to drop below 1.0 m/s before deploying personnel."
    ),
    tags=(
        "flash flood", "emergency", "evacuation", "NDRF", "SDRF", "EOC",
        "rescue", "water depth", "road closure", "relief camp", "helicopter",
    ),
    source_ref="AMC Flood SOP 2023, Sec 4.1 — Flash Flood Emergency Response",
)

_SOP_DRAIN_BLOCKED = KnowledgeChunk(
    id="sop-drain-blockage-response",
    category=KnowledgeCategory.SOP,
    title="Blocked Drain Emergency Clearance SOP",
    text=(
        "When a storm drain blockage is reported or detected, the Drainage Maintenance "
        "Unit must acknowledge within 15 minutes and deploy a clearance crew within "
        "45 minutes during rain events. "
        "Drain clearance crews must not enter confined drain chambers during active "
        "rainfall exceeding 35 mm/hr — use remote jetting equipment only. "
        "If blockage is causing road flooding above 0.3 m, the road must be barricaded "
        "and the incident escalated to the Duty Engineer. "
        "Clearance attempts must be recorded in the SCADA maintenance log. "
        "If the blockage cannot be cleared within 2 hours, a mobile pump unit must "
        "be deployed to manage water accumulation while clearance continues. "
        "Post-clearance inspection must be conducted to confirm drainage is restored."
    ),
    tags=(
        "drain", "blockage", "clearance", "jetting", "SCADA", "maintenance",
        "drainage unit", "confined space", "rainfall threshold",
    ),
    source_ref="AMC Drainage SOP 2022, Sec 2.3 — Blocked Drain Emergency Clearance",
)

_SOP_ROAD_CLOSURE = KnowledgeChunk(
    id="sop-road-closure",
    category=KnowledgeCategory.SOP,
    title="Flood-Related Road Closure and Diversion SOP",
    text=(
        "Roads must be closed to traffic when water depth exceeds 0.3 m on minor roads "
        "or 0.5 m on primary arterial roads. "
        "Barricades must be placed at both ends of the flooded section with visible "
        "fluorescent markers and hazard lighting active after dark. "
        "The Traffic Control Cell must be notified immediately so diversions can be "
        "activated on the city traffic management system. "
        "Police assistance is required for closures on state highways — contact the "
        "nearest police station and the District Traffic Police. "
        "Road reopening requires sign-off from the duty engineer after confirming "
        "water depth is below 0.1 m and road surface is structurally safe."
    ),
    tags=(
        "road closure", "barricade", "diversion", "traffic", "flood", "depth threshold",
        "arterial road", "police", "reopening",
    ),
    source_ref="AMC Traffic SOP 2023, Sec 1.4 — Flood Road Closure Procedure",
)

_SOP_RESCUE = KnowledgeChunk(
    id="sop-rescue-team-deployment",
    category=KnowledgeCategory.SOP,
    title="Rescue Team Deployment and Safety SOP",
    text=(
        "Rescue teams must not enter water above knee height (approximately 0.45 m) "
        "without approved personal flotation devices and life-lines. "
        "Swift-water rescue operations require minimum 2-person teams; solo entry "
        "is prohibited regardless of experience level. "
        "Teams must check-in with the EOC every 15 minutes during active deployment. "
        "Thermal imaging must be used for night operations when visibility is below "
        "50 metres. "
        "Rescue boats may be launched only when water depth exceeds 0.8 m and current "
        "velocity is below 1.5 m/s. "
        "Medical screening of rescued persons must occur within 30 minutes of extraction. "
        "All rescue operations require real-time incident commander oversight — "
        "no autonomous team action is permitted."
    ),
    tags=(
        "rescue", "rescue team", "swift water", "life line", "flotation",
        "boat", "night operation", "EOC check-in", "incident commander",
    ),
    source_ref="SDRF Rescue SOP 2023, Sec 5.2 — Urban Flood Rescue Deployment",
)

# ── DRAINAGE: Maintenance & Infrastructure Guidance ───────────────────────────

_DRAIN_MAINTENANCE = KnowledgeChunk(
    id="drainage-maintenance-guidance",
    category=KnowledgeCategory.DRAINAGE,
    title="Urban Drainage Maintenance and Pre-Monsoon Preparation",
    text=(
        "All major storm drains must be inspected and de-silted before the onset of "
        "the monsoon season (target: before June 1 each year). "
        "Inspection records must be uploaded to the GIS-linked drainage asset database "
        "within 48 hours of inspection. "
        "Drains classified as high-risk (capacity utilisation above 80% in a 10-year "
        "design storm) must be cleared twice — once pre-monsoon and once mid-monsoon. "
        "Vegetation growing within 1 metre of drain openings must be cleared to prevent "
        "monsoon-season blockage. "
        "Pump stations must undergo functional testing including wet-run tests before "
        "June 15 each year. Any pump with reduced capacity below 70% of rated output "
        "must be flagged for urgent repair before monsoon onset."
    ),
    tags=(
        "maintenance", "de-silting", "pre-monsoon", "inspection", "pump station",
        "drainage", "capacity", "monsoon", "asset database",
    ),
    source_ref="AMC Drainage Maintenance Manual 2022, Sec 1.1 — Pre-Monsoon Schedule",
)

_DRAIN_DEWATERING_CAPACITY = KnowledgeChunk(
    id="drainage-dewatering-capacity",
    category=KnowledgeCategory.DRAINAGE,
    title="Dewatering Pump Capacity and Zone Coverage Guidelines",
    text=(
        "Each dewatering pump zone assignment must be based on the hydraulic catchment "
        "area and not administrative ward boundaries. "
        "A single pump unit rated below 5,000 L/hr must not be assigned to a zone "
        "with more than 2 hectares of inundated area. "
        "Multiple pump units may be deployed in the same zone; the second unit must be "
        "positioned at the downslope end of the zone to optimise drainage flow. "
        "When rainfall rate exceeds 64 mm/hr, all available dewatering pumps in the "
        "affected sub-division should be pre-positioned at designated standby points "
        "before field deployment. "
        "Pump units must not be operated in water carrying floating debris without "
        "a protective debris screen — debris ingestion causes mechanical failure."
    ),
    tags=(
        "pump", "dewatering", "capacity", "zone", "hydraulic", "rainfall",
        "standby", "deployment", "debris screen",
    ),
    source_ref="AMC Drainage Manual 2022, Sec 3.4 — Dewatering Pump Operations",
)

_DRAIN_SURAT = KnowledgeChunk(
    id="drainage-surat-specifics",
    category=KnowledgeCategory.DRAINAGE,
    title="Surat Drainage Network — Tapi River Backflow Guidance",
    text=(
        "When Tapi River gauge at Sardar Bridge exceeds 15 metres above datum, "
        "gravity drainage from the low-lying wards on the west bank becomes ineffective "
        "due to backflow pressure. In this condition, all dewatering must rely entirely "
        "on mechanical pumping. "
        "The Athwalines and Nanpura wards are most exposed to backflow-induced "
        "waterlogging. Pump pre-positioning in these zones must begin when the "
        "Tapi level reaches 13 metres. "
        "Inter-agency coordination with the Surat Irrigation Department is mandatory "
        "before activating any sluice gate on the main drainage canal."
    ),
    tags=(
        "Surat", "Tapi", "river", "backflow", "gravity drainage", "sluice gate",
        "Athwalines", "Nanpura", "west bank", "irrigation department",
    ),
    source_ref="SMC Flood Management Plan 2023, Sec 6.2 — Tapi Backflow Conditions",
)

# ── ESCALATION: Rules and Thresholds ──────────────────────────────────────────

_ESC_SEVERITY_TRIGGERS = KnowledgeChunk(
    id="escalation-severity-triggers",
    category=KnowledgeCategory.ESCALATION,
    title="Severity-Based Escalation Trigger Rules",
    text=(
        "CRITICAL severity in any ward triggers automatic escalation to the "
        "City Emergency Operations Centre (EOC). The EOC must be activated within "
        "15 minutes of a CRITICAL classification. "
        "WARNING severity affecting three or more wards simultaneously triggers "
        "District Collector notification. "
        "When the overall situation severity is CRITICAL, the State Disaster Management "
        "Authority (SDMA) must be notified within 30 minutes. "
        "No de-escalation from CRITICAL to WARNING may occur without concurrence "
        "from the Duty Commissioner or designated deputy. "
        "All escalation events must be recorded in the EOC incident log with "
        "timestamp, severity at time of escalation, and name of officer notified."
    ),
    tags=(
        "escalation", "severity", "CRITICAL", "EOC", "district collector",
        "SDMA", "deescalation", "incident log", "commissioner",
    ),
    source_ref="Gujarat DDMP 2023, Sec 8.1 — Urban Flood Escalation Triggers",
)

_ESC_RESOURCE_GAP = KnowledgeChunk(
    id="escalation-resource-gap",
    category=KnowledgeCategory.ESCALATION,
    title="Resource Gap Escalation and Mutual Aid Protocol",
    text=(
        "When the local resource pool cannot cover one or more CRITICAL or HIGH "
        "severity incidents, the EOC Duty Officer must immediately request mutual aid "
        "from neighbouring municipalities. "
        "Mutual aid requests must specify: incident location, required resource type, "
        "required quantity, and estimated deployment window. "
        "NDRF teams may be requested when local rescue capacity is exhausted and "
        "more than 200 people require evacuation. "
        "State Emergency Operations Centre (SEOC) must be looped in on all "
        "mutual aid requests within 1 hour of the request being raised. "
        "If a resource gap persists for more than 2 hours on a CRITICAL incident, "
        "the District Magistrate must be personally briefed."
    ),
    tags=(
        "resource gap", "mutual aid", "NDRF", "EOC", "escalation",
        "evacuation", "SEOC", "district magistrate", "neighbouring municipality",
    ),
    source_ref="Gujarat DDMP 2023, Sec 8.3 — Resource Gap Escalation and Mutual Aid",
)

_ESC_MEDIA = KnowledgeChunk(
    id="escalation-media-communication",
    category=KnowledgeCategory.ESCALATION,
    title="Media and Public Communication Escalation Rules",
    text=(
        "Public advisories must be issued within 1 hour of a CRITICAL flood "
        "classification via SMS alert, local cable TV, and the city's official "
        "social media channels. "
        "Media briefings are the responsibility of the Public Relations Officer (PRO) "
        "designated by the Commissioner. Field officers must not make independent "
        "media statements without PRO clearance. "
        "During active CRITICAL incidents, a media briefing must be held at minimum "
        "every 4 hours. "
        "All public advisories must include: affected zones, recommended actions for "
        "residents, emergency contact numbers, and expected resolution timeline."
    ),
    tags=(
        "media", "public advisory", "communication", "SMS", "social media",
        "PRO", "commissioner", "briefing", "CRITICAL",
    ),
    source_ref="AMC Communications Protocol 2023, Sec 2.1 — Flood Emergency Media Rules",
)

# ── APPROVAL_POLICY: Human Sign-off Requirements ──────────────────────────────

_APPROVAL_HIGH_RISK = KnowledgeChunk(
    id="approval-high-risk-operations",
    category=KnowledgeCategory.APPROVAL_POLICY,
    title="Human Approval Requirements for High-Risk Operations",
    text=(
        "The following operations require explicit written approval from the "
        "Duty Commissioner before execution: "
        "(1) Deployment of NDRF/SDRF rescue teams into active swift-water conditions. "
        "(2) Forced evacuation of residents from any ward. "
        "(3) Closure of any national highway or state highway. "
        "(4) Activation of the City Emergency Operations Centre beyond Level 1. "
        "(5) Requisitioning of private vehicles, equipment, or buildings under "
        "the Disaster Management Act. "
        "Approval may be given verbally in life-threatening situations, but must be "
        "followed by written confirmation within 2 hours."
    ),
    tags=(
        "approval", "sign-off", "commissioner", "NDRF", "evacuation",
        "highway closure", "EOC activation", "disaster management act",
        "written authorisation", "high risk",
    ),
    source_ref="Gujarat DDMP 2023, Sec 9.1 — Approval Requirements for High-Risk Operations",
)

_APPROVAL_RESOURCE_COMMITMENT = KnowledgeChunk(
    id="approval-resource-commitment",
    category=KnowledgeCategory.APPROVAL_POLICY,
    title="Resource Commitment Approval Thresholds",
    text=(
        "Single resource deployments for MEDIUM or LOW severity incidents may be "
        "approved by the Duty Engineer without further escalation. "
        "Deployment of three or more resources to a single incident requires "
        "approval from the Ward Incident Commander. "
        "Cross-ward resource reallocation (moving a resource from its assigned ward) "
        "requires approval from the Area Flood Coordinator. "
        "Any resource commitment exceeding 8 hours of continuous deployment "
        "requires review and re-authorisation by the Duty Commissioner. "
        "Resources committed under mutual aid agreements may not be re-tasked "
        "within the city without the originating municipality's consent."
    ),
    tags=(
        "approval", "resource commitment", "duty engineer", "ward", "incident commander",
        "area coordinator", "mutual aid", "deployment hours", "reallocation",
    ),
    source_ref="AMC Resource Management Policy 2023, Sec 4.2 — Deployment Approval Thresholds",
)

_APPROVAL_CRITICAL_INCIDENTS = KnowledgeChunk(
    id="approval-critical-incident-actions",
    category=KnowledgeCategory.APPROVAL_POLICY,
    title="Approval Requirements for Critical-Severity Incident Actions",
    text=(
        "All proposed response actions for CRITICAL severity incidents must be "
        "reviewed by the EOC Duty Officer before execution. "
        "Auto-dispatch of resources to CRITICAL incidents is prohibited — a human "
        "operator must confirm each assignment. "
        "If the EOC Duty Officer is unavailable, authority passes to the senior-most "
        "available officer in the EOC, who must document the assumption of authority "
        "in the incident log. "
        "Response plan changes during an active CRITICAL incident must be agreed by "
        "at least two EOC officers and logged with rationale. "
        "The time between plan approval and first resource deployment must not exceed "
        "10 minutes for CRITICAL incidents."
    ),
    tags=(
        "approval", "critical", "EOC duty officer", "auto dispatch",
        "incident log", "response plan", "deployment time",
    ),
    source_ref="Gujarat DDMP 2023, Sec 9.2 — Critical Incident Action Approval Rules",
)

_APPROVAL_AI_DECISIONS = KnowledgeChunk(
    id="approval-ai-generated-decisions",
    category=KnowledgeCategory.APPROVAL_POLICY,
    title="Human Oversight Policy for AI-Generated Response Recommendations",
    text=(
        "AI-generated response plans and resource assignments are advisory only. "
        "No AI recommendation may be executed without review and confirmation by "
        "a qualified human operator. "
        "The EOC Duty Officer is responsible for reviewing all AI-generated plans "
        "before they are acted upon. "
        "AI recommendations for CRITICAL severity incidents must always be confirmed "
        "at supervisor level (EOC Section Chief or above). "
        "Where an AI recommendation contradicts standing SOP, the SOP prevails "
        "and the contradiction must be documented in the incident log. "
        "AI recommendations must be labelled as 'AI-generated' in all operator "
        "displays and printed logs to ensure traceability."
    ),
    tags=(
        "AI", "human oversight", "advisory", "approval", "EOC duty officer",
        "SOP compliance", "AI-generated", "traceability", "CRITICAL", "supervisor",
    ),
    source_ref="Gujarat DDMP 2023, Sec 9.4 — AI Decision Support Oversight Policy",
)

# ── SAFETY: Responder Safety Rules ────────────────────────────────────────────

_SAFETY_NO_GO = KnowledgeChunk(
    id="safety-no-go-conditions",
    category=KnowledgeCategory.SAFETY,
    title="Flood Responder No-Go Safety Conditions",
    text=(
        "Responders must not enter any of the following conditions without "
        "specialist equipment and explicit incident commander authorisation: "
        "(1) Water current velocity above 1.5 m/s. "
        "(2) Water depth exceeding 1.2 m for personnel on foot. "
        "(3) Visibility below 20 metres without thermal imaging equipment. "
        "(4) Active lightning within 8 km of the operational area. "
        "(5) Structural flood damage visible to adjacent buildings. "
        "In no-go conditions, life-safety of responders takes precedence over "
        "property protection. Operations must be suspended and EOC notified "
        "immediately. Resumption requires incident commander sign-off after "
        "conditions improve."
    ),
    tags=(
        "safety", "no go", "current velocity", "water depth", "lightning",
        "structural damage", "responder", "incident commander", "visibility",
    ),
    source_ref="SDRF Safety Manual 2023, Sec 3.1 — No-Go Conditions for Urban Flood Response",
)

_SAFETY_PPE = KnowledgeChunk(
    id="safety-ppe-requirements",
    category=KnowledgeCategory.SAFETY,
    title="Personal Protective Equipment (PPE) Requirements for Flood Response",
    text=(
        "All personnel entering flood-affected zones must wear at minimum: "
        "rubber boots (minimum knee-height), high-visibility reflective vest, "
        "hard hat, and nitrile gloves. "
        "Swift-water rescue personnel must additionally wear: "
        "approved personal flotation device (PFD) rated for moving water, "
        "dry suit or wetsuit appropriate for water temperature, "
        "rescue helmet with face shield, and attached knife and whistle. "
        "PPE inspection must be completed before each shift deployment. "
        "Personnel with damaged or non-compliant PPE must not enter flood zones — "
        "they must be reassigned to dry operations until replacement PPE is issued."
    ),
    tags=(
        "PPE", "personal protective equipment", "flotation device", "PFD",
        "rescue helmet", "boots", "wetsuit", "safety", "inspection",
    ),
    source_ref="SDRF Safety Manual 2023, Sec 2.1 — PPE Requirements",
)

# ── COMMUNICATION: Inter-Agency Coordination ──────────────────────────────────

_COMMS_EOC = KnowledgeChunk(
    id="communication-eoc-protocol",
    category=KnowledgeCategory.COMMUNICATION,
    title="EOC Communication and Reporting Protocol",
    text=(
        "All field units must report status to the EOC at the following intervals: "
        "every 15 minutes during active deployment, every 30 minutes during standby. "
        "Status reports must include: current location, operational status, "
        "resource availability, and any safety concerns. "
        "The EOC Situation Report (SITREP) must be compiled every hour during "
        "CRITICAL incidents and every 2 hours during WARNING-level incidents. "
        "SITREP distribution includes: Municipal Commissioner, District Collector, "
        "State EOC Liaison, and the Mayor's office. "
        "All radio communications must use plain language — no codes except "
        "those in the approved ICS radio code list."
    ),
    tags=(
        "EOC", "SITREP", "reporting", "communication", "field unit",
        "municipal commissioner", "district collector", "radio", "ICS",
    ),
    source_ref="AMC Emergency Communication Protocol 2023, Sec 5.1 — EOC Reporting",
)

_COMMS_PUBLIC = KnowledgeChunk(
    id="communication-public-guidance",
    category=KnowledgeCategory.COMMUNICATION,
    title="Public Guidance Messaging for Flood Events",
    text=(
        "Public guidance messages during flood events must advise: "
        "stay indoors and move to upper floors if ground floor is flooded; "
        "do not attempt to cross flooded roads on foot or by vehicle; "
        "keep mobile phones charged and monitor official advisory channels; "
        "evacuate only when instructed by official loudspeaker or officer; "
        "avoid contact with floodwater which may be contaminated. "
        "Messages must be broadcast in Gujarati, Hindi, and English. "
        "Helpline numbers: AMC Flood Control Room (relevant number as published), "
        "NDRF toll-free, and EMRI 108 for medical emergencies. "
        "Social media posts must be approved by the PRO before publication and "
        "must not contain unverified information about road status or casualties."
    ),
    tags=(
        "public", "guidance", "flood", "advisory", "evacuation", "Gujarati",
        "helpline", "social media", "contamination", "road status",
    ),
    source_ref="AMC Communications Protocol 2023, Sec 3.2 — Public Flood Guidance",
)

# ── Master corpus ──────────────────────────────────────────────────────────────

_ALL_CHUNKS: list[KnowledgeChunk] = [
    # SOPs
    _SOP_WATERLOGGING,
    _SOP_FLASH_FLOOD,
    _SOP_DRAIN_BLOCKED,
    _SOP_ROAD_CLOSURE,
    _SOP_RESCUE,
    # Drainage
    _DRAIN_MAINTENANCE,
    _DRAIN_DEWATERING_CAPACITY,
    _DRAIN_SURAT,
    # Escalation
    _ESC_SEVERITY_TRIGGERS,
    _ESC_RESOURCE_GAP,
    _ESC_MEDIA,
    # Approval policy
    _APPROVAL_HIGH_RISK,
    _APPROVAL_RESOURCE_COMMITMENT,
    _APPROVAL_CRITICAL_INCIDENTS,
    _APPROVAL_AI_DECISIONS,
    # Safety
    _SAFETY_NO_GO,
    _SAFETY_PPE,
    # Communication
    _COMMS_EOC,
    _COMMS_PUBLIC,
]

#: Pre-built knowledge base — inject into ResponsePlanningAgent or GraniteReasoningLayer.
FLOWSHIELD_KB: KnowledgeBase = KnowledgeBase(chunks=_ALL_CHUNKS)
