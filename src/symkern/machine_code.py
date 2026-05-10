from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from pathlib import Path


CODE_MAGIC = b"SYMKC1\0"
LEXICON_MAGIC = b"SYMKL1\0"
SYMBOLS_MAGIC = b"SYMKS1\0"
CODE_SCHEMA_VERSION = "symkern.machine-code/v1alpha2"
LEXICON_SCHEMA_VERSION = "symkern.machine-lexicon/v1alpha1"
SYMBOL_SNAPSHOT_SCHEMA_VERSION = "symkern.machine-symbols/v1alpha1"
LANGUAGE_DOCUMENT_SCHEMA_VERSION = "symkern.machine-language/v1alpha1"


def _pack_binary(magic: bytes, payload: dict[str, object]) -> bytes:
    compact = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return magic + zlib.compress(compact, level=9)


def _unpack_binary(blob: bytes, magic: bytes) -> dict[str, object]:
    if not blob.startswith(magic):
        raise ValueError("Unsupported machine binary header.")
    return json.loads(zlib.decompress(blob[len(magic):]).decode("utf-8"))


@dataclass(slots=True)
class MachineLexicon:
    symbols: dict[str, int]
    keys: dict[str, int]
    atoms: dict[str, int]

    @classmethod
    def empty(cls) -> "MachineLexicon":
        return cls(symbols={}, keys={}, atoms={})

    @classmethod
    def from_bytes(cls, blob: bytes) -> "MachineLexicon":
        payload = _unpack_binary(blob, LEXICON_MAGIC)
        if payload.get("schema_version") != LEXICON_SCHEMA_VERSION:
            raise ValueError(f"Unsupported machine lexicon schema version: {payload.get('schema_version')}")
        return cls(
            symbols={str(key): int(value) for key, value in dict(payload.get("symbols", {})).items()},
            keys={str(key): int(value) for key, value in dict(payload.get("keys", {})).items()},
            atoms={str(key): int(value) for key, value in dict(payload.get("atoms", {})).items()},
        )

    def to_bytes(self) -> bytes:
        payload = {
            "schema_version": LEXICON_SCHEMA_VERSION,
            "symbols": dict(sorted(self.symbols.items())),
            "keys": dict(sorted(self.keys.items())),
            "atoms": dict(sorted(self.atoms.items())),
        }
        return _pack_binary(LEXICON_MAGIC, payload)

    def _add(self, table: dict[str, int], value: str) -> int:
        normalized = str(value)
        existing = table.get(normalized)
        if existing is not None:
            return existing
        identifier = max(table.values(), default=0) + 1
        table[normalized] = identifier
        return identifier

    def add_symbol(self, value: str) -> int:
        return self._add(self.symbols, value)

    def add_key(self, value: str) -> int:
        return self._add(self.keys, value)

    def add_atom(self, value: str) -> int:
        return self._add(self.atoms, value)


class _NodeTable:
    def __init__(self) -> None:
        self._forward: dict[str, int] = {}

    def add(self, value: str) -> int:
        normalized = str(value)
        existing = self._forward.get(normalized)
        if existing is not None:
            return existing
        identifier = len(self._forward) + 1
        self._forward[normalized] = identifier
        return identifier

    def to_reverse_dict(self) -> dict[int, str]:
        return {identifier: value for value, identifier in self._forward.items()}


@dataclass(slots=True)
class SymbolSnapshot:
    run_id: str
    node_ids: dict[int, str]
    opcode_ids: list[int]
    symbol_ids: list[int]
    key_ids: list[int]
    atom_ids: list[int]

    @classmethod
    def from_bytes(cls, blob: bytes) -> "SymbolSnapshot":
        payload = _unpack_binary(blob, SYMBOLS_MAGIC)
        if payload.get("schema_version") != SYMBOL_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported machine symbols schema version: {payload.get('schema_version')}")
        return cls(
            run_id=str(payload.get("run_id", "")),
            node_ids={int(key): str(value) for key, value in dict(payload.get("node_ids", {})).items()},
            opcode_ids=[int(item) for item in list(payload.get("opcode_ids", []))],
            symbol_ids=[int(item) for item in list(payload.get("symbol_ids", []))],
            key_ids=[int(item) for item in list(payload.get("key_ids", []))],
            atom_ids=[int(item) for item in list(payload.get("atom_ids", []))],
        )

    def to_bytes(self) -> bytes:
        payload = {
            "schema_version": SYMBOL_SNAPSHOT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "node_ids": {str(identifier): value for identifier, value in sorted(self.node_ids.items())},
            "opcode_ids": sorted(set(self.opcode_ids)),
            "symbol_ids": sorted(set(self.symbol_ids)),
            "key_ids": sorted(set(self.key_ids)),
            "atom_ids": sorted(set(self.atom_ids)),
        }
        return _pack_binary(SYMBOLS_MAGIC, payload)


