"""Intercepts openseespy calls to record model geometry without running real analysis."""

import sys
import types
from typing import Any, TypedDict


class Section(TypedDict, total=False):
    tag: int
    color: str
    label: str


# Node counts for common element types (used to separate node tags from other args)
_NODE_COUNT: dict[str, int] = {
    'elasticBeamColumn': 2,
    'forceBeamColumn': 2,
    'dispBeamColumn': 2,
    'truss': 2,
    'corotTruss': 2,
    'zeroLength': 2,
}


class Viewer(TypedDict, total=False):
    sections: list[Section]
    precision: int


class ModelInterceptor:
    """Mock openseespy module: records model data instead of building a real model."""

    def __init__(self) -> None:
        self.ndm: int = 2
        self.ndf: int = 3
        self.nodes: list[dict[str, Any]] = []
        self.elements: list[dict[str, Any]] = []
        self.supports: list[dict[str, Any]] = []
        self.nodal_loads: list[dict[str, Any]] = []
        self.viewer: Viewer | None = None
        self._section_tags: set[int] = set()
    def model(self, *args: Any) -> None:
        str_args = [str(a) for a in args]
        if '-ndm' in str_args:
            self.ndm = int(str_args[str_args.index('-ndm') + 1])
        if '-ndf' in str_args:
            self.ndf = int(str_args[str_args.index('-ndf') + 1])

    def node(self, tag: int, *coords: float) -> None:
        self.nodes.append({"tag": int(tag), "coords": [float(c) for c in coords]})

    def section(self, stype: str, tag: int, *args: Any) -> None:
        self._section_tags.add(int(tag))

    def element(self, etype: str, tag: int, *args: Any) -> None:
        ncount = _NODE_COUNT.get(etype)
        if ncount is not None and len(args) >= ncount:
            node_tags = [int(a) for a in args[:ncount]]
            rest = args[ncount:]
        else:
            # Fallback: collect leading integers as node tags
            node_tags = []
            for a in args:
                if isinstance(a, int):
                    node_tags.append(int(a))
                else:
                    break
            rest = args[len(node_tags):]

        entry: dict[str, Any] = {"tag": int(tag), "type": str(etype), "nodes": node_tags}

        # First remaining int that matches a known section tag → section reference
        if rest and isinstance(rest[0], int) and rest[0] in self._section_tags:
            entry["section"] = int(rest[0])

        self.elements.append(entry)

    def fix(self, tag: int, *dofs: int) -> None:
        self.supports.append({"tag": int(tag), "dofs": [int(d) for d in dofs]})

    def load(self, tag: int, *values: float) -> None:
        self.nodal_loads.append({"tag": int(tag), "values": [float(v) for v in values]})

    def timeSeries(self, *args: Any, **kwargs: Any) -> None:
        pass

    def pattern(self, *args: Any, **kwargs: Any) -> None:
        pass

    def wipe(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": 1,
            "ndm": self.ndm,
            "ndf": self.ndf,
            "nodes": self.nodes,
            "elements": self.elements,
            "supports": self.supports,
            "nodal_loads": self.nodal_loads,
            "error": None,
        }
        if self.viewer is not None:
            result["viewer"] = self.viewer
        return result


def inject(interceptor: ModelInterceptor) -> dict[str, Any]:
    """Inject interceptor into sys.modules. Returns previous state for cleanup."""
    mock_package = types.ModuleType('openseespy')
    mock_package.opensees = interceptor  # type: ignore[attr-defined]
    mock_package.__path__ = []  # type: ignore[attr-defined]

    saved: dict[str, Any] = {}
    for key in ('openseespy', 'openseespy.opensees'):
        if key in sys.modules:
            saved[key] = sys.modules[key]

    sys.modules['openseespy'] = mock_package
    sys.modules['openseespy.opensees'] = interceptor  # type: ignore[assignment]
    return saved


def restore(saved: dict[str, Any]) -> None:
    """Restore sys.modules to state before inject()."""
    for key in ('openseespy', 'openseespy.opensees'):
        if key in saved:
            sys.modules[key] = saved[key]
        elif key in sys.modules:
            del sys.modules[key]
