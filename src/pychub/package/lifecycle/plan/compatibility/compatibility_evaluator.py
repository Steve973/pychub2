import re
from collections.abc import Mapping

from packaging.tags import Tag, parse_tag
from packaging.version import Version

from pychub.package.domain.compatibility_model import AbiValuesSpec, PlatformOSSpec, PlatformFamilySpec
from pychub.package.packaging_context_vars import current_packaging_context

# ---------------------------------------------------------------------------
# Helpers for platform tag parsing
# ---------------------------------------------------------------------------

# Example tags: manylinux_2_17_x86_64, musllinux_1_1_aarch64, macosx_11_0_arm64, win_amd64
PLATFORM_RE = re.compile(
    r"^(?P<flavor>[a-zA-Z0-9]+)"
    r"(?:_(?P<major>\d+)_(?P<minor>\d+))?"
    r"(?:_(?P<arch>[A-Za-z0-9_]+))?$")


def _split_platform_tag(platform: str) -> tuple[str, str | None, str | None]:
    """
    Splits a platform tag into its respective components: flavor, version, and architecture.

    This function uses a regular expression to parse the given platform tag string. It extracts the
    flavor, version (constructed by combining major and minor components if both exist), and the
    architecture components of the platform tag. If the input platform string does not match the
    expected pattern, it returns the entire platform tag as the flavor, with version and architecture
    set to None.

    Args:
        platform (str): The platform tag string to be parsed.

    Returns:
        Tuple[str, str | None, str | None]: A 3-tuple containing:
            - flavor (str): The flavor of the platform, derived from the tag.
            - version (str | None): The combined major and minor components as a single string,
              or None if either of them is missing.
            - arch (str | None): The architecture part of the platform tag, or None if it is not present.
    """
    m = PLATFORM_RE.match(platform)
    if not m:
        return platform, None, None

    flavor = m.group("flavor")
    major = m.group("major")
    minor = m.group("minor")
    arch = m.group("arch")
    version = f"{major}_{minor}" if major and minor else None
    return flavor, version, arch


def _parse_glibc_like_version(v: str) -> tuple[int, int]:
    """
    Parses a version string resembling glibc-like versions into major and minor version components.

    This function takes a version string, normalizes it, and extracts the major and minor versions
    as integers. If the version string contains only a major version (e.g., "3"), it assumes a minor
    version of "0". Unexpected formatting of the version string will not raise an error unless it
    prevents splitting or conversion to integers.

    Args:
        v (str): The version string to parse. It is expected to be in the format of "major.minor" or
            just "major".

    Returns:
        Tuple[int, int]: A tuple containing the major and minor versions as integers.
    """
    v = v.strip()
    normalized = v.replace(".", "_")
    try:
        major_s, minor_s = normalized.split("_", 1)
    except ValueError:
        # Bare major -> treat as ".0"
        major_s, minor_s = normalized, "0"
    return int(major_s), int(minor_s)


# ---------------------------------------------------------------------------
# Helpers for Python versions / ABI
# ---------------------------------------------------------------------------


def _parse_python_version_label(label: str) -> tuple[int, int] | None:
    """
    Extracts a (major, minor) Python version from a version label.

    This function identifies and parses version labels representing Python versions
    into a tuple of major and minor version numbers. It supports formats such as
    '3.11', 'cp311', 'cp310', 'py311', 'py39', and 'py3'. Labels with only major
    version numbers (e.g., 'py3') are interpreted with a minor version of 0. If no
    valid version can be determined from the label, the function returns None.

    Args:
        label (str): The label to extract the version from. This could be in various
            formats such as '3.11', 'cp311', or 'py3'.

    Returns:
        Tuple[int, int] | None: A tuple of (major, minor) version numbers if the
        label can be parsed, otherwise None.
    """
    s = label.strip()

    # plain "3.11"
    m = re.match(r"^(?P<maj>\d+)\.(?P<min>\d+)$", s)
    if m:
        return int(m.group("maj")), int(m.group("min"))

    # trailing digits in things like 'cp311', 'py3'
    m = re.search(r"(\d+)$", s)
    if not m:
        return None

    digits = m.group(1)
    length = len(digits)
    if length == 1:
        # '3' -> (3, 0)
        return int(digits), 0
    if length == 2:
        # '39' -> 3.9
        return int(digits[0]), int(digits[1])
    if length == 3:
        # '311' -> 3.11
        return int(digits[0]), int(digits[1:])

    return None


