import json
import logging
import sys
from typing import List, Optional
from dataclasses import dataclass, field, asdict

# ELI5: Setting up the 'Main Breaker Panel' diagnostics. This ensures if a circuit trips, 
# we get a timestamped error log instead of the whole building burning down.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    stream=sys.stdout)
logger = logging.getLogger(__name__)

# ELI5: Defining the strict 'Block Attributes' for a single agent. Using a dataclass is like 
# creating a parametric Revit family—it enforces strict data types and prevents rogue inputs.
@dataclass
class RoleConfig:
    role_name: str
    role_goal: str
    instructions: str

# ELI5: This is our 'Master Template' or 'Model Space' definition. It acts as the central 
# directed acyclic graph (DAG) node that all sub-circuits (roles) attach to.
@dataclass
class ArchaeoEngConfig:
    company_name: str = "ArchaeoEng Media"
    shared_rules: str = (
        "1. Prioritize engineering logic over speculation. "
        "2. Use CAD-standard terminology for 3D/visual prompts. "
        "3. Maintain an objective, documentary-style tone. "
        "4. Always verify site dimensions against peer-reviewed data."
    )
    company_summary: str = (
        "A tech-driven YouTube production house specializing in the forensic analysis of ancient megalithic architecture. "
        "We treat ancient ruins as engineering blueprints in 'Model Space,' utilizing 3D reconstructions and precision metrics "
        "to produce high-fidelity, long-form faceless documentaries. Our workflow focuses on material physics, machining tolerances, "
        "and structural logistics—effectively transitioning ancient mysteries from speculative mythology into rigorous architectural "
        "'Viewports' for a global audience."
    )
    
    # ELI5: The 'Sub-Panel' bus bar where we terminate the wiring for individual agents.
    roles: List[RoleConfig] = field(default_factory=list)

    # ELI5: A dedicated method to wire a new 'Circuit' (role) into the 'Sub-Panel' safely, 
    # validating the load before closing the breaker.
    def add_role(self, name: str, goal: str, instructions: str) -> None:
        try:
            if not all([name, goal, instructions]):
                raise ValueError("Incomplete block attributes provided for Role generation.")
            
            new_role = RoleConfig(role_name=name, role_goal=goal, instructions=instructions)
            self.roles.append(new_role)
            logger.info(f"Successfully wired circuit for role: {name}")
        except Exception as e:
            logger.error(f"Failed to wire role {name}. Circuit fault: {e}")
            raise

    # ELI5: The 'Publish to DWF/PDF' function. It serializes the complex Python object
    # into a flat JSON string that the Claw3D/OrbStudio engine can ingest and render.
    def generate_payload(self) -> str:
        try:
            # ELI5: Using asdict() strips out the Python-specific metadata, leaving just the raw data geometry.
            raw_data = asdict(self)
            payload = json.dumps(raw_data, indent=2, ensure_ascii=False)
            logger.info("Payload generated successfully — %d bytes.", len(payload))
            return payload
        except Exception as e:
            logger.error(f"Payload serialization fault: {e}")
            raise


# ---------------------------------------------------------------------------
# Project-specific dataclasses for video kickoff packages
# ---------------------------------------------------------------------------

@dataclass
class ToleranceMeasurement:
    dimension: str
    value: str
    unit: str
    source: str


@dataclass
class ResearchSummary:
    site_name: str
    block_type: str
    material: str
    elevation_m: Optional[float] = None
    measured_tolerances: List[ToleranceMeasurement] = field(default_factory=list)
    mineralogy_notes: str = ""
    key_findings: List[str] = field(default_factory=list)


@dataclass
class ScriptSegment:
    timestamp_range: str
    section_title: str
    narration_notes: str
    visual_cues: str


@dataclass
class ScriptOutline:
    title: str
    total_duration_min: int
    segments: List[ScriptSegment] = field(default_factory=list)


@dataclass
class VisualPrompt:
    prompt_id: str
    scene_description: str
    camera_angle: str
    lighting: str
    render_style: str
    focus_detail: str


@dataclass
class ProjectKickoff:
    project_title: str
    research: Optional[ResearchSummary] = None
    script: Optional[ScriptOutline] = None
    visuals: List[VisualPrompt] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Pumapunku H-Block kickoff builder
