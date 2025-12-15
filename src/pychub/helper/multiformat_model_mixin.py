from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import Any

from typing_extensions import Self

from pychub.helper.toml_utils import dump_toml_to_str
from pychub.helper.toml_utils import load_toml_text


def _normalize(value: Any) -> Any:
    """
    Normalizes various types of Python objects to consistent, standardized forms.

    This function processes input values of diverse types and converts them into a
    normalized representation. The normalization includes handling Path objects,
    Enums, mappings, sets, frozensets, lists, and tuples. It recursively processes
    nested structures when applicable, ensuring uniformity across all supported
    data types.

    Args:
        value (Any): The input value to be normalized. It supports various types
            such as Path, Enum, Mapping, sets, frozensets, lists, and tuples.

    Returns:
        Any: The normalized form of the input value. The output will be:
            - A POSIX string for Path types.
            - The stored value for Enum types.
            - A sorted dictionary for Mapping types, with stringified keys.
            - A sorted list for sets and frozensets, with normalized elements.
            - A list for list or tuple input, with elementwise normalization.
            - The original non-supported type if no specific transformation is
              applied.
    """
    # Path -> POSIX string
    match value:
        case Path():
            return value.as_posix()

        case Enum():
            return value.value

        case Mapping():
            return {
                str(k): _normalize(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }

        case set() | frozenset():
            return sorted(_normalize(v) for v in value)

        case list() | tuple():
            return [_normalize(v) for v in value]

        case _:
            return value


class MultiformatSerializableMixin:
    """
    A mixin to add multi-format serialization support for custom objects.

    This mixin provides functionality to serialize an object's data into different
    formats, including JSON, YAML, and TOML. It also offers utilities for generating
    hashes, summaries, and customizable mapping transformations. Subclasses must
    implement specific methods to use this mixin effectively.
    """

    def mapping_hash(self) -> str:
        """
        Generates a SHA-512 hash based on the normalized representation of a mapping.

        This method computes a cryptographic hash by first normalizing the mapping
        through a specified normalization process. It serializes the normalized
        structure to JSON with specific settings (sorted keys and custom separators)
        to ensure consistent hash computation. Finally, it generates a SHA-512
        digest of the serialized payload.

        Returns:
            str: The hexadecimal representation of the SHA-512 hash.
        """
        import hashlib
        import json

        normalized = _normalize(self.to_mapping())  # as before
        payload = (
            json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"))
            .encode("utf-8"))

        return hashlib.new("sha512", payload).hexdigest()

    def to_mapping(self, *args, **kwargs) -> Mapping[str, Any]:
        """
        Converts data into a mapping-like structure.

        This method is intended to be implemented by subclasses that use the
        MultiformatSerializableMixin. It must provide the logic for serializing
        data into a dictionary-like format.

        Note:
            For container-like objects (e.g., logical lists), this method should
            still return a mapping. A common pattern is:

                {"items": [item.to_mapping() for item in self.items]}

        Args:
            *args: Variable length argument list for any additional parameters
                required for the conversion.
            **kwargs: Arbitrary keyword arguments for any extra options
                during the conversion.

        Returns:
            Mapping[str, Any]: A dictionary-like structure representing the object's data.

        Raises:
            NotImplementedError: Raised when subclasses do not implement this
                method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement to_mapping() "
            "to use MultiformatSerializableMixin serialization.")

    def to_json(self, *, indent=2) -> str:
        """
        Converts the object's data to a JSON string.

        This method serializes the return value of the `to_mapping` method into a
        JSON-formatted string. It ensures non-ASCII characters are preserved, and
        the output is both indented and sorted by keys for better readability.

        Args:
            indent (int): Number of spaces to use as the indentation level in the
                generated JSON string. Defaults to 2.

        Returns:
            str: A string containing the JSON representation of the object's data.
        """
        import json
        return json.dumps(self.to_mapping(), ensure_ascii=False, indent=indent, sort_keys=True)

    def to_yaml(self, *, indent=2) -> str:
        """
        Converts the object's data to a YAML string representation.

        This method utilizes the PyYAML library to serialize the object's data,
        as obtained by its `to_mapping` method, into a YAML formatted string.
        It allows customization of the indentation level of the resulting YAML
        content.

        Args:
            indent (int): The number of spaces to use for indentation in the
                YAML output. Defaults to 2.

        Returns:
            str: The YAML string representation of the object's data.

        Raises:
            RuntimeError: If the PyYAML library is not installed on the system.
        """
        try:
            import yaml
        except ImportError:
            raise RuntimeError("PyYAML not installed")
        return yaml.safe_dump(self.to_mapping(), sort_keys=True, allow_unicode=True, indent=indent)

    def to_toml(self, *, indent=2) -> str:
        """
        Converts the instance's data to a TOML string.

        This method converts the object's data representation into a formatted TOML
        string. The data is first sorted in an order determined by the `sort_dict`
        function. The sorting ensures that dictionaries and lists are recursively
        ordered. After sorting, the data is serialized into a TOML string.

        Args:
            indent (int): Number of spaces to be used for indentation in the resulting
                TOML string.

        Returns:
            str: A TOML-formatted string representation of the object's data.
        """

        def sort_dict(obj):
            match obj:
                case dict():
                    return {k: sort_dict(obj[k]) for k in sorted(obj)}
                case list():
                    return [sort_dict(item) for item in obj]
                case _:
                    return obj

        sorted_mapping = sort_dict(self.to_mapping())
        return dump_toml_to_str(sorted_mapping, indent)

    def serialize(self, *, fmt='json', indent=2) -> str:
        """
        Serializes the object to a string in the specified format.

        This function allows exporting the object to a string representation
        in one of the supported formats: JSON, YAML, or TOML. The format
        is specified using the `fmt` parameter. Indentation for JSON and
        YAML formats can be customized using the `indent` parameter.

        Args:
            fmt (str): The format to serialize the object to. Supported formats
                are 'json', 'yaml', and 'toml'. Defaults to 'json'.
            indent (int): The number of spaces to use for indentation in JSON
                and YAML formatted output. Defaults to 2.

        Returns:
            str: The serialized representation of the object in the specified format.

        Raises:
            ValueError: If the specified format is not recognized or supported.
        """
        match fmt:
            case 'json':
                return self.to_json(indent=indent)
            case 'yaml':
                return self.to_yaml(indent=indent)
            case 'toml':
                return self.to_toml()
            case _:
                raise ValueError(f"unrecognized format: {fmt}")

    def flat_summary(
            self,
            first_fields=("timestamp",),
            last_fields=(),
            sep=" | ",
            exclude=(),
            include_empty=False):
        """
        Generate a flat summary representation of the object's data.

        The method retrieves the object's mapping representation, organizes its keys
        according to specified first and last fields while ordering the rest alphabetically,
        and creates a flat string representation of the data. Empty or None values are excluded
        unless explicitly included.

        Args:
            first_fields (tuple): A tuple of keys that should appear first in the summary,
                in the specified order.
            last_fields (tuple): A tuple of keys that should appear last in the summary,
                in the specified order.
            sep (str): The string used to separate different items in the summary.
            exclude (tuple): A tuple of keys that should be excluded from the summary.
            include_empty (bool): Whether to include empty fields (e.g., None, empty lists,
                dictionaries, or strings) in the summary.

        Returns:
            str: A flat string representation of the object's data.
        """
        mapping = self.to_mapping()
        all_keys = set(mapping.keys()) - set(exclude)
        first = [f for f in first_fields if f in all_keys]
        last = [f for f in last_fields if f in all_keys and f not in first]
        middle = sorted(all_keys - set(first) - set(last))
        ordered_keys = list(first) + middle + list(last)

        items = []
        for k in ordered_keys:
            v = mapping[k]
            # Filter if not including empty/None
            if not include_empty and (
                    v is None or v == "" or
                    (isinstance(v, (list, tuple, set, dict))
                     and not v)):
                continue

            if isinstance(v, (datetime, date)):
                v_str = v.isoformat(timespec='seconds') if isinstance(v, datetime) else v.isoformat()
            elif k.lower() == "payload" and isinstance(v, dict):
                try:
                    import json
                    v_str = json.dumps(v, separators=(',', ':'))
                except Exception:
                    v_str = repr(v)
            elif isinstance(v, dict):
                v_str = "{" + ", ".join(f"{kk}: {repr(v[kk])}" for kk in v.keys()) + "}"
            elif isinstance(v, (list, tuple, set)):
                v_str = "[" + ", ".join(repr(x) for x in v) + "]"
            else:
                v_str = str(v)
            items.append(f"{k}: {v_str}")
        return sep.join(items)

    def __str__(self):
        return self.flat_summary()


class MultiformatDeserializableMixin:
    """
    A mixin class that provides deserialization capabilities from multiple formats like JSON, YAML, and TOML.

    Details:
        This mixin enables subclasses to deserialize data from different text-based serialization formats
        into Python objects. Subclasses must implement the `from_mapping` method to specify how to build
        an instance from a mapping. The mixin also provides hook methods to allow customizing the
        deserialization steps, such as preprocessing mappings or postprocessing instances.
    """

    # ---- core contract ----

    @classmethod
    def from_mapping(cls: type[Self], mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        A factory method responsible for creating an instance of the class from a given mapping. This method is intended to
        be implemented by subclasses.

        Args:
            mapping (Mapping[str, Any]): A collection or object that maps strings to any type of value.
            **_ (Any): Additional keyword arguments for extensibility in derived implementations.

        Raises:
            NotImplementedError: Raised if this base method is not overridden by a subclass providing the specific
            implementation.
        """
        raise NotImplementedError(
            f"{cls.__name__} must implement from_mapping(mapping, **kwargs) "
            "to use MultiformatDeserializableMixin.")

    # ---- public entrypoints ----

    @classmethod
    def deserialize(cls: type[Self], text: str, *, fmt: str = "json", **context: Any) -> Self:
        """
        Deserializes a given text representation into an instance of the class.

        This method processes the text input based on the specified format, ensuring
        the data is parsed, coerced into a mapping structure, and optionally preprocessed
        before creating an instance of the class. Finally, a postprocessing step is
        performed on the created instance to finalize its state.

        Args:
            text (str): The string representation of the object to be deserialized.
            fmt (str, optional): The format in which the input text is given. Defaults to "json".
            **context (Any): Additional context or parameters that might be necessary
                for parsing or instantiation.

        Returns:
            Self: An instance of the class created using the deserialized data.
        """
        raw = cls._parse_text(text, fmt=fmt, path=None, **context)
        mapping = cls._coerce_root_mapping(raw, fmt=fmt, path=None, **context)
        mapping = cls._preprocess_mapping(mapping, fmt=fmt, path=None, **context)
        inst = cls.from_mapping(mapping, **context)
        return cls._postprocess_instance(inst, fmt=fmt, path=None, **context)

    @classmethod
    def from_json(cls: type[Self], text: str, **context: Any) -> Self:
        """
        Creates an instance of the class by deserializing a JSON-formatted string.

        This class method processes a JSON string to create and return an instance
        of the class. The deserialization is performed using the provided JSON string
        and any additional context-specific arguments required for customization.

        Args:
            text (str): The JSON string to be deserialized.
            **context (Any): Additional context or parameters to be passed for
                deserialization.

        Returns:
            Self: An instance of the class initialized with data from the JSON string.
        """
        return cls.deserialize(text, fmt="json", **context)

    @classmethod
    def from_yaml(cls: type[Self], text: str, **context: Any) -> Self:
        """
        Creates an instance of the class by deserializing a YAML string.

        This method is a class method that takes a YAML string and optional
        additional context as input. It then deserializes the string into an
        instance of the class.

        Args:
            text: The YAML string to be deserialized.
            **context: Arbitrary keyword arguments that may provide additional
                context or configuration for the deserialization.

        Returns:
            An instance of the class (`T`) created using the deserialized data.
        """
        return cls.deserialize(text, fmt="yaml", **context)

    @classmethod
    def from_toml(cls: type[Self], text: str, **context: Any) -> Self:
        """
        Creates an instance of the class by deserializing data in TOML format.

        This method is a class method that allows creating an instance of the class
        by providing a TOML-encoded input and optional context parameters for
        deserialization.

        Args:
            text (str): The TOML-formatted string to be deserialized into an
                instance of the class.
            **context (Any): Additional context parameters that may be utilized
                during the deserialization process.

        Returns:
            Self: An instance of the class created by deserializing the provided
                TOML-formatted data.
        """
        return cls.deserialize(text, fmt="toml", **context)

    @classmethod
    def from_file(cls: type[Self], path: str | Path, fmt: str | None = None, **context: Any) -> Self:
        """
        Creates an instance of the class from a file specified by the provided path.

        This method loads text from the given file path, determines the format if not
        explicitly provided, parses the text, coerces it into an internal mapping, and
        preprocesses it before creating an instance. After creating the instance,
        postprocessing is applied before returning the final object.

        Args:
            path (str | Path): A string or `Path` object specifying the file's path.
            fmt (str | None): The format of the file content. If None, the format will
                be inferred automatically from the file's suffix.
            **context (Any): Additional context data or configuration that might
                influence the parsing and creation process.

        Returns:
            Self: An instance of the class.
        """
        p = Path(path)
        text = cls._load_text(p, **context)
        fmt = fmt or cls._infer_format_from_suffix(p)
        raw = cls._parse_text(text, fmt=fmt, path=p, **context)
        mapping = cls._coerce_root_mapping(raw, fmt=fmt, path=p, **context)
        mapping = cls._preprocess_mapping(mapping, fmt=fmt, path=p, **context)
        inst = cls.from_mapping(mapping, **context)
        return cls._postprocess_instance(inst, fmt=fmt, path=p, **context)

    # ---- overridable hooks ----

    @classmethod
    def _load_text(cls, path: Path, **_: Any) -> str:
        """
        Loads text from a given file path.

        This method reads the content of a file located at the given `path` and
        returns it as a string. The file is assumed to be encoded in UTF-8.

        Args:
            path (Path): The path to the file from which text will be loaded.
            **_ (Any): Additional keyword arguments that are ignored.

        Returns:
            str: The content of the file as a string.
        """
        return path.read_text(encoding="utf-8")

    @classmethod
    def _infer_format_from_suffix(cls, path: Path) -> str:
        """
        Infers the file format based on the suffix of the given file path.

        This method analyzes the suffix of the file to determine the format.
        Supported formats are JSON, YAML, and TOML. If the suffix does not match
        any of the supported formats, it raises a ValueError.

        Args:
            path (Path): The file path to infer the format from.

        Returns:
            str: The inferred format as a string ("json", "yaml", or "toml").

        Raises:
            ValueError: If the file suffix is not recognized as a supported format.
        """
        suffix = path.suffix.lower()
        match suffix:
            case ".json":
                return "json"
            case ".yaml" | ".yml":
                return "yaml"
            case ".toml":
                return "toml"
            case _:
                raise ValueError(f"Cannot infer format from extension {suffix!r}")

    @classmethod
    def _parse_text(cls, text: str, *, fmt: str, path: Path | None, **_: Any) -> Any:
        """
        Parses text content into a data structure based on the specified format.

        This method supports parsing text content in JSON, YAML, or TOML format.
        If the format specified is unsupported or invalid, it raises an
        appropriate exception.

        Args:
            text (str): The text content to be parsed.
            fmt (str): The format of the text content. Supported values are
                "json", "yaml", and "toml". Case is ignored.
            path (Path | None): Reserved for potential future use, currently not utilized.
            **_ (Any): Additional keyword parameters, ignored.

        Returns:
            Any: The parsed data structure derived from the input text.

        Raises:
            RuntimeError: If the format is "yaml" and the PyYAML library is not installed.
            ValueError: If the format is unrecognized or unsupported.
        """
        fmt = fmt.lower()
        match fmt:
            case "json":
                import json
                return json.loads(text or "{}")
            case "yaml":
                try:
                    import yaml
                except ImportError:
                    raise RuntimeError("PyYAML not installed")
                return next(iter(yaml.safe_load_all(text)), None) or {}
            case "toml":
                return load_toml_text(text or "")
            case _:
                raise ValueError(f"unrecognized format: {fmt!r}")

    @classmethod
    def _coerce_root_mapping(
            cls,
            raw: Any,
            *,
            fmt: str,
            path: Path | None,
            **_: Any) -> Mapping[str, Any]:
        """
        Coerces a given raw input into a mapping type if valid.

        This method ensures that the provided `raw` object is a mapping type. If it is
        not, a TypeError will be raised. It is typically used to validate and process
        data inputs.

        Args:
            raw: The input to be validated as a mapping type.
            fmt: A string representing the format or source of the input,
                used for error reporting.
            path: A Path object or None indicating the filepath associated with the
                input, used for error reporting.
            **_: Additional keyword arguments that are ignored during processing.

        Returns:
            Mapping[str, Any]: The validated input as a mapping type.

        Raises:
            TypeError: If the provided input is not a mapping type.
        """
        if isinstance(raw, Mapping):
            return raw
        raise TypeError(
            f"{cls.__name__} expected top-level mapping, got {type(raw)!r} "
            f"from {fmt} {str(path) if path else '<inline>'}")

    @classmethod
    def _preprocess_mapping(
            cls,
            mapping: Mapping[str, Any],
            *,
            fmt: str,
            path: Path | None,
            **_: Any) -> Mapping[str, Any]:
        """
        Preprocesses a given mapping according to specific requirements. This method can be overridden
        in subclasses to handle unique preprocessing cases. By default, it passes the mapping through
        unchanged.

        Args:
            mapping (Mapping[str, Any]): The input mapping to preprocess.
            fmt (str): The format to be applied during preprocessing.
            path (Path | None): The file path relevant to the preprocessing, if any.
            **_ (Any): Additional arguments that might be passed but are ignored by default.

        Returns:
            Mapping[str, Any]: The processed mapping, identical to the input by default.
        """
        # default: pass-through; override in unique cases
        return mapping

    @classmethod
    def _postprocess_instance(
            cls,
            inst: Self,
            *,
            fmt: str,
            path: Path | None,
            **_: Any) -> Self:
        """
        Post-process an instance after its creation. This method performs any
        necessary modifications, validations, or derivations on the instance
        before returning it. By default, this is a pass-through operation, but
        it can be overridden in subclasses to implement custom behavior.

        Processes the given instance by setting the 'source_description' attribute
        based on the provided format and path if the attribute exists and is
        currently empty or falsey. This operation does not modify the value if it
        already holds a truthy value.

        If a subclass overrides this method and still wants the default behavior,
        it can call super()._postprocess_instance(...) and then apply additional
        logic.

        Args:
            inst: The instance to be post-processed.
            fmt: A string representing the format that may guide the
                post-processing operations.
            path: An optional path of type Path which may be used for
                additional processing context.
            **_: Additional keyword arguments that might be absorbed without
                explicit use in the default implementation.

        Returns:
            The post-processed instance of the same type as the input.
        """
        # Soft opt-in: only touch if the attribute exists and is empty/falsey
        if hasattr(inst, "source_description"):
            current = getattr(inst, "source_description", None)
            if not current:
                if path is not None:
                    desc = f"{fmt}:{path}"
                else:
                    desc = f"{fmt}:<inline>"
                try:
                    setattr(inst, "source_description", desc)
                except Exception:
                    # Don't blow up if the subclass does something naughty (oh, behave!)
                    pass

        return inst


class MultiformatModelMixin(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    pass
