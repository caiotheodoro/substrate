"""@substrate/knowledge (04) — operating retrieval like it's a database."""

__version__ = "0.1.0"

from substrate_knowledge.core.verdicts import RetrievalVerdict, VerdictKind, gate
from substrate_knowledge.core.ontology import DEFAULT_ONTOLOGY, OntologyRegistry

__all__ = ["RetrievalVerdict", "VerdictKind", "gate", "DEFAULT_ONTOLOGY", "OntologyRegistry", "__version__"]