def _is_debug_abi(abi: str) -> bool:
    """
    Determines if the given ABI (Application Binary Interface) corresponds to a
    debug build configuration.

    This function analyzes the ABI string and checks whether it ends with a
    character 'd', which typically denotes a debug build.

    Args:
        abi (str): The ABI string to evaluate.

    Returns:
        bool: True if the given ABI corresponds to a debug build, otherwise False.
    """
    return abi.endswith("d")


def _is_stable_abi(abi: str) -> bool:
    """
    Determines whether the provided ABI (Application Binary Interface) string represents
    a stable ABI.

    An ABI is considered stable if it starts with the prefix "abi" followed by numeric
    characters, or if the ABI is explicitly "none".

    Args:
        abi (str): The ABI string to be checked for stability.

    Returns:
        bool: True if the ABI is stable, False otherwise.
    """
    if abi == "none":
        return True
    return abi.startswith("abi") and abi[3:].isdigit()


def _accept_universal_interpreter(interpreter: str) -> bool:
    build_plan = current_packaging_context.get().build_plan
    spec = build_plan.compatibility_spec
    if spec is None:
        raise RuntimeError("CompatibilitySpec not initialized")
    if not spec.python_versions_spec.accept_universal:
        return False
    for mv in spec.accepted_python_major_versions:
        if f"py{mv}" in interpreter:
            return True
    return False


def _accept_universal_abi(abi: str) -> bool:
    return abi == "none"


def _accept_universal_platform(platform: str) -> bool:
    return platform == "any"


def _accept_universal_tag(interpreter: str, abi: str, platform: str) -> bool:
    return (_accept_universal_interpreter(interpreter)
            and _accept_universal_abi(abi)
            and _accept_universal_platform(platform))


# ---------------- Python interpreter ----------------

def _accept_interpreter(interpreter: str) -> bool:
    """
    Checks if the provided interpreter part of a tag (e.g., 'cp311', 'py3') is accepted
    according to the PythonVersionsSpec.

    The method applies several rules to validate the interpreter:
      1. Explicit excludes: Rejects interpreters explicitly listed in `spec.excludes`.
      2. Specific-only rule: If `specific_only` is True, only interpreters explicitly
         listed in `spec.specific` are allowed.
      3. Additive specifics: If `specific_only` is False, interpreters explicitly listed
         in `spec.specific` are always allowed.
      4. Universal form ('pyX'): Allows 'pyX' universal interpreters (major Python versions),
         if `accept_universal` is True and the major version lies within the specified bounds.
      5. Concrete versions: Interpreters that map to a specific major/minor version
         are allowed if they fall within the specified bounds.

    Unrecognized or unparsable interpreters are always rejected.

    Args:
        interpreter (str): The interpreter label to check (e.g., 'cp311', 'py3').

    Raises:
        RuntimeError: If Python version bounds are not initialized.

    Returns:
        bool: True if the interpreter is accepted, False otherwise.
    """
    build_plan = current_packaging_context.get().build_plan
    spec = build_plan.compatibility_spec
    if spec is None:
        raise RuntimeError("CompatibilitySpec not initialized")
    vspec = spec.python_versions_spec
    bounds = spec.resolved_python_version_range
    if bounds is None:
        raise RuntimeError("Python version bounds not initialized")

    # 1) explicit excludes
    if interpreter in vspec.excludes:
        return False

    # 2) specific_only → pure whitelist
    if vspec.specific_only:
        return interpreter in vspec.specific

    # 3) additive specifics
    if interpreter in vspec.specific:
        return True

    # 4) 'pyX' universal form (single-digit major)
    if _accept_universal_interpreter(interpreter):
        return True

    # 5) everything else must map to a concrete version in-range
    v = _parse_python_version_label(interpreter)
    if v is None:
        # No guessing: if we can't map it, we don't accept it.
        return False

    maj_ver, min_ver = v
    return Version(f"{maj_ver}.{min_ver}") in bounds