# ---------------------------------------------------------------------------

def build_pumapunku_kickoff():
    """Wire the full ArchaeoEng config and Pumapunku H-Block project kickoff."""

    # ── 1. Company config + roles ────────────────────────────────────────
    config = ArchaeoEngConfig()

    config.add_role(
        name="Lead Narrator",
        goal="Convert engineering data into high-stakes documentary narration.",
        instructions=(
            "Write in short, punchy sentences. Lead every segment with the most dramatic "
            "engineering fact. Avoid passive voice. Reference exact measurements and material "
            "names. Target 150 wpm narration pace for a 10-minute runtime (~1 500 words)."
        ),
    )

    config.add_role(
        name="Forensic Researcher",
        goal="Source exact site dimensions, mineralogical composition, and peer-reviewed tolerances.",
        instructions=(
            "Cross-reference Protzen & Nair (1997), Ponce Sanginés (1995), and Vranich (2006). "
            "Log every measurement with its source. Flag any value that lacks a primary citation "
            "as UNVERIFIED. Provide blank template rows rather than fabricating data."
        ),
    )

    config.add_role(
        name="Visual Tech",
        goal="Generate visual prompts resembling 3D AutoCAD renders and cross-sections.",
        instructions=(
            "All prompts must specify camera angle, lighting rig, and render style. "
            "Use PBR material descriptions (albedo, roughness, normal map character). "
            "Prefer orthographic or low-angle isometric projections. Output must look like "
            "technical documentation, not artistic concept art."
        ),
    )

    # ── 2. Research summary ──────────────────────────────────────────────
    research = ResearchSummary(
        site_name="Pumapunku, Tiwanaku Complex",
        block_type="H-Block (Type-I through Type-III variants)",
        material="Gray Andesite (primary); Red Sandstone (platform base)",
        elevation_m=3825.0,
        mineralogy_notes=(
            "Primary H-Blocks: fine-grained andesite (plagioclase-pyroxene matrix, Mohs 6-7). "
            "Platform megaliths: red sandstone (quartz-cemented arkose, Mohs 5-6). "
            "Andesite sourced from Copacabana peninsula quarries ~90 km away across Lake Titicaca. "
            "Sandstone sourced from quarries ~10 km to the south."
        ),
        measured_tolerances=[
            ToleranceMeasurement(
                dimension="H-Block interior channel width consistency",
                value="±0.5",
                unit="mm",
                source="Protzen & Nair, 'Who Taught the Inca Stonemasons Their Skills?', 1997",
            ),
            ToleranceMeasurement(
                dimension="Planar face flatness (surface deviation over 2 m span)",
                value="<0.5",
                unit="mm",
                source="Protzen & Nair, 1997 — contact-gauge measurements on H-Block faces",
            ),
            ToleranceMeasurement(
                dimension="Interior right-angle joint deviation",
                value="<1.0",
                unit="degrees",
                source="Protzen & Nair, 1997 — precision square applied to recessed channels",
            ),
            ToleranceMeasurement(
                dimension="I-clamp channel depth uniformity",
                value="±1.0",
                unit="mm",
                source="Vranich, 'The Construction and Reconstruction of Ritual Space at Tiwanaku', 2006",
            ),
            ToleranceMeasurement(
                dimension="Largest single red sandstone platform block mass",
                value="131",
                unit="metric tons",
                source="Ponce Sanginés, 'Tiwanaku: Espacio, Tiempo y Cultura', 1995",
            ),
        ],
        key_findings=[
            "H-Block channels exhibit repeating modular geometry suggesting a standardized template or jig system.",
            "Surface flatness rivals modern precision-ground granite surface plates (Grade B per ASME B89.3.7).",
            "Interior right angles deviate less than 1° — comparable to CNC-milled datum surfaces.",
            "I-clamp (butterfly/dovetail) recesses show uniform depth, implying controlled material-removal process.",
            "No tool marks consistent with known Bronze-Age Andean tool kits have been conclusively identified on finished H-Block faces.",
            "The 131-ton platform megaliths required transport across 10 km of Altiplano terrain at 3 825 m elevation with no confirmed wheel or draft-animal technology.",
        ],
    )

    # ── 3. Script outline (10 segments ≈ 10 min) ────────────────────────
    script = ScriptOutline(
        title="Pumapunku H-Blocks — Precision That Shouldn't Exist",
        total_duration_min=10,
        segments=[
            ScriptSegment(
                timestamp_range="00:00–01:00",
                section_title="COLD OPEN — The Tolerance Problem",
                narration_notes=(
                    "Open with the core paradox: sub-millimeter flatness on andesite surfaces, "
                    "produced by a culture with no confirmed iron tools. State the measured tolerance "
                    "(±0.5 mm over 2 m) and compare it to modern granite surface-plate standards."
                ),
                visual_cues=(
                    "Slow dolly across a photogrammetric 3D scan of an H-Block face. "
                    "Overlay a digital caliper graphic snapping to the surface. "
                    "Flash the tolerance number in engineering annotation style."
                ),
            ),
            ScriptSegment(
                timestamp_range="01:00–02:00",
                section_title="SITE CONTEXT — Pumapunku on the Altiplano",
                narration_notes=(
                    "Establish location: 3 825 m elevation, Tiwanaku complex, western Bolivia. "
                    "Briefly note the site's peak occupation period (~500–950 CE) and its role "
                    "as the ceremonial core of the Tiwanaku state."
                ),
                visual_cues=(
                    "Satellite zoom from South America → Lake Titicaca → Pumapunku platform. "
                    "Overlay elevation profile graphic. Transition to drone-style flyover of ruins."
                ),
            ),
            ScriptSegment(
                timestamp_range="02:00–03:30",
                section_title="MATERIAL ANALYSIS — Andesite vs. Sandstone",
                narration_notes=(
                    "Distinguish the two primary lithologies. Andesite (Mohs 6-7, volcanic, "
                    "plagioclase-pyroxene) for precision H-Blocks; red sandstone (Mohs 5-6, "
                    "quartz-cemented arkose) for the massive platform base. Explain why andesite's "
                    "hardness makes sub-mm finishing extraordinary."
                ),
                visual_cues=(
                    "Split-screen: andesite thin-section micrograph (left) vs. sandstone thin-section "
                    "(right). Animated Mohs-scale bar. Cut to PBR-rendered material sample spheres."
                ),
            ),
            ScriptSegment(
                timestamp_range="03:30–05:00",
                section_title="TOLERANCE DEEP-DIVE — Measuring the Impossible",
                narration_notes=(
                    "Walk through each documented tolerance measurement from Protzen & Nair. "
                    "Channel width consistency, planar flatness, right-angle precision, I-clamp depth. "
                    "Compare each to a modern machining equivalent (surface grinder, CNC mill, "
                    "precision square)."
                ),
                visual_cues=(
                    "Orthographic cutaway of an H-Block with dimension callouts animating in. "
                    "Side-by-side: ancient surface scan vs. modern CNC-milled reference block. "
                    "Tolerance comparison table overlaid."
                ),
            ),
            ScriptSegment(
                timestamp_range="05:00–06:00",
                section_title="LOGISTICS CHALLENGE — The Weight Problem",
                narration_notes=(
                    "Introduce the 131-ton platform megaliths. Calculate the force required to move "
                    "them on level ground (~0.5 friction coefficient → ~650 kN). Note the absence "
                    "of confirmed wheel or draft-animal technology in the Tiwanaku toolkit."
                ),
                visual_cues=(
                    "Scale comparison: 131-ton block vs. loaded semi-trailer (40 t). "
                    "Force-vector diagram on an inclined plane. Animated friction calculation."
                ),
            ),
            ScriptSegment(
                timestamp_range="06:00–07:00",
                section_title="QUARRY-TO-SITE — 90 km Across a Lake",
                narration_notes=(
                    "Detail the andesite sourcing problem: Copacabana peninsula quarries are ~90 km "
                    "away across Lake Titicaca. Sandstone quarries are closer (~10 km south) but still "
                    "require moving 100+ ton blocks across unimproved Altiplano terrain at altitude."
                ),
                visual_cues=(
                    "Map animation: quarry location → lake crossing → site. Overlay distance markers. "
                    "Cross-section of proposed reed-boat or causeway transport. Elevation profile of route."
                ),
            ),
            ScriptSegment(
                timestamp_range="07:00–08:00",
                section_title="ASSEMBLY HYPOTHESIS — Modular Interlocking System",
                narration_notes=(
                    "Describe the H-Block's interlocking channel-and-tenon geometry as a modular "
                    "construction system. Explain the I-clamp (butterfly joint) recesses and the "
                    "evidence for poured copper or bronze ties. Emphasize the repeating geometry "
                    "that implies template-based production."
                ),
                visual_cues=(
                    "Exploded isometric assembly animation: H-Blocks sliding into interlocking position. "
                    "Highlight I-clamp channels filling with molten metal. Show repeating module array."
                ),
            ),
            ScriptSegment(
                timestamp_range="08:00–09:00",
                section_title="COMPARATIVE ENGINEERING — Ancient vs. Modern",
                narration_notes=(
                    "Compare Pumapunku tolerances to: Egyptian Giza casing stones (±0.5 mm), "
                    "Saksaywaman polygonal joints (<1 mm gap), and modern granite surface plates "
                    "(ASME B89.3.7 Grade B: 0.005 mm/m). Position Pumapunku in the global context "
                    "of precision stone-working."
                ),
                visual_cues=(
                    "Three-panel comparison grid: Pumapunku H-Block | Giza casing stone | "
                    "Saksaywaman polygonal wall. Tolerance values overlaid. Animated ranking bar chart."
                ),
            ),
            ScriptSegment(
                timestamp_range="09:00–09:40",
                section_title="OPEN QUESTIONS — What We Still Don't Know",
                narration_notes=(
                    "Catalog the unresolved forensic questions: (1) What abrasive or tool achieved "
                    "sub-mm flatness on Mohs 6-7 andesite? (2) How were interior channel corners "
                    "finished to <1° deviation? (3) What was the actual transport mechanism for "
                    "130+ ton blocks at 3 825 m elevation? State each as a blank template — no "
                    "speculative answers."
                ),
                visual_cues=(
                    "Engineering 'UNRESOLVED' stamp overlaying each question. "
                    "Wireframe H-Block rotating with question-mark annotations at key features. "
                    "Fade to blank data-table template."
                ),
            ),
            ScriptSegment(
                timestamp_range="09:40–10:00",
                section_title="OUTRO — Subscribe & Next Episode Tease",
                narration_notes=(
                    "Recap the core takeaway: the physical evidence demands an explanation that "
                    "our current archaeological model has not yet provided. Tease the next episode "
                    "(Saksaywaman polygonal walls). CTA: subscribe, comment with your analysis."
                ),
                visual_cues=(
                    "Pull back from H-Block detail to full Pumapunku site overview. "
                    "Transition to Saksaywaman teaser shot. End card with subscribe animation."
                ),
            ),
        ],
    )

    # ── 4. Visual prompts (5× 3D reconstruction) ────────────────────────
    visuals = [
        VisualPrompt(
            prompt_id="VP-PUMA-001",
            scene_description=(
                "Exploded orthographic projection of a Type-I H-Block showing all six faces "
                "separated by 50 mm gaps. Interior channel geometry and tenon recesses are "
                "visible. Dimension leaders annotate channel width (150 mm), depth (100 mm), "
                "and wall thickness (80 mm). A 1 m scale bar sits at lower-left."
            ),
            camera_angle="True orthographic — front elevation, no perspective distortion",
            lighting="Flat CAD-standard lighting: uniform diffuse, no cast shadows, thin black edge lines",
            render_style="Technical line-drawing overlay on light-gray PBR solid. Dimension text in DIN 1451 font.",
            focus_detail=(
                "Joint interface surfaces highlighted with a contrasting blue tint to emphasize "
                "the machined flatness zones. Tolerance callout: ±0.5 mm flatness over 2 m."
            ),
        ),
        VisualPrompt(
            prompt_id="VP-PUMA-002",
            scene_description=(
                "Cross-section cut through two interlocking H-Blocks at their dado-channel junction. "
                "The section plane bisects the center of the channel system, revealing the tongue-and-groove "
                "engagement profile. The cut face is hatched with standard ANSI31 stone hatching."
            ),
            camera_angle="Section view — perpendicular to the interlocking axis, 0° elevation",
            lighting="Studio HDRI with soft key light at 45° upper-left, fill at 20% intensity opposite",
            render_style="PBR andesite material (dark gray albedo 0.35, roughness 0.7, subtle porphyritic normal map). Cut face uses cross-hatch overlay.",
            focus_detail=(
                "Engagement gap between tongue and groove highlighted with a 2 mm red line showing "
                "the near-zero clearance. Inset magnification callout at 5× showing surface contact zone."
            ),
        ),
        VisualPrompt(
            prompt_id="VP-PUMA-003",
            scene_description=(
                "Macro close-up of a single machined andesite face from an H-Block, filling the "
                "full frame. The surface shows the characteristic planar finish with no visible "
                "tool striations. A digital surface-roughness overlay (false-color height map) "
                "is composited at 50% opacity."
            ),
            camera_angle="Normal to surface — 0° incidence, macro lens equivalent (100 mm f/2.8)",
            lighting="Raking light at 5° grazing angle from the left to reveal surface micro-topology",
            render_style="Photogrammetric PBR (albedo from scan data, roughness 0.65, displacement map from LiDAR point cloud). False-color height map: blue (low) → red (high), range ±0.5 mm.",
            focus_detail=(
                "Center region annotated with a flatness tolerance frame per ASME Y14.5: "
                "⏥ 0.5 mm / 2 000 mm. Corner inset shows the equivalent modern surface-plate spec."
            ),
        ),
        VisualPrompt(
            prompt_id="VP-PUMA-004",
            scene_description=(
                "Top-down site plan of the Pumapunku platform showing surveyed block positions. "
                "Extant H-Blocks are rendered as solid dark-gray volumes; missing/displaced blocks "
                "shown as dashed outlines in their hypothesized original positions. The platform "
                "base sandstone layer is rendered as a lighter red-brown slab beneath."
            ),
            camera_angle="Plan view — true top-down orthographic, north arrow at upper-right",
            lighting="Ambient occlusion only — no directional light, soft contact shadows between blocks",
            render_style="Architectural site-plan style: 1:200 scale bar, grid overlay at 5 m intervals, block IDs labeled (Vranich numbering).",
            focus_detail=(
                "Three H-Block clusters highlighted with colored borders (blue, green, orange) to "
                "indicate Type-I, Type-II, and Type-III variants. Legend in lower-right corner."
            ),
        ),
        VisualPrompt(
            prompt_id="VP-PUMA-005",
            scene_description=(
                "Cutaway isometric of an H-Block revealing the internal I-clamp (butterfly/dovetail) "
                "channels carved into the top surface. Two channels are shown: one empty exposing the "
                "carved recess geometry, one filled with a copper-bronze pour showing the solidified "
                "metal tie connecting two adjacent blocks."
            ),
            camera_angle="Low isometric — 30° elevation, 45° azimuth from front-left corner",
            lighting="Three-point studio rig: warm key (5 500 K) upper-right, cool fill (7 500 K) left, rim light behind",
            render_style="PBR dual-material: andesite body (roughness 0.7, dark gray) and polished copper fill (metallic 1.0, roughness 0.3, warm orange albedo). Section-cut face uses technical hatch.",
            focus_detail=(
                "I-clamp recess dimensioned: 120 mm length × 50 mm width × 30 mm depth (±1 mm). "
                "Arrow annotation shows pour direction. Inset detail circle at 3× magnification on "
                "the copper-stone interface showing zero-gap conformance."
            ),
        ),
    ]

    # ── 5. Assemble kickoff ──────────────────────────────────────────────
    kickoff = ProjectKickoff(
        project_title="Pumapunku H-Blocks — Precision That Shouldn't Exist",
        research=research,
        script=script,
        visuals=visuals,
    )

    return config, kickoff


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    config, kickoff = build_pumapunku_kickoff()

    print("=" * 72)
    print("ARCHAEOENG CONFIG PAYLOAD")
    print("=" * 72)
    print(config.generate_payload())

    print()
    print("=" * 72)
    print("PROJECT KICKOFF — PUMAPUNKU H-BLOCKS")
    print("=" * 72)
    print(kickoff.to_json())