def _encode_value(value: object, lexicon: MachineLexicon, used_key_ids: set[int], used_atom_ids: set[int]) -> list[object]:
    if value is None:
        return ["n"]
    if isinstance(value, bool):
        return ["b", int(value)]
    if isinstance(value, int):
        return ["i", value]
    if isinstance(value, float):
        return ["f", value]
    if isinstance(value, str):
        atom_id = lexicon.add_atom(value)
        used_atom_ids.add(atom_id)
        return ["a", atom_id]
    if isinstance(value, list):
        return ["l", [_encode_value(item, lexicon, used_key_ids, used_atom_ids) for item in value]]
    if isinstance(value, dict):
        items: list[list[object]] = []
        for key, item in sorted(((str(k), v) for k, v in value.items()), key=lambda entry: entry[0]):
            key_id = lexicon.add_key(key)
            used_key_ids.add(key_id)
            items.append([key_id, _encode_value(item, lexicon, used_key_ids, used_atom_ids)])
        return ["d", items]
    raise TypeError(f"Unsupported machine-code value: {type(value)!r}")


def _decode_value(encoded: list[object], keys: dict[int, str], atoms: dict[int, str]) -> object:
    tag = str(encoded[0])
    if tag == "n":
        return None
    if tag == "b":
        return bool(encoded[1])
    if tag == "i":
        return int(encoded[1])
    if tag == "f":
        return float(encoded[1])
    if tag == "a":
        return atoms[int(encoded[1])]
    if tag == "l":
        return [_decode_value(item, keys, atoms) for item in list(encoded[1])]
    if tag == "d":
        return {keys[int(key_id)]: _decode_value(value, keys, atoms) for key_id, value in list(encoded[1])}
    raise ValueError(f"Unsupported machine-code tag: {tag}")


def load_or_create_lexicon(path: str | Path) -> MachineLexicon:
    target = Path(path)
    if not target.exists():
        return MachineLexicon.empty()
    return MachineLexicon.from_bytes(target.read_bytes())


def save_lexicon(path: str | Path, lexicon: MachineLexicon) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(lexicon.to_bytes())
    return target


def encode_machine_code(language_document: dict[str, object], lexicon: MachineLexicon) -> tuple[bytes, bytes]:
    nodes = list(dict(language_document.get("plan", {})).get("nodes", []))
    operation_schemas = dict(language_document.get("operation_schemas", {}))
    inventions = list(language_document.get("inventions", []))

    node_ids = _NodeTable()
    used_opcode_ids: set[int] = set()
    used_symbol_ids: set[int] = set()
    used_key_ids: set[int] = set()
    used_atom_ids: set[int] = set()

    encoded_nodes: list[list[object]] = []
    for node in nodes:
        opcode_id = int(node["op_code"])
        used_opcode_ids.add(opcode_id)
        input_ids = [lexicon.add_symbol(symbol) for symbol in list(node.get("inputs", []))]
        output_ids = [lexicon.add_symbol(symbol) for symbol in list(node.get("outputs", []))]
        state_ref_ids = [lexicon.add_symbol(symbol) for symbol in list(node.get("state_refs", []))]
        used_symbol_ids.update(input_ids)
        used_symbol_ids.update(output_ids)
        used_symbol_ids.update(state_ref_ids)
        execution_mode_id = lexicon.add_atom(str(node.get("execution_mode", "bulk")))
        used_atom_ids.add(execution_mode_id)
        encoded_nodes.append(
            [
                node_ids.add(str(node["node_id"])),
                opcode_id,
                input_ids,
                output_ids,
                execution_mode_id,
                _encode_value(dict(node.get("metadata", {})), lexicon, used_key_ids, used_atom_ids),
                _encode_value(dict(node.get("provenance", {})), lexicon, used_key_ids, used_atom_ids),
                state_ref_ids,
                int(bool(node.get("valid", True))),
            ]
        )

    encoded_edges = [[node_ids.add(str(source)), node_ids.add(str(target))] for source, target in list(dict(language_document.get("plan", {})).get("edges", []))]

    encoded_schemas: list[list[object]] = []
    for descriptor in operation_schemas.values():
        opcode_id = int(descriptor["op_code"])
        used_opcode_ids.add(opcode_id)
        signature = dict(descriptor.get("signature", {}))
        input_ids = [lexicon.add_symbol(symbol) for symbol in list(signature.get("inputs", []))]
        output_ids = [lexicon.add_symbol(symbol) for symbol in list(signature.get("outputs", []))]
        used_symbol_ids.update(input_ids)
        used_symbol_ids.update(output_ids)
        description_id = lexicon.add_atom(str(descriptor.get("description", "")))
        used_atom_ids.add(description_id)
        encoded_schemas.append(
            [
                opcode_id,
                input_ids,
                output_ids,
                _encode_value(dict(descriptor.get("machine_metadata", {})), lexicon, used_key_ids, used_atom_ids),
                description_id,
            ]
        )

    encoded_inventions: list[list[object]] = []
    for invention in inventions:
        invention_opcode = int(invention["op_code"])
        used_opcode_ids.add(invention_opcode)
        source_opcode_ids = [int(op_code) for op_code in list(invention.get("source_op_codes", []))]
        used_opcode_ids.update(source_opcode_ids)
        rationale_id = lexicon.add_atom(str(invention.get("rationale", "")))
        used_atom_ids.add(rationale_id)
        encoded_inventions.append(
            [
                invention_opcode,
                source_opcode_ids,
                float(invention.get("score", 0.0)),
                int(bool(invention.get("accepted", False))),
                rationale_id,
                _encode_value(dict(invention.get("metadata", {})), lexicon, used_key_ids, used_atom_ids),
            ]
        )

    run_id_atom = lexicon.add_atom(str(language_document.get("run_id", "")))
    plan_id_atom = lexicon.add_atom(str(dict(language_document.get("plan", {})).get("plan_id", "")))
    used_atom_ids.update({run_id_atom, plan_id_atom})

    payload = {
        "cv": CODE_SCHEMA_VERSION,
        "ri": run_id_atom,
        "pi": plan_id_atom,
        "pn": encoded_nodes,
        "pe": encoded_edges,
        "ps": _encode_value(dict(dict(language_document.get("plan", {})).get("state_bindings", {})), lexicon, used_key_ids, used_atom_ids),
        "pm": _encode_value(dict(dict(language_document.get("plan", {})).get("metadata", {})), lexicon, used_key_ids, used_atom_ids),
        "os": encoded_schemas,
        "iv": encoded_inventions,
        "lm": _encode_value(dict(language_document.get("plan_metadata", {})), lexicon, used_key_ids, used_atom_ids),
    }
    symbols = SymbolSnapshot(
        run_id=str(language_document.get("run_id", "")),
        node_ids=node_ids.to_reverse_dict(),
        opcode_ids=sorted(used_opcode_ids),
        symbol_ids=sorted(used_symbol_ids),
        key_ids=sorted(used_key_ids),
        atom_ids=sorted(used_atom_ids),
    )
    return _pack_binary(CODE_MAGIC, payload), symbols.to_bytes()


