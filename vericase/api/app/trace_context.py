from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


_chain_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vericase_chain_id", default=None
)
_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vericase_run_id", default=None
)
_node: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vericase_node", default=None
)
_input_refs: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "vericase_input_refs", default=None
)
_output_refs: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "vericase_output_refs", default=None
)


@dataclass(frozen=True)
class TraceContext:
    chain_id: str | None = None
    run_id: str | None = None
    node: str | None = None
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)


def get_trace_context() -> TraceContext:
    return TraceContext(
        chain_id=_chain_id.get(),
        run_id=_run_id.get(),
        node=_node.get(),
        input_refs=list(_input_refs.get() or []),
        output_refs=list(_output_refs.get() or []),
    )


def ensure_chain_id(chain_id: str | None = None) -> str:
    existing = chain_id or _chain_id.get()
    if existing:
        return existing
    new_id = str(uuid.uuid4())
    _chain_id.set(new_id)
    return new_id


def set_trace_context(
    *,
    chain_id: str | None = None,
    run_id: str | None = None,
    node: str | None = None,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
) -> dict[str, contextvars.Token[Any]]:
    tokens: dict[str, contextvars.Token[Any]] = {}
    if chain_id is not None:
        tokens["chain_id"] = _chain_id.set(chain_id)
    if run_id is not None:
        tokens["run_id"] = _run_id.set(run_id)
    if node is not None:
        tokens["node"] = _node.set(node)
    if input_refs is not None:
        tokens["input_refs"] = _input_refs.set(list(input_refs))
    if output_refs is not None:
        tokens["output_refs"] = _output_refs.set(list(output_refs))
    return tokens


def reset_trace_context(tokens: dict[str, contextvars.Token[Any]]) -> None:
    for key, token in tokens.items():
        if key == "chain_id":
            _chain_id.reset(token)
        elif key == "run_id":
            _run_id.reset(token)
        elif key == "node":
            _node.reset(token)
        elif key == "input_refs":
            _input_refs.reset(token)
        elif key == "output_refs":
            _output_refs.reset(token)


@contextmanager
def trace_context(
    *,
    chain_id: str | None = None,
    run_id: str | None = None,
    node: str | None = None,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
) -> Iterator[TraceContext]:
    tokens = set_trace_context(
        chain_id=chain_id,
        run_id=run_id,
        node=node,
        input_refs=input_refs,
        output_refs=output_refs,
    )
    try:
        yield get_trace_context()
    finally:
        reset_trace_context(tokens)
