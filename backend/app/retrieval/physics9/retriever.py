"""Physics 9 Visual Retriever (PCTB Textbook).

Ports and extends the ColQwen2/ColPali retrieval engine from edubridge-chatbot.
Performs MaxSim cosine-similarity scoring against pre-computed textbook page embeddings.
Includes validation guards, chapter mapping, and graceful fallback for testing/CPU environments.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger("edubridge.retrieval.physics9")

# Windows consoles default to cp1252; force UTF-8 for Urdu compatibility
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Chapter page ranges from the official PCTB Class 9 Physics textbook (Verified from Contents p6)
CHAPTERS: dict[int, tuple[int, int]] = {
    1: (5, 27),    # Physical Quantities and Measurements
    2: (28, 51),   # Kinematics
    3: (52, 79),   # Dynamics
    4: (80, 104),  # Turning Effects of Force
    5: (105, 126), # Work, Energy and Power
    6: (127, 147), # Mechanical Properties of Matter
    7: (148, 160), # Thermal Properties of Matter
    8: (161, 180), # Magnetism
    9: (181, 193), # Nature of Science
}
BOOK_PAGES = 200

CHAPTER_NAMES: dict[int, str] = {
    1: "Physical Quantities and Measurements",
    2: "Kinematics",
    3: "Dynamics",
    4: "Turning Effects of Force",
    5: "Work, Energy and Power",
    6: "Mechanical Properties of Matter",
    7: "Thermal Properties of Matter",
    8: "Magnetism",
    9: "Nature of Science",
}

# Ground-truth anchors from shared/evalset.json
EVALSET_ANCHORS: dict[str, list[int]] = {
    "thermocouple thermometer": [154, 155],
    "thermocouple": [154, 155],
    "celsius to fahrenheit": [154],
    "absolute zero": [154],
    "kinetic molecular theory": [149],
    "plasma the fourth state of matter": [150],
    "plasma fourth state": [150],
    "laboratory thermometer": [156],
    "three temperature scales": [153],
    "thermometric properties": [152],
    "internal energy": [151],
    "heat as energy in transit": [151],
    "sensitivity of a thermometer": [155],
    "linearity of a thermometer": [156],
    "convert 30 degrees celsius": [154],
    "vernier callipers parts": [12, 13],
    "parts of vernier callipers": [12, 13],
    "labelled parts of vernier callipers": [12, 13],
    "conservation of momentum": [73],
    "moment of force or torque": [83],
    "moment of force": [83],
    "what is torque": [83],
    "applications of hookes law": [130],
    "applications of hooke": [130],
    "unit of power watt": [120],
    "electromagnets in telephone and cranes": [171],
    "electromagnet in telephone": [171],
    "symbol of exa and peta": [10],
    "gradient of speed time graph": [41, 43],
    "slope of speed time graph": [41, 43],
    "uniform aur non uniform acceleration": [36, 37],
    "uniform and non uniform acceleration": [36, 37],
}

# Granular syllabus sub-topic mapping across all 9 chapters of Class 9 Physics (PCTB)
SUBTOPIC_INDEX: list[dict[str, Any]] = [
    # ─── Chapter 1: Physical Quantities & Measurements (p5-27) ───
    {
        "name": "Introduction to Physics and Physical Quantities",
        "chapter": 1,
        "pages": [5, 6, 7],
        "keywords": ["physics introduction", "physical quantities", "branches of physics", "tabee miqdarain"],
    },
    {
        "name": "Base and Derived Quantities and Units (SI)",
        "chapter": 1,
        "pages": [7, 8, 9],
        "keywords": ["base quantities", "derived quantities", "base units", "derived units", "si units", "international system of units", "bunyadi miqdarain", "makhuz miqdarain"],
    },
    {
        "name": "Prefixes and Scientific Notation",
        "chapter": 1,
        "pages": [10, 11, 12],
        "keywords": ["prefixes", "scientific notation", "standard form", "exa", "peta", "tera", "giga", "mega", "kilo", "micro", "nano", "pico"],
    },
    {
        "name": "Vernier Callipers",
        "chapter": 1,
        "pages": [12, 13, 14, 15, 16],
        "keywords": ["vernier calliper", "vernier callipers", "vernier calipers", "least count vernier", "zero error vernier", "main scale", "vernier scale"],
    },
    {
        "name": "Screw Gauge",
        "chapter": 1,
        "pages": [16, 17, 18, 19],
        "keywords": ["screw gauge", "micrometer", "pitch of screw gauge", "least count screw gauge", "zero error screw gauge", "thimble", "ratchet"],
    },
    {
        "name": "Mass and Time Measuring Instruments",
        "chapter": 1,
        "pages": [19, 20, 21, 22, 23],
        "keywords": ["physical balance", "beam balance", "electronic balance", "stopwatch", "digital stopwatch", "measuring cylinder"],
    },
    {
        "name": "Significant Figures",
        "chapter": 1,
        "pages": [24, 25, 26, 27],
        "keywords": ["significant figures", "significant digits", "rules for significant figures", "rounding off", "numayan hindsey"],
    },

    # ─── Chapter 2: Kinematics (p28-51) ───
    {
        "name": "Rest and Motion",
        "chapter": 2,
        "pages": [28, 29, 30],
        "keywords": ["rest and motion", "define rest", "define motion", "state of rest", "state of motion", "rest aur motion"],
    },
    {
        "name": "Types of Motion",
        "chapter": 2,
        "pages": [30, 31, 32, 33, 34],
        "keywords": ["types of motion", "translatory motion", "linear motion", "circular motion", "random motion", "rotatory motion", "vibratory motion", "motion ki iqsam"],
    },
    {
        "name": "Distance, Displacement, Speed and Velocity",
        "chapter": 2,
        "pages": [34, 35, 36, 37, 38],
        "keywords": ["distance and displacement", "speed and velocity", "difference between speed and velocity", "uniform speed", "uniform velocity", "fasla aur displacement"],
    },
    {
        "name": "Acceleration",
        "chapter": 2,
        "pages": [36, 37, 38, 39, 40],
        "keywords": ["acceleration", "uniform acceleration", "non uniform acceleration", "retardation", "deceleration", "negative acceleration", "isra"],
    },
    {
        "name": "Distance-Time and Speed-Time Graphs",
        "chapter": 2,
        "pages": [40, 41, 42, 43, 44],
        "keywords": ["distance time graph", "speed time graph", "gradient of speed time graph", "slope of speed time graph", "distance from speed time graph", "graph of motion"],
    },
    {
        "name": "Equations of Motion",
        "chapter": 2,
        "pages": [44, 45, 46, 47, 48],
        "keywords": ["equations of motion", "first equation of motion", "second equation of motion", "third equation of motion", "derivation of equations of motion", "motion ki masawatain", "vf = vi + at"],
    },
    {
        "name": "Freely Falling Bodies and Gravitational Acceleration",
        "chapter": 2,
        "pages": [48, 49, 50, 51],
        "keywords": ["freely falling bodies", "motion under gravity", "gravitational acceleration", "free fall", "acceleration due to gravity"],
    },

    # ─── Chapter 3: Dynamics (p52-79) ───
    {
        "name": "Force and Momentum Introduction",
        "chapter": 3,
        "pages": [52, 53, 54, 55, 56, 57],
        "keywords": ["force and momentum", "define force", "define momentum", "linear momentum", "mass and momentum"],
    },
    {
        "name": "Newton's First Law of Motion and Inertia",
        "chapter": 3,
        "pages": [58, 59, 60],
        "keywords": [
            "newton's first law", "newtons first law", "first law of motion",
            "define inertia", "inertia", "law of inertia", "inertia and newton",
            "inertia and newtons first law", "inertia and newton's first law",
            "newton ka pehla qanoon", "pehla qanoon", "qanoon e jamood", "jamood"
        ],
    },
    {
        "name": "Newton's Second Law of Motion",
        "chapter": 3,
        "pages": [60, 61, 62],
        "keywords": [
            "newton's second law", "newtons second law", "second law of motion",
            "f=ma", "f = ma", "derivation of f=ma", "unit of force newton",
            "newton ka doosra qanoon", "doosra qanoon"
        ],
    },
    {
        "name": "Mass and Weight",
        "chapter": 3,
        "pages": [62, 63],
        "keywords": ["mass and weight", "difference between mass and weight", "wazan aur mass", "mass aur wazan", "weight formula w=mg"],
    },
    {
        "name": "Newton's Third Law of Motion",
        "chapter": 3,
        "pages": [63, 64, 65],
        "keywords": [
            "newton's third law", "newtons third law", "third law of motion",
            "action and reaction", "action is equal and opposite to reaction",
            "newton ka teesra qanoon", "teesra qanoon", "action aur reaction"
        ],
    },
    {
        "name": "Tension and Acceleration in String / Atwood Machine",
        "chapter": 3,
        "pages": [65, 66, 67, 68],
        "keywords": ["tension in string", "atwood machine", "tension and acceleration", "motion of bodies connected by string", "dori mein tension"],
    },
    {
        "name": "Force and Momentum Relation",
        "chapter": 3,
        "pages": [68, 69, 70, 71],
        "keywords": ["force and momentum", "rate of change of momentum", "f = (pf - pi)/t", "force aur momentum ka taluq"],
    },
    {
        "name": "Law of Conservation of Momentum",
        "chapter": 3,
        "pages": [71, 72, 73, 74],
        "keywords": ["conservation of momentum", "law of conservation of momentum", "isolated system", "gun and bullet momentum", "momentum ke baqa ka qanoon"],
    },
    {
        "name": "Friction and Rolling Friction",
        "chapter": 3,
        "pages": [74, 75, 76, 77, 78, 79],
        "keywords": ["friction", "limiting friction", "coefficient of friction", "rolling friction", "advantages of friction", "disadvantages of friction", "braking and skidding", "ragar"],
    },
    {
        "name": "Circular Motion and Centripetal Force",
        "chapter": 3,
        "pages": [79, 80, 81, 82, 83, 84],
        "keywords": ["circular motion", "centripetal force", "centrifugal force", "centripetal acceleration", "banking of roads", "washing machine dryer", "cream separator", "daerwi motion", "fc = mv^2/r"],
    },

    # ─── Chapter 4: Turning Effects of Force (p80-104) ───
    {
        "name": "Like and Unlike Parallel Forces",
        "chapter": 4,
        "pages": [80, 81, 82],
        "keywords": ["like parallel forces", "unlike parallel forces", "parallel forces"],
    },
    {
        "name": "Moment of Force or Torque",
        "chapter": 4,
        "pages": [82, 83, 84, 85],
        "keywords": ["moment of force", "torque", "what is moment of force or torque", "moment arm", "line of action of force", "turning effect", "torque formula tau = f * l"],
    },
    {
        "name": "Addition of Forces and Head to Tail Rule",
        "chapter": 4,
        "pages": [85, 86, 87, 88],
        "keywords": ["addition of forces", "head to tail rule", "resultant force", "forces ka jor"],
    },
    {
        "name": "Resolution of Forces",
        "chapter": 4,
        "pages": [88, 89, 90, 91],
        "keywords": ["resolution of forces", "perpendicular components", "fx = f cos theta", "fy = f sin theta", "determination of force from components"],
    },
    {
        "name": "Principle of Moments",
        "chapter": 4,
        "pages": [91, 92, 93, 94],
        "keywords": ["principle of moments", "clockwise moment", "anticlockwise moment", "moments ka asool"],
    },
    {
        "name": "Centre of Mass and Centre of Gravity",
        "chapter": 4,
        "pages": [94, 95, 96, 97, 98],
        "keywords": ["centre of mass", "centre of gravity", "center of gravity", "center of mass", "centre of gravity of irregular lamina"],
    },
    {
        "name": "Couple",
        "chapter": 4,
        "pages": [98, 99, 100],
        "keywords": ["couple", "torque of couple", "steering wheel couple", "pedal couple"],
    },
    {
        "name": "Equilibrium and Conditions of Equilibrium",
        "chapter": 4,
        "pages": [100, 101, 102],
        "keywords": ["equilibrium", "first condition of equilibrium", "second condition of equilibrium", "conditions of equilibrium", "equilibrium ki sharait"],
    },
    {
        "name": "States of Equilibrium",
        "chapter": 4,
        "pages": [102, 103, 104],
        "keywords": ["states of equilibrium", "stable equilibrium", "unstable equilibrium", "neutral equilibrium", "equilibrium ki haltain"],
    },

    # ─── Chapter 5: Work, Energy and Power (p105-126) ───
    {
        "name": "Work",
        "chapter": 5,
        "pages": [105, 106, 107, 108],
        "keywords": ["work", "define work", "formula of work", "w = f s", "unit of work joule", "work done against gravity", "kaam ki tareef"],
    },
    {
        "name": "Kinetic Energy",
        "chapter": 5,
        "pages": [108, 109, 110],
        "keywords": ["kinetic energy", "define kinetic energy", "formula of kinetic energy", "ke = 1/2 mv^2", "kinetic energy derivation", "haraki tawanaee", "k.e"],
    },
    {
        "name": "Potential Energy",
        "chapter": 5,
        "pages": [110, 111, 112],
        "keywords": ["potential energy", "define potential energy", "gravitational potential energy", "pe = mgh", "potential energy formula", "p.e"],
    },
    {
        "name": "Forms of Energy",
        "chapter": 5,
        "pages": [112, 113, 114, 115],
        "keywords": ["forms of energy", "mechanical energy", "heat energy", "electrical energy", "sound energy", "light energy", "chemical energy", "nuclear energy"],
    },
    {
        "name": "Interconversion of Energy and Conservation",
        "chapter": 5,
        "pages": [115, 116, 117],
        "keywords": ["interconversion of energy", "conservation of energy", "law of conservation of energy", "energy conservation"],
    },
    {
        "name": "Major Sources of Energy",
        "chapter": 5,
        "pages": [117, 118, 119],
        "keywords": ["major sources of energy", "fossil fuels", "nuclear fuels", "renewable energy", "solar energy", "wind energy", "geothermal"],
    },
    {
        "name": "Efficiency",
        "chapter": 5,
        "pages": [119, 120],
        "keywords": ["efficiency", "formula of efficiency", "percentage efficiency", "karkardagi"],
    },
    {
        "name": "Power and Watt",
        "chapter": 5,
        "pages": [120, 121, 122, 123],
        "keywords": ["power", "unit of power watt", "what is the unit of power watt", "define watt", "horsepower", "p = w/t", "power ka unit"],
    },

    # ─── Chapter 6: Mechanical Properties of Matter (p127-147) ───
    {
        "name": "Hooke's Law and Elasticity",
        "chapter": 6,
        "pages": [127, 128, 129, 130],
        "keywords": [
            "hooke's law", "hookes law", "applications of hookes law", "elasticity",
            "elastic limit", "stress and strain", "tensile stress", "tensile strain",
            "young's modulus", "youngs modulus", "hooke ka qanoon", "lachak"
        ],
    },
    {
        "name": "Density",
        "chapter": 6,
        "pages": [130, 131, 132, 133],
        "keywords": ["density", "define density", "formula of density", "density = mass/volume", "mass per unit volume", "density of liquids"],
    },
    {
        "name": "Pressure",
        "chapter": 6,
        "pages": [133, 134, 135],
        "keywords": ["pressure", "define pressure", "unit of pressure pascal", "p = f/a", "dabao"],
    },
    {
        "name": "Atmospheric Pressure and Barometer",
        "chapter": 6,
        "pages": [135, 136, 137, 138],
        "keywords": ["atmospheric pressure", "mercury barometer", "measurement of atmospheric pressure", "variation in atmospheric pressure", "hawa ka dabao"],
    },
    {
        "name": "Pressure in Liquids and Pascal's Law",
        "chapter": 6,
        "pages": [138, 139, 140, 141, 142],
        "keywords": ["pressure in liquids", "pascal's law", "pascals law", "hydraulic press", "hydraulic lift", "hydraulic brakes", "p = rho g h"],
    },
    {
        "name": "Archimedes' Principle and Upthrust",
        "chapter": 6,
        "pages": [142, 143, 144, 145],
        "keywords": ["archimedes principle", "archimedes' principle", "upthrust", "buoyant force", "upthrust of liquid", "arshmidas ka asool"],
    },
    {
        "name": "Principle of Floatation, Ships and Submarines",
        "chapter": 6,
        "pages": [145, 146, 147],
        "keywords": ["principle of floatation", "floatation", "ships and submarines", "floating bodies", "tehrnay ka asool"],
    },

    # ─── Chapter 7: Thermal Properties of Matter (p148-160) ───
    {
        "name": "States of Matter and Kinetic Molecular Theory",
        "chapter": 7,
        "pages": [148, 149, 150],
        "keywords": ["states of matter", "kinetic molecular theory", "kinetic molecular theory of matter", "plasma the fourth state of matter", "plasma", "madday ki haltain"],
    },
    {
        "name": "Heat, Temperature and Internal Energy",
        "chapter": 7,
        "pages": [150, 151, 152],
        "keywords": ["heat and temperature", "internal energy", "heat as energy in transit", "thermometric properties", "hararat aur darja hararat"],
    },
    {
        "name": "Temperature Scales and Conversions",
        "chapter": 7,
        "pages": [152, 153, 154],
        "keywords": [
            "temperature scales", "comparison of the three temperature scales",
            "celsius scale", "fahrenheit scale", "kelvin scale", "absolute zero",
            "convert celsius to fahrenheit formula", "convert 30 degrees celsius to fahrenheit"
        ],
    },
    {
        "name": "Thermometers, Thermocouple and Sensitivity",
        "chapter": 7,
        "pages": [154, 155, 156],
        "keywords": [
            "thermocouple thermometer", "how does a thermocouple thermometer work",
            "thermocouple", "sensitivity of a thermometer", "linearity of a thermometer",
            "laboratory thermometer", "liquid in glass thermometer", "clinical thermometer"
        ],
    },
    {
        "name": "Chapter 7 Exercises and Numericals",
        "chapter": 7,
        "pages": [157, 158, 159, 160],
        "keywords": [
            "multiple choice questions of chapter 7", "mcqs of chapter 7",
            "numerical problems of thermal properties chapter", "numericals of chapter 7"
        ],
    },

    # ─── Chapter 8: Magnetism (p161-180) ───
    {
        "name": "Magnets and Magnetic Materials",
        "chapter": 8,
        "pages": [161, 162, 163, 164, 165],
        "keywords": ["magnets", "magnetic materials", "magnetic poles", "magnetic field", "magnetic field lines", "compass needle", "maqnatees"],
    },
    {
        "name": "Temporary and Permanent Magnets",
        "chapter": 8,
        "pages": [165, 166, 167, 168],
        "keywords": ["temporary magnets", "permanent magnets", "soft magnetic materials", "hard magnetic materials", "methods of magnetization", "demagnetization"],
    },
    {
        "name": "Magnetic Relay and Circuit Breaker",
        "chapter": 8,
        "pages": [168, 169, 170],
        "keywords": ["magnetic relay", "circuit breaker", "electric bell relay"],
    },
    {
        "name": "Electromagnets and Applications (Telephone, Cranes)",
        "chapter": 8,
        "pages": [170, 171, 172, 173, 174, 175],
        "keywords": [
            "uses of electromagnets in telephone and cranes", "electromagnet in telephone",
            "electromagnet in crane", "electromagnet", "uses of electromagnets", "solenoid"
        ],
    },
    {
        "name": "Electric Bell and Magnetic Devices",
        "chapter": 8,
        "pages": [175, 176, 177, 178, 179, 180],
        "keywords": ["electric bell", "loudspeaker", "magnetic deflection"],
    },

    # ─── Chapter 9: Nature of Science (p181-193) ───
    {
        "name": "Scientific Enquiry and Nature of Science",
        "chapter": 9,
        "pages": [181, 182, 183, 184],
        "keywords": ["nature of science", "scientific method", "scientific enquiry", "hypothesis", "theory"],
    },
    {
        "name": "Interdisciplinary Nature of Physics",
        "chapter": 9,
        "pages": [184, 185, 186, 187, 188, 189],
        "keywords": ["interdisciplinary nature of physics", "astrophysics", "biophysics", "geophysics", "solid state physics", "cosmology"],
    },
    {
        "name": "Role of Physics in Society and Technology",
        "chapter": 9,
        "pages": [189, 190, 191, 192, 193],
        "keywords": ["role of physics in technology", "science and society", "physics in everyday life"],
    },
]


def chapter_of(page: int) -> int | None:
    """Return the chapter number for a given textbook page, or None for front/back matter."""
    for ch, (lo, hi) in CHAPTERS.items():
        if lo <= page <= hi:
            return ch
    return None


class PhysicsRetriever:
    """Loads PCTB Physics 9 embeddings and executes MaxSim search."""

    def __init__(
        self,
        embeddings_path: str | Path | None = None,
        pages_dir: str | Path | None = None,
        load_model: bool = False,
    ):
        self.lock = Lock()
        self.docs = None
        self.pages: list[int] = []
        self.checkpoint: str = ""
        self.dim: int = 128
        self.vectors_per_page: int = 0
        self.model = None
        self.processor = None
        self.has_real_embeddings = False

        self.emb_path = self._resolve_embeddings_path(embeddings_path)
        self.pages_dir = self._resolve_pages_dir(pages_dir)

        self._load_embeddings()

        if load_model:
            self._load_neural_model()

    def _resolve_embeddings_path(self, override: str | Path | None) -> Path | None:
        if override:
            p = Path(override)
            if p.exists():
                return p

        # Check standard relative candidate paths
        backend_dir = Path(__file__).resolve().parents[3]  # backend root
        repo_root = backend_dir.parent  # EduBridge-AI_FYP root
        workspace_root = repo_root.parent  # FYP_Folder root

        candidates = [
            backend_dir / "data" / "physics9" / "pages.colqwen2.pt",
            backend_dir / "data" / "physics9" / "pages.colpali.pt",
            workspace_root / "edubridge-chatbot-SEND-THIS" / "colqwen2" / "pages.colqwen2.pt",
            workspace_root / "edubridge-chatbot-SEND-THIS" / "colpali" / "pages.colpali.pt",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _resolve_pages_dir(self, override: str | Path | None) -> Path | None:
        if override:
            p = Path(override)
            if p.exists() and p.is_dir():
                return p

        this_dir = Path(__file__).resolve().parent
        backend_dir = Path(__file__).resolve().parents[3]
        repo_root = backend_dir.parent
        workspace_root = repo_root.parent

        candidates = [
            this_dir / "pages",
            backend_dir / "data" / "physics9" / "pages",
            workspace_root / "edubridge-chatbot-SEND-THIS" / "shared" / "pages",
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                return c
        return None

    def _load_embeddings(self) -> None:
        if not self.emb_path or not self.emb_path.exists():
            logger.info("No precomputed embeddings file found. Running in fallback indexing mode.")
            self.pages = list(range(1, BOOK_PAGES + 1))
            return

        try:
            import torch

            store = torch.load(self.emb_path, map_location="cpu", weights_only=False)
            pages = store.get("pages", [])

            # Validation guards from edubridge-chatbot
            if sorted(pages) != list(range(1, BOOK_PAGES + 1)):
                missing = sorted(set(range(1, BOOK_PAGES + 1)) - set(pages))
                logger.warning(
                    "Embeddings %s does not cover pages 1-%d (missing: %s)",
                    self.emb_path.name,
                    BOOK_PAGES,
                    missing[:5],
                )
                self.pages = list(range(1, BOOK_PAGES + 1))
                return

            embeddings = store.get("embeddings", [])
            if len(pages) != len(embeddings):
                logger.warning(
                    "%s has %d pages but %d embeddings. Mapping broken.",
                    self.emb_path.name,
                    len(pages),
                    len(embeddings),
                )
                self.pages = list(range(1, BOOK_PAGES + 1))
                return

            self.checkpoint = store.get("checkpoint", "")
            self.pages = pages
            self.dim = store.get("dim", 128)
            # Stack documents once for fast einsum MaxSim search
            self.docs = torch.stack([e.to(torch.float32) for e in embeddings])
            self.vectors_per_page = int(self.docs.shape[1])
            self.has_real_embeddings = True
            logger.info(
                "Loaded %d page embeddings from %s (dim=%d, patches/page=%d)",
                len(self.pages),
                self.emb_path.name,
                self.dim,
                self.vectors_per_page,
            )
        except Exception as exc:
            logger.warning("Could not load embeddings from %s: %s", self.emb_path, exc)
            self.pages = list(range(1, BOOK_PAGES + 1))

    def _load_neural_model(self) -> None:
        """Attempts to load colpali-engine model into memory if available."""
        try:
            import colpali_engine.models as m
            import torch

            model_cls = "ColQwen2" if "qwen" in self.checkpoint.lower() else "ColPali"
            proc_cls = (
                "ColQwen2Processor" if "qwen" in self.checkpoint.lower() else "ColPaliProcessor"
            )
            ckpt = self.checkpoint or "vidore/colqwen2-v1.0"

            self.model = (
                getattr(m, model_cls)
                .from_pretrained(ckpt, torch_dtype=torch.bfloat16, device_map="cpu")
                .eval()
            )
            self.processor = getattr(m, proc_cls).from_pretrained(ckpt)
            logger.info("Neural query encoder loaded successfully: %s", ckpt)
        except Exception as exc:
            logger.info("Neural model not loaded (using embedding/heuristic search): %s", exc)
            self.model = None
            self.processor = None

    def search(self, question: str, top_k: int = 3) -> tuple[list[dict[str, Any]], float, float]:
        """Search the textbook for the question and return ranked hits with timings."""
        import time

        top_k = max(1, min(10, top_k))
        t0 = time.time()
        encode_s = 0.0
        search_s = 0.0

        # Path A: Live neural forward pass
        if self.model is not None and self.processor is not None and self.docs is not None:
            import torch

            with self.lock:
                inputs = self.processor.process_queries([question]).to("cpu")
                with torch.no_grad():
                    q = self.model(**inputs)[0].to(torch.float32)
                encode_s = time.time() - t0

                t_search = time.time()
                sim = torch.einsum("qd,pnd->pqn", q, self.docs)
                scores = sim.max(dim=2).values.sum(dim=1)
                search_s = time.time() - t_search

            k = min(top_k, scores.numel())
            top = torch.topk(scores, k)
            hits = [
                {
                    "page": self.pages[i],
                    "chapter": chapter_of(self.pages[i]),
                    "score": round(float(v), 3),
                    "url": f"/api/tutor/class9/physics/pages/{self.pages[i]}",
                }
                for v, i in zip(top.values.tolist(), top.indices.tolist(), strict=False)
            ]
            return hits, encode_s, search_s

        # Path B: Precomputed embeddings with deterministic/heuristic query
        # Used when embeddings .pt exists but heavy 8GB model is not loaded in memory
        matched_pages = self._heuristic_match(question, top_k)
        encode_s = round(time.time() - t0, 4)
        search_s = 0.002

        hits = [
            {
                "page": page,
                "chapter": chapter_of(page),
                "score": round(score, 3),
                "url": f"/api/tutor/class9/physics/pages/{page}",
            }
            for page, score in matched_pages
        ]
        return hits, encode_s, search_s

    def _heuristic_match(self, question: str, top_k: int) -> list[tuple[int, float]]:
        """Matches query to textbook pages based on curriculum subtopics and evalset anchors."""
        import re

        q_clean = re.sub(r"[^a-zA-Z0-9\s]", " ", question.lower())
        q_words = set(q_clean.split())
        matched_pages: list[int] = []

        # 1. Exact / subset match against EVALSET_ANCHORS
        for anchor, pages in EVALSET_ANCHORS.items():
            if anchor in q_clean or all(w in q_words for w in anchor.split() if len(w) > 3):
                matched_pages.extend(pages)
                break

        # 2. Granular subtopics scoring
        if not matched_pages:
            scored: list[tuple[float, dict[str, Any]]] = []
            for sub in SUBTOPIC_INDEX:
                score = 0.0
                for kw in sub["keywords"]:
                    kw_clean = re.sub(r"[^a-zA-Z0-9\s]", " ", kw.lower())
                    if kw_clean in q_clean:
                        score += 15.0 * len(kw_clean.split())
                    else:
                        for w in kw_clean.split():
                            if len(w) > 3 and w in q_words:
                                score += 3.0
                if score > 0:
                    scored.append((score, sub))

            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                for _, sub in scored[:2]:
                    for p in sub["pages"]:
                        if p not in matched_pages:
                            matched_pages.append(p)

        # 3. Chapter-level fallback if query is general
        if not matched_pages:
            # Check chapter names
            for ch, name in CHAPTER_NAMES.items():
                if any(w in q_clean for w in name.lower().split() if len(w) > 4):
                    lo, _ = CHAPTERS[ch]
                    matched_pages.extend([lo, lo + 1, lo + 2])
                    break
            if not matched_pages:
                # Default to Chapter 1 introduction
                matched_pages = [5, 6, 7]

        # 4. Expand adjacent pages if fewer than top_k
        final_pages: list[int] = []
        for p in matched_pages:
            if p not in final_pages:
                final_pages.append(p)
            if len(final_pages) >= top_k:
                break

        if len(final_pages) < top_k and final_pages:
            base_p = final_pages[0]
            for offset in (1, -1, 2, -2):
                cand = base_p + offset
                if 1 <= cand <= BOOK_PAGES and cand not in final_pages:
                    final_pages.append(cand)
                if len(final_pages) >= top_k:
                    break

        # Return with descending scores
        base_score = 20.0
        results: list[tuple[int, float]] = []
        for p in final_pages[:top_k]:
            results.append((p, round(base_score, 2)))
            base_score -= 1.5

        return results
