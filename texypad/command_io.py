"""Portable import/export format for Texypad custom command collections."""
from __future__ import annotations

import json
from typing import Any, Iterable

from texypad.latex_commands import (
    COMMAND_BY_KEY,
    MAX_CUSTOM_COMMANDS,
    CommandSpec,
    validate_custom_command,
)

COMMAND_COLLECTION_FORMAT = "texypad-command-collection"
COMMAND_COLLECTION_VERSION = 1
COMMAND_COLLECTION_FILTER = "Texypad Command Collections (*.texypadcommands);;JSON Files (*.json);;All Files (*)"
MAX_COMMAND_COLLECTION_SIZE = 2 * 1024 * 1024
MAX_FAVOURITES = 500


class CommandCollectionError(ValueError):
    """Raised when an imported command collection is malformed or unsupported."""


def _spec_to_dict(spec: CommandSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "category": spec.category,
        "description": spec.description,
        "template": spec.template,
        "languages": list(spec.languages),
    }


def _parse_custom(values: Iterable[Any]) -> list[CommandSpec]:
    parsed: list[CommandSpec] = []
    keys: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise CommandCollectionError("Every custom command must be an object.")
        try:
            spec = validate_custom_command(
                key=value.get("key"),
                label=value.get("label", ""),
                category=value.get("category", "Custom"),
                description=value.get("description", ""),
                template=value.get("template", ""),
                languages=value.get("languages", ("latex",)),
            )
        except (TypeError, ValueError) as error:
            raise CommandCollectionError(f"Invalid custom command: {error}") from error
        if spec.key in keys:
            continue
        keys.add(spec.key)
        parsed.append(spec)
        if len(parsed) > MAX_CUSTOM_COMMANDS:
            raise CommandCollectionError(f"A collection may contain at most {MAX_CUSTOM_COMMANDS} custom commands.")
    return parsed


def _parse_favourites(values: Iterable[Any], custom_keys: set[str]) -> set[str]:
    valid = set(COMMAND_BY_KEY) | custom_keys
    favourites: set[str] = set()
    for value in values:
        if not isinstance(value, str) or len(value) > 160:
            continue
        if value in valid:
            favourites.add(value)
        if len(favourites) > MAX_FAVOURITES:
            raise CommandCollectionError(f"A collection may contain at most {MAX_FAVOURITES} favourites.")
    return favourites


def build_command_collection(custom_commands: Iterable[CommandSpec], favourites: Iterable[str]) -> dict[str, Any]:
    custom = _parse_custom(_spec_to_dict(spec) for spec in custom_commands)
    custom_keys = {spec.key for spec in custom}
    favourite_set = _parse_favourites(favourites, custom_keys)
    return {
        "format": COMMAND_COLLECTION_FORMAT,
        "version": COMMAND_COLLECTION_VERSION,
        "application": "Texypad",
        "custom_commands": [_spec_to_dict(spec) for spec in custom],
        "favourites": sorted(favourite_set, key=str.casefold),
    }


def parse_command_collection(payload: bytes | str) -> tuple[list[CommandSpec], set[str]]:
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        data = json.loads(text)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise CommandCollectionError("The selected file is not valid UTF-8 JSON.") from error
    if not isinstance(data, dict):
        raise CommandCollectionError("The command collection root must be an object.")
    if data.get("format") != COMMAND_COLLECTION_FORMAT:
        raise CommandCollectionError("This is not a Texypad command collection.")
    if data.get("version") != COMMAND_COLLECTION_VERSION:
        raise CommandCollectionError("This Texypad command collection version is not supported.")
    custom_values = data.get("custom_commands", [])
    favourite_values = data.get("favourites", [])
    if not isinstance(custom_values, list) or not isinstance(favourite_values, list):
        raise CommandCollectionError("The custom_commands and favourites fields must be lists.")
    custom = _parse_custom(custom_values)
    favourites = _parse_favourites(favourite_values, {spec.key for spec in custom})
    return custom, favourites