def decode_machine_code(code_bytes: bytes, lexicon: MachineLexicon, symbol_bytes: bytes) -> dict[str, object]:
    payload = _unpack_binary(code_bytes, CODE_MAGIC)
    if payload.get("cv") != CODE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported machine code schema version: {payload.get('cv')}")

    symbol_snapshot = SymbolSnapshot.from_bytes(symbol_bytes)
    node_ids = symbol_snapshot.node_ids
    symbols = {identifier: value for value, identifier in lexicon.symbols.items() if identifier in symbol_snapshot.symbol_ids}
    keys = {identifier: value for value, identifier in lexicon.keys.items() if identifier in symbol_snapshot.key_ids}
    atoms = {identifier: value for value, identifier in lexicon.atoms.items() if identifier in symbol_snapshot.atom_ids}

    plan = {
        "plan_id": atoms[int(payload["pi"])],
        "nodes": [
            {
                "node_id": node_ids[int(node[0])],
                "op_code": int(node[1]),
                "inputs": [symbols[int(symbol_id)] for symbol_id in list(node[2])],
                "outputs": [symbols[int(symbol_id)] for symbol_id in list(node[3])],
                "execution_mode": atoms[int(node[4])],
                "metadata": _decode_value(list(node[5]), keys, atoms),
                "provenance": _decode_value(list(node[6]), keys, atoms),
                "state_refs": [symbols[int(symbol_id)] for symbol_id in list(node[7])],
                "valid": bool(node[8]),
            }
            for node in list(payload.get("pn", []))
        ],
        "edges": [[node_ids[int(source)], node_ids[int(target)]] for source, target in list(payload.get("pe", []))],
        "state_bindings": _decode_value(list(payload["ps"]), keys, atoms),
        "metadata": _decode_value(list(payload["pm"]), keys, atoms),
    }

    operation_schemas = {
        str(int(descriptor[0])): {
            "op_code": int(descriptor[0]),
            "signature": {
                "inputs": [symbols[int(symbol_id)] for symbol_id in list(descriptor[1])],
                "outputs": [symbols[int(symbol_id)] for symbol_id in list(descriptor[2])],
            },
            "machine_metadata": _decode_value(list(descriptor[3]), keys, atoms),
            "description": atoms[int(descriptor[4])],
        }
        for descriptor in list(payload.get("os", []))
    }

    inventions = [
        {
            "op_code": int(invention[0]),
            "source_op_codes": [int(opcode) for opcode in list(invention[1])],
            "score": float(invention[2]),
            "accepted": bool(invention[3]),
            "rationale": atoms[int(invention[4])],
            "metadata": _decode_value(list(invention[5]), keys, atoms),
        }
        for invention in list(payload.get("iv", []))
    ]

    return {
        "kind": "symkern.machine_language",
        "schema_version": LANGUAGE_DOCUMENT_SCHEMA_VERSION,
        "plan": plan,
        "operation_schemas": operation_schemas,
        "inventions": inventions,
        "plan_metadata": _decode_value(list(payload["lm"]), keys, atoms),
        "run_id": atoms[int(payload["ri"])],
    }