# ---------------- ABI ----------------

def _accept_abi(abi: str) -> bool:
    """
    Checks the ABI (Application Binary Interface) part of a tag against specified
    rules defined by the AbiValuesSpec. The function verifies if the provided ABI
    adheres to constraints such as specific inclusion or exclusion rules, and
    Python version compatibility.

    The rules applied are as follows:

    1. Exclude specified ABIs.
    2. If `specific_only` is True:
       - Allow only specified ABI values minus exclusions.
    3. Otherwise:
       - Allow additive specific ABIs.
       - Allow debug ABIs only if `include_debug` is True.
       - Allow stable ABIs (e.g., 'abi3', 'none') only if `include_stable`
         is True and their major version is within Python version bounds.
       - Allow other concrete Python-versioned ABIs (e.g., 'cp311') only if
         they map to a Python version within bounds.
    4. Reject unknown ABIs.

    Args:
        abi (str): The ABI part of the tag (e.g., 'cp311', 'abi3', 'none')
            to be checked against the specification.

    Returns:
        bool: True if the ABI passes the checks and aligns with the specifications,
        otherwise False.

    Raises:
        RuntimeError: If the Python version bounds are not initialized.
    """
    if _accept_universal_abi(abi):
        return True
    build_plan = current_packaging_context.get().build_plan
    spec = build_plan.compatibility_spec
    if spec is None:
        raise RuntimeError("CompatibilitySpec not initialized")
    aspec: AbiValuesSpec = spec.abi_values
    bounds = spec.resolved_python_version_range
    if bounds is None:
        raise RuntimeError("Python version bounds not initialized")

    # 1) excludes
    if abi in aspec.excludes:
        return False

    # 2) specific_only → pure whitelist
    if aspec.specific_only:
        return abi in aspec.specific

    # 3) additive specifics
    if abi in aspec.specific:
        return True

    # 4) debug ABIs
    if _is_debug_abi(abi) and not aspec.include_debug:
        return False

    # 5) stable ABIs
    if _is_stable_abi(abi):
        if not aspec.include_stable:
            return False
        # abiX -> stable ABI for major X
        m = re.search(r"(\d+)$", abi)
        if not m:
            return False
        major = int(m.group(1))
        return any(v_str.startswith(f"{major}.") for v_str in spec.resolved_python_version_list)

    # 6) cpXYZ-style ABIs: must map to a concrete version in-range
    v = _parse_python_version_label(abi)
    if v is None:
        return False

    maj_ver, min_ver = v
    if bounds is not None:
        return Version(f"{maj_ver}.{min_ver}") in bounds
    else:
        return False

# ---------------- Platform ----------------

