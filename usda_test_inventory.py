from __future__ import annotations

from dataclasses import dataclass
import re


_PRIM_START_RE = re.compile(r'^(?P<indent>\s*)(?:def|over|class)\s+(?P<type>\w+)\s+"(?P<name>[^"]+)"(?:\s*\()?\s*$')


@dataclass(frozen=True)
class UsdaPrim:
    path: str
    type_name: str
    direct_text: str
    text: str


class UsdaInventory:
    def __init__(self, prims: dict[str, UsdaPrim]) -> None:
        self._prims = prims

    @classmethod
    def from_text(cls, text: str) -> "UsdaInventory":
        prims: dict[str, dict[str, object]] = {}
        stack: list[dict[str, object]] = []
        brace_depth = 0

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                continue

            match = _PRIM_START_RE.match(line)
            created_node = False
            if match is not None:
                type_name = match.group("type")
                name = match.group("name")
                parent_path = stack[-1]["path"] if stack else ""
                path = f"{parent_path}/{name}" if parent_path else f"/{name}"
                node = {
                    "path": path,
                    "type_name": type_name,
                    "direct_lines": [],
                    "subtree_lines": [],
                    "body_depth": None,
                    "declaration_paren_depth": line.count("(") - line.count(")"),
                }
                prims[path] = node
                stack.append(node)
                created_node = True
            if stack:
                stack[-1]["direct_lines"].append(line)
                for active in stack:
                    active["subtree_lines"].append(line)

            opens = line.count("{")
            closes = line.count("}")
            brace_depth += opens - closes
            if stack and stack[-1]["body_depth"] is None:
                if not created_node:
                    stack[-1]["declaration_paren_depth"] += line.count("(") - line.count(")")
                if opens and stack[-1]["declaration_paren_depth"] <= 0:
                    stack[-1]["body_depth"] = brace_depth
            while stack and stack[-1]["body_depth"] is not None and brace_depth < stack[-1]["body_depth"]:
                stack.pop()

        return cls(
            {
                path: UsdaPrim(
                    path=path,
                    type_name=node["type_name"],
                    direct_text="\n".join(node["direct_lines"]),
                    text="\n".join(node["subtree_lines"]),
                )
                for path, node in prims.items()
            }
        )

    def prim(self, path: str) -> UsdaPrim:
        return self._prims[path]

    def has_prim(self, path: str, type_name: str | None = None) -> bool:
        prim = self._prims.get(path)
        return prim is not None and (type_name is None or prim.type_name == type_name)

    def contains(self, path: str, fragment: str) -> bool:
        return fragment in self.prim(path).text

    def direct_contains(self, path: str, fragment: str) -> bool:
        return fragment in self.prim(path).direct_text

    def has_attribute(self, path: str, attribute_name: str) -> bool:
        pattern = re.compile(rf"(?m)^\s*(?:[A-Za-z0-9_\[\]]+\s+)*{re.escape(attribute_name)}\s*=")
        return bool(pattern.search(self.prim(path).direct_text))

    def has_relationship(self, path: str, relationship_name: str) -> bool:
        pattern = re.compile(rf"(?m)^\s*(?:prepend\s+|append\s+)?rel\s+{re.escape(relationship_name)}\s*=")
        return bool(pattern.search(self.prim(path).direct_text))

    def has_api_schema(self, path: str, schema_name: str) -> bool:
        prim_text = self.prim(path).direct_text
        return f'apiSchemas = ["{schema_name}"' in prim_text
