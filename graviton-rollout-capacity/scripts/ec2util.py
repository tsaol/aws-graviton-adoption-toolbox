"""Small helpers shared by the scripts. Standard library only."""
import re

_SIZE = re.compile(r"^(?P<family>[a-z]+\d+[a-z\-]*)\.(?P<size>[a-z0-9]+)$")
_FIXED = {"medium": 1, "large": 2, "xlarge": 4}
# families whose small sizes break the simple rule are rare for rollouts; pass --vcpu to override
_GRAVITON = re.compile(r"^[a-z]+\d+g[a-z\-]*$")


def family(itype):
    m = _SIZE.match(itype or "")
    return m.group("family") if m else ""


def is_graviton(itype):
    """True for Graviton families such as m8g, c7gn, r8gd, t4g, x2gd, im4gn, is4gen."""
    f = family(itype)
    return bool(_GRAVITON.match(f)) or f in {"a1", "is4gen", "im4gn"}


def vcpus(itype, overrides=None):
    """vCPUs for a size name: Nxlarge = 4N, xlarge = 4, large = 2, medium = 1
    (t-family nano to medium = 2). 'metal' sizes need an override."""
    if overrides and itype in overrides:
        return int(overrides[itype])
    m = _SIZE.match(itype or "")
    if not m:
        raise ValueError(f"unknown instance type {itype!r}")
    size = m.group("size")
    if m.group("family").startswith("t") and size in ("nano", "micro", "small", "medium"):
        return 2                      # burstable t-family: nano to medium all have 2 vCPUs
    if size in _FIXED:
        return _FIXED[size]
    n = re.match(r"^(\d+)xlarge$", size)
    if n:
        return 4 * int(n.group(1))
    raise ValueError(f"cannot infer vCPUs for {itype!r}; pass an override")
