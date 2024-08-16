#!/usr/bin/env python

from __future__ import annotations

import os
import re
import sys
from collections import namedtuple

try:
    from typing import Literal, TypedDict

    type SectionName = Literal["build", "host", "run", "test"]
    VALID_SECTIONS = {"build", "run", "host", "test"}  # type: set[SectionName]
    type Dependencies = dict[SectionName, list[Dependency]]

except ImportError:
    pass
Dependency = namedtuple("Dependency", ["name", "version", "raw_line"])


re_selector = re.compile(r"# *\[([^#]+)]$")
re_pin = re.compile(r"""{{ *pin_compatible *\( *['"]([^'"]+)['"]""")


def _native_platform():
    # type: () -> Literal["osx", "win", "linux"]
    """Gets the native platform name for selection purposes"""
    if sys.platform == "darwin":
        return "osx"
    elif os.name == "nt":
        return "win"
    elif sys.platform.startswith("linux"):
        return "linux"


def _split_dependency_line(line):
    """Split a single line into (name, version, raw_line) parts"""
    # type: (str) -> Dependency

    # Lines that are templated get ignored here
    if "{" in line:
        return Dependency(None, None, line)
    pending = line
    # Strip off the comment/selector
    if "#" in line:
        pending = pending[: pending.index("#")].strip()
    # If we have a version spec and no space, this is an error
    if " " not in pending and (set(pending) & set("><=!")):
        raise RuntimeError(
            "Error: Versioned requirement '%s' has no space" % (pending,)
        )
    vers = None
    if " " in pending:
        pending, vers = pending.split(" ", maxsplit=1)
    return Dependency(pending, vers, line)


def _merge_dependency_lists(source, merge_into):
    # type: (list[Dependency], list[Dependency]) -> None
    """
    Merge two lists of dependencies into one unified list.

    This will replace unversioned dependencies with versioned
    dependencies, merge dependencies with identical versions, and
    leave in place depenencies with versions specified.

    Lines from the source list that don't have a dependency name
    will be added as long as they don't have a duplicate line in the
    target list.
    """
    indices = {x[0]: i for i, x in enumerate(merge_into)}
    for pkg, ver, line in source:
        if pkg is None:
            # Lines that don't define a package always get added
            merge_into.append(Dependency(pkg, ver, line))
        elif pkg in indices:
            # This already exists in the target. Should we replace it?
            other_ver = merge_into[indices[pkg]][1]
            if not other_ver and ver:
                print(f"Merging '{line}' over {merge_into[indices[pkg]]}")
                merge_into[indices[pkg]] = Dependency(pkg, ver, line)
            elif other_ver and ver and ver != other_ver:
                raise RuntimeError(
                    "Cannot merge requirements for %s: '%s' and '%s'"
                    % (pkg, ver, other_ver)
                )
        else:
            merge_into.append(Dependency(pkg, ver, line))
            indices[pkg] = len(merge_into) - 1


# def _merge_dependency_dictionaries(sources):
#     # type: (list[dict[str, Dependency]]) -> dict[str, Dependency]
#     """Merge multiple parsed dependency dictionaries into one."""
#     Evidently WIP?


