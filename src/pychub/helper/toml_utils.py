from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomli
import tomli_w


def load_toml_file(path: str | Path) -> dict[str, Any]:
    """
    Loads and parses a TOML file, returning its content as a dictionary.

    The function reads the contents of the TOML file specified by the path
    and uses the `tomli` module to parse and convert it into a dictionary
    structure. It assumes that the provided file is valid TOML.

    Args:
        path (str | Path): The path to the TOML file to be loaded. Can be
            provided as a string or a `Path` object.

    Returns:
        dict[str, Any]: A dictionary representation of the TOML file.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        PermissionError: If the file cannot be accessed due to permissions.
        tomli.TOMLDecodeError: If the file content is not valid TOML.
    """
    with open(path, "rb") as f:
        return tomli.load(f)


def load_toml_text(text: str) -> dict[str, Any]:
    """
    Parses a TOML formatted string and converts it into a dictionary.

    This function uses the `tomli` library to parse the provided TOML string and
    return a dictionary representation of the data. The function expects a valid
    TOML formatted string as input.

    Args:
        text (str): A string containing TOML formatted data.

    Returns:
        dict[str, Any]: A dictionary representation of the parsed TOML data.
    """
    return tomli.loads(text)


def dump_toml_to_str(data: Mapping[str, Any], indent: int = 2) -> str:
    """
    Converts a given mapping of data into a TOML string with a specified indentation.

    This function takes a mapping of key-value pairs and serializes it into a TOML
    formatted string. An optional indentation level can be specified for a better
    readability of the output.

    Args:
        data (Mapping[str, Any]): The mapping of data to be serialized into TOML format.
        indent (int, optional): The number of spaces to be used for indentation.
            Defaults to 2.

    Returns:
        str: The serialized TOML formatted string.
    """
    return tomli_w.dumps(data, indent=indent)


def dump_toml_to_file(data: Mapping[str, Any], path: str | Path) -> None:
    """
    Write a TOML (Tom's Obvious, Minimal Language) representation of the provided data
    to a specified file path.

    This function converts the provided mapping into a TOML string and writes it
    to the given file path using UTF-8 encoding.

    Args:
        data (Mapping[str, Any]): The data to be serialized into TOML format.
        path (str | Path): The file path where the TOML content will be written.

    Returns:
        None
    """
    Path(path).write_text(dump_toml_to_str(data), encoding="utf-8")
