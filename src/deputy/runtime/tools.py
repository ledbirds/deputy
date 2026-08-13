"""Tools an agent may call, each declaring what kind of action it is.

The important field is not the callable. It is `action`: every tool declares
whether invoking it is reversible and whether it is externally visible. That
declaration is what the policy engine reads, so authority is expressed once,
at the point the capability is defined, rather than re-derived at every call
site by whoever remembers to check.

A tool with no declared action cannot be registered. Forgetting to classify
a capability is the failure that quietly grants an agent the ability to send
things, and it is caught here at registration rather than at 3am.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from deputy.policy.rules import Action


class ToolError(RuntimeError):
    """A tool failed. Carried back to the agent rather than crashing the run."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    reversible: bool
    external: bool
    attrs: dict[str, Any] = field(default_factory=dict)

    def action_for(self, subject: str = "") -> Action:
        return Action(
            name=self.name,
            subject=subject,
            reversible=self.reversible,
            external=self.external,
            attrs=dict(self.attrs),
        )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self.fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalised for the agent loop
            raise ToolError(f"{self.name} failed: {exc}") from exc


class Toolbox:
    """A registry of tools, keyed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        fn: Callable[..., Any],
        *,
        reversible: bool,
        external: bool,
        **attrs: Any,
    ) -> Tool:
        if name in self._tools:
            raise ValueError(f"tool {name!r} is already registered")
        tool = Tool(
            name=name,
            description=description,
            fn=fn,
            reversible=reversible,
            external=external,
            attrs=attrs,
        )
        self._tools[name] = tool
        return tool

    def tool(
        self, name: str, description: str, *, reversible: bool, external: bool, **attrs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator form. Both flags are required, on purpose."""

        def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(
                name,
                description,
                fn,
                reversible=reversible,
                external=external,
                **attrs,
            )
            return fn

        return wrap

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"no such tool: {name!r}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        lines = []
        for name in self.names():
            tool = self._tools[name]
            flags = []
            if not tool.reversible:
                flags.append("irreversible")
            if tool.external:
                flags.append("external")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"- {name}: {tool.description}{suffix}")
        return "\n".join(lines)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