class DependencySelectorParser(object):
    """
    Parse simple conda-build selectors syntax, with optional variables.

    Supported:
    - Variables linux, osx, win, in addition to anything passed into __init__
    - Variable inversion e.g. "not osx"
    - Basic "And" combinations e.g. "bootstrap and not osx"
    """

    def __init__(self, **kwargs):
        self._vars = dict(kwargs)
        if kwargs.get("platform", None) is None:
            kwargs["platform"] = _native_platform()
        self._vars.update(
            {
                "osx": kwargs["platform"] == "osx",
                "linux": kwargs["platform"] == "linux",
                "win": kwargs["platform"] == "win",
            }
        )

    def _parse_expression(self, fragment, pos=0):
        # type: (str, int) -> bool
        """Recursively parse an expression or fragment of an expression."""
        if fragment in self._vars:
            return self._vars[fragment]
        if " and " in fragment:
            left, right = fragment.split(" and ", maxsplit=1)
            return self._parse_expression(left, pos) and self._parse_expression(
                right, pos + fragment.index(" and ")
            )
        if fragment.startswith("not "):
            return not self._parse_expression(fragment[4:].strip(), pos + 4)
        raise ValueError("Could not parse selector fragment '" + fragment + "'")

    def preprocess(self, data):
        # type: (str) -> str
        """Apply preprocessing selectors to raw file data"""
        output_lines = []
        for line in data.splitlines():
            match = re_selector.search(line)

            if match:
                if self._parse_expression(match.group(1)):
                    # print(f"... Passed: {line}")
                    output_lines.append(line)
            elif re_pin.search(line):
                # Ignore pin_compatible dependencies
                continue
            else:
                output_lines.append(line)
        return "\n".join(output_lines)

    def parse_file(self, filename):
        # type: (str) -> Dependencies
        """
        Parse a dependency file into a structured dictionary.

        The dictionary has structure:
        {
            "section": [
                ("dependency_name", "dependency_version", "raw_line"),
                ...
            ]
        }
        """
        with open(filename, "rt") as f:
            data = self.preprocess(f.read())
        output = {}  # type: Dependencies
        current_section = None  # type: SectionName | None
        for n, line in enumerate(data.splitlines()):
            # print(f"Examining line {n}: {line} (current: {current_section})")
            if "#" in line:
                line = line[: line.index("#")]
            line = line.strip()
            if line.endswith(":"):
                new_section = line[:-1].strip()
                assert new_section in VALID_SECTIONS
                current_section = new_section
                output[current_section] = []
            elif line.startswith("-"):
                if not current_section:
                    raise RuntimeError(
                        "Error parsing "
                        + filename
                        + ":"
                        + str(n + 1)
                        + "; No current section on line '"
                        + line
                        + "'"
                    )
                assert current_section in VALID_SECTIONS
                req = _split_dependency_line(line[1:].strip())
                the_list = output.setdefault(current_section, [])
                the_list.append(req)
            else:
                if line:
                    raise RuntimeError(
                        "Error parsing "
                        + filename
                        + ":"
                        + str(n + 1)
                        + "; Uncategorised line '"
                        + line
                        + "'"
                    )
        return output

    def parse_files(self, filenames):
        # type: (list[str | os.PathLike]) -> Dependencies
        """Parse and merge multiple dependency files."""
        reqs = {}  # type: Dependencies
        for source in filenames:
            source_reqs = self.parse_file(str(source))
            # Now, merge this into the previous results
            for section, items in source_reqs.items():
                _merge_dependency_lists(items, reqs.setdefault(section, []))
        return reqs


def preprocess_for_bootstrap(paths, prebuilt_cctbx, platform):
    # type: (list[str | os.PathLike], bool, str) -> list[str]
    """Do dependency file preprocessing intended for bootstrap.py"""
    parser = DependencySelectorParser(
        prebuilt_cctbx=prebuilt_cctbx, bootstrap=True, platform=platform
    )
    reqs = parser.parse_files(paths)
    merged_req = []
    for items in reqs.values():
        _merge_dependency_lists(items, merged_req)

    output_lines = []
    for pkg, ver, _ in sorted(merged_req, key=lambda x: x[0]):
        if pkg == "python":
            # Bootstrap handles this dependency implicitly
            continue
        output_lines.append("conda-forge::" + pkg + (ver or ""))
    return output_lines


def test_parser():
    parser = DependencySelectorParser(bootstrap=True, prebuilt_cctbx=False)
    assert parser._parse_expression("osx")
    assert parser._parse_expression("bootstrap")
    assert parser._parse_expression("osx and bootstrap")
    assert not parser._parse_expression("linux and bootstrap")
    assert not parser._parse_expression("prebuilt_cctbx and osx and not bootstrap")


if __name__ == "__main__":
    from argparse import ArgumentParser
    from pprint import pprint

    parser = ArgumentParser()
    parser.add_argument(
        "-k",
        "--kind",
        choices=["bootstrap", "conda-build"],
        help="Choose the target for handling dependency lists. Default: %(default)s",
        default="bootstrap",
    )
    parser.add_argument(
        "-p",
        "--platform",
        choices=["osx", "linux", "win"],
        help="Choose the target for handling bootstrap dependency lists. Default: %(default)s",
        default=_native_platform(),
    )
    # parser.add_argument("--conda-build", action="store_const", const="conda-build", dest="kind", help="Run as though constructing a conda-build recipe")
    parser.add_argument(
        "--prebuilt-cctbx", help="Mark as using prebuilt cctbx. Implied by conda-build."
    )
    parser.add_argument("sources", nargs="+", help="Dependency files to merge")
    args = parser.parse_args()

    if args.kind == "bootstrap":
        print(
            "\n".join(
                preprocess_for_bootstrap(
                    args.sources,
                    prebuilt_cctbx=args.prebuilt_cctbx,
                    platform=args.platform,
                )
            )
        )
    else:
        if args.platform:
            sys.exit("Error: Can only specify platform with --kind=bootstrap")
        deps = DependencySelectorParser(bootstrap=False, prebuilt_cctbx=True)
        reqs = deps.parse_files(args.sources)
        pprint(reqs)