def _accept_platform(platform: str) -> bool:
    """
    Evaluates whether a given platform string conforms to the platform specifications
    defined under the `PlatformValues`. The function performs a series of checks and rules
    to determine if the platform should be accepted or rejected, based on explicit excludes,
    specific entries, specific-only behavior, and family-based criteria. The evaluation
    is fail-closed unless explicitly allowed through the specifications.

    Args:
        platform (str): The platform tag to be checked, typically formatted as
            'flavor_version_arch' (e.g., 'manylinux_2_17_x86_64').

    Returns:
        bool: True if the platform is accepted according to the specifications,
        False otherwise.
    """
    if _accept_universal_platform(platform):
        return True
    build_plan = current_packaging_context.get().build_plan
    spec = build_plan.compatibility_spec
    if spec is None:
        raise RuntimeError("CompatibilitySpec not initialized")
    platform_specs: Mapping[str, PlatformOSSpec] = spec.platform_values

    # No platform constraints at all -> reject everything by default.
    if not platform_specs:
        return False

    # 1) excludes
    for os_spec in platform_specs.values():
        if platform in os_spec.excludes:
            return False

    # 2) specific_only → whitelist union
    specific_only_specs = [
        os_spec for os_spec in platform_specs.values() if os_spec.specific_only
    ]
    if specific_only_specs:
        whitelist: set[str] = set()
        for os_spec in specific_only_specs:
            whitelist.update(os_spec.specific)
        return platform in whitelist

    # 3) additive specifics
    for os_spec in platform_specs.values():
        if platform in os_spec.specific:
            return True

    # 4) family-based rules
    flavor, version, arch = _split_platform_tag(platform)

    family_spec: PlatformFamilySpec | None = None
    owning_os_spec: PlatformOSSpec | None = None

    for os_spec in platform_specs.values():
        fam = os_spec.families.get(flavor)
        if fam is not None:
            family_spec = fam
            owning_os_spec = os_spec
            break

    if family_spec is None:
        # No OS spec describes this flavor
        return False

    # OS-level arch filter
    if owning_os_spec and owning_os_spec.arches:
        if arch is None or arch not in owning_os_spec.arches:
            return False

    # Family-level version filter (supports '*' as unbounded)
    if (family_spec.min or family_spec.max) and version is None:
        return False

    if version is not None:
        v_tuple = _parse_glibc_like_version(version)

        if family_spec.min and family_spec.min != "*":
            min_v = _parse_glibc_like_version(family_spec.min)
            if v_tuple < min_v:
                return False

        if family_spec.max and family_spec.max != "*":
            max_v = _parse_glibc_like_version(family_spec.max)
            if v_tuple > max_v:
                return False

    return True

# ---------------- Full tag / top-level ----------------

def _accept_tag(tag: Tag) -> bool:
    """
    Determines whether the given tag is acceptable based on its interpreter,
    ABI, and platform. A tag is considered acceptable if its interpreter, ABI,
    and platform meet specific acceptance criteria.

    Args:
        tag (Tag): The tag to evaluate for acceptance.

    Returns:
        bool: True if the tag is acceptable; otherwise, False.
    """
    return (_accept_universal_tag(tag.interpreter, tag.abi, tag.platform)
            or (_accept_interpreter(tag.interpreter)
                and _accept_abi(tag.abi)
                and _accept_platform(tag.platform)))

def evaluate_compatibility(tag_str: str) -> bool:
    """
    Evaluates whether a given tag string is compatible based on the defined
    rules and profiles.

    The function evaluates the compatibility of a tag string against a series
    of conditions defined by tag-specific exclusions, whitelist, and rules
    based on interpreter, ABI, and platform. The evaluation considers the
    precedence of these conditions to determine whether the tag string is
    accepted as compatible.

    Args:
        tag_str (str): The tag string to evaluate, typically containing
            version, ABI, and platform information (e.g.,
            'cp311-cp311-manylinux_2_17_x86_64').

    Returns:
        bool: True if the tag string is considered compatible, False otherwise.
    """
    build_plan = current_packaging_context.get().build_plan
    spec = build_plan.compatibility_spec
    if spec is None:
        raise RuntimeError("CompatibilitySpec not initialized")
    spec.check_initialized()

    tag = next(iter(parse_tag(tag_str)))

    # Tag-level excludes
    if tag in spec.exclude_tags:
        return False

    # Tag-specific whitelist mode
    if spec.tags_specific_only:
        return tag in spec.tags_whitelist

    # Additive tag-specifics
    if tag in spec.tags:
        return True

    # Fallback: axis-based rules
    return _accept_tag(tag)
