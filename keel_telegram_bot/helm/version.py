import functools
import re
from dataclasses import dataclass
from typing import Optional, Tuple

# lenient semver: optional "v" prefix, minor and patch may be missing (e.g. "v1.2")
SEMVER_PATTERN = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)"
    r"(?:\.(?P<minor>0|[1-9]\d*))?"
    r"(?:\.(?P<patch>0|[1-9]\d*))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@functools.total_ordering
@dataclass(frozen=True)
class SemVer:
    """
    A semantic version, ordered by semver 2.0 precedence (build metadata is ignored)
    """
    major: int
    minor: int
    patch: int
    prerelease: Tuple[str, ...] = ()

    @staticmethod
    def parse(text: str) -> Optional["SemVer"]:
        """
        Parses a version string
        :param text: the version string, e.g. "1.2.3", "v1.2.3-rc.1" or "1.2.3+build.5"
        :return: the parsed version, or None if the text is not a semantic version
        """
        if text is None:
            return None
        match = SEMVER_PATTERN.match(str(text).strip())
        if match is None:
            return None
        prerelease = match.group("prerelease")
        return SemVer(
            major=int(match.group("major")),
            minor=int(match.group("minor") or 0),
            patch=int(match.group("patch") or 0),
            prerelease=tuple(prerelease.split(".")) if prerelease else (),
        )

    @property
    def is_prerelease(self) -> bool:
        return len(self.prerelease) > 0

    def _key(self):
        # a version without pre-release has higher precedence than one with
        if not self.is_prerelease:
            prerelease_key = (1,)
        else:
            # numeric identifiers have lower precedence than alphanumeric ones,
            # a shorter set of identifiers has lower precedence if all preceding ones are equal
            prerelease_key = (0, tuple(
                (0, int(x), "") if x.isdigit() else (1, 0, x)
                for x in self.prerelease
            ))
        return self.major, self.minor, self.patch, prerelease_key

    def __lt__(self, other: "SemVer") -> bool:
        return self._key() < other._key()

    def __eq__(self, other) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __str__(self):
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.is_prerelease:
            text += "-" + ".".join(self.prerelease)
        return text
