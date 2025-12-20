from __future__ import annotations

from packaging.tags import Tag
from packaging.utils import canonicalize_name, parse_wheel_filename

from pychub.package.domain.compatibility_model import WheelKey, Pep691Metadata
from pychub.package.lifecycle.plan.compatibility.compatibility_evaluator import evaluate_compatibility

# Opinionated ranking policy.
# Interpreter: prefer generic "py" tags over CPython-specific "cp".
INTERP_TYPE_ORDER = ["py", "cp"]

# ABI: prefer pure-python, then stable CPython ABI, then everything else.
ABI_ORDER = ["none", "abi3"]

# Platform: Linux-only worldview (plus "any").
PLATFORM_PREFIX_ORDER = ["any", "manylinux", "musllinux"]

ScoreKey = tuple[int, int, int, str]


def _rank_by_order(value: str, order: list[str]) -> int:
    """
    Ranks a given value based on its position in a predefined order.

    The function attempts to find the index of `value` in the given `order` list. If
    the `value` is not found in the `order`, it returns the length of the `order`
    list, effectively ranking the value as the lowest priority.

    Args:
        value (str): The value to be ranked.
        order (list[str]): A list of strings defining the priority order. The index
            of the value in this list determines its rank.

    Returns:
        int: The rank of the value based on the provided order. If the value is not
        found, the returned rank is the length of the order list.
    """
    try:
        return order.index(value)
    except ValueError:
        return len(order)


def _rank_by_prefix(value: str, prefixes: list[str]) -> int:
    """
    Ranks a given string value based on its presence or match with a list of prefixes.

    The ranking is determined by the position of a prefix in the list that either fully matches
    or partially matches (as a starting substring) the given value. If no match is found, the
    returned rank corresponds to the size of the prefix list.

    Args:
        value (str): The string value to be ranked against the list of prefixes.
        prefixes (list[str]): A list of prefix strings used to determine the rank of the value.

    Returns:
        int: The rank of the given value. A lower rank indicates a closer match, with the
        index in the prefix list being the rank. Returns a rank equal to the length of the
        prefix list if no match is found.
    """
    for i, p in enumerate(prefixes):
        if value == p or value.startswith(p):
            return i
    return len(prefixes)


def _interp_type(label: str) -> str:
    """
    Determines and extracts the leading alphabetic portion of a given string.

    This function iterates through the input string until a non-alphabetic character is
    encountered, returning the portion of the string composed solely of alphabetic
    characters at its beginning.

    Args:
        label (str): The input string from which to extract the initial alphabetic
            portion.

    Returns:
        str: The leading alphabetic portion of the input string.
    """
    i = 0
    while i < len(label) and label[i].isalpha():
        i += 1
    return label[:i]


def _score(t: Tag) -> ScoreKey:
    """
    Computes a scoring tuple for a given tag based on specific ranking criteria.

    The scoring mechanism involves ranking the interpreter type, ABI, and platform of the tag using
    predefined orders and prefix-based rankings. It provides a way to assess and rank tags for further
    processing or comparison.

    Args:
        t (Tag): The tag object containing attributes such as interpreter type, ABI, and platform.

    Returns:
        tuple[int, int, int, str]: A tuple of ranks and the string representation of the tag. The
        tuple consists of the following elements:
            - Interpreter rank (int): Ranking based on the order of the interpreter type.
            - ABI rank (int): Ranking based on the order of ABI.
            - Platform rank (int): Ranking based on the order or prefix match of the platform.
            - Tag string (str): The string representation of the given tag.
    """
    interp_rank = _rank_by_order(_interp_type(t.interpreter), INTERP_TYPE_ORDER)
    abi_rank = _rank_by_order(t.abi, ABI_ORDER)
    platform_rank = _rank_by_prefix(t.platform, PLATFORM_PREFIX_ORDER)
    return interp_rank, abi_rank, platform_rank, str(t)


def choose_wheel_tag(filename: str, name: str, version: str) -> str:
    """
    Selects the most compatible tag from a given wheel file based on the specified package name
    and version. This function validates the wheel filename and ensures its compatibility with
    the provided package details.

    Args:
        filename: The name of the wheel file to parse and evaluate.
        name: The canonicalized package name to validate against the wheel file.
        version: The version of the package to validate against the wheel file.

    Returns:
        The string representation of the most compatible tag with the given package's
        name and version.

    Raises:
        ValueError: If the wheel filename is invalid or does not match the provided name or
            version.
        ValueError: If there are no compatible tags for the given wheel file.
    """
    parsed_name, parsed_version, _, tagset = parse_wheel_filename(filename)
    if (canonicalize_name(str(parsed_name)) != canonicalize_name(name)
            or str(parsed_version) != str(version)):
        raise ValueError(f"Invalid wheel filename: {filename}")

    compatible = [t for t in tagset if evaluate_compatibility(tag_str=str(t))]
    if not compatible:
        raise ValueError("No compatible tags")

    return str(min(compatible, key=_score))


def _tag_from_str(tag_str: str) -> Tag:
    """
    Parses a string representation of a tag into a Tag object.

    This function takes a string representation of a tag formatted as "i-a-p", where
    "i", "a", and "p" are individual components separated by hyphens, and converts
    it into a Tag object by splitting the string into its respective components.

    Args:
        tag_str (str): The string representation of the tag, formatted as "i-a-p".

    Returns:
        Tag: An instance of the Tag object created from the parsed components of
        the string.
    """
    i, a, p = tag_str.split("-", 2)
    return Tag(i, a, p)


def resolve_uri_for_wheel_key(wheel_key: WheelKey, candidate_meta: Pep691Metadata) -> str | None:
    """
    Resolves the appropriate URI for a given wheel key and metadata.

    This function determines the most suitable URI for a `.whl` file based
    on the provided wheel key and metadata. It evaluates all available
    candidates under the metadata, scoring them based on compatibility and
    other factors, and returns the URI of the best-matched candidate.
    If no suitable candidate is found, it returns `None`.

    Args:
        wheel_key: The wheel key containing the name and version of the wheel
            to be matched.
        candidate_meta: The metadata including the list of available files and
            their associated properties for selection.

    Returns:
        The URI of the best-matched `.whl` file as a string, or `None` if no
        suitable file is found.
    """
    candidates: list[tuple[tuple[ScoreKey, str], str]] = []
    # candidates = [ ((score_key, filename), url), ... ]

    for file_meta in candidate_meta.files:
        if file_meta.yanked or not file_meta.filename.endswith(".whl"):
            continue

        try:
            chosen_tag_str = choose_wheel_tag(
                filename=file_meta.filename,
                name=wheel_key.name,
                version=wheel_key.version)
        except ValueError:
            continue

        score_key: ScoreKey = _score(_tag_from_str(chosen_tag_str))
        candidates.append(((score_key, file_meta.filename), file_meta.url))

    return None if not candidates else min(candidates, key=lambda c: c[0])[1]

