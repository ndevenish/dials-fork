from __future__ import annotations

import sys
from pathlib import Path

import libtbx.pkg_utils

# Hack:
# libtbx_refresh needs to import from the package before it's configured.
# Historically, without src/ layout, the full package was implicitly on
# the sys.path, so this worked. Now, it doesn't - other packages might
# attempt to import dials, which would only get a namespace package. This
# means even just setting the path wouldn't work. So, check to see if
# we have a namespace package imported, remove it, set the __path__, then
# import the real copy of DIALS.
#
# This is probably... not something we want to do, but it allows moving
# to src/ without drastically changing this part of the setup.
_dials = sys.modules.get("dials")
if _dials and _dials.__file__ is None:
    _src_path_root = str(Path(libtbx.env.dist_path("dials")).joinpath("src"))
    del sys.modules["dials"]
sys.path.insert(0, _src_path_root)

import dials.precommitbx.nagger

if sys.version_info.major == 2:
    sys.exit("Python 2 is no longer supported")

libtbx.pkg_utils.define_entry_points(
    {
        "dxtbx.profile_model": [
            "gaussian_rs = dials.extensions.gaussian_rs_profile_model_ext:GaussianRSProfileModelExt",
            "ellipsoid = dials.extensions.ellipsoid_profile_model_ext:EllipsoidProfileModelExt",
        ],
        "dxtbx.scaling_model_ext": [
            "physical = dials.algorithms.scaling.model.model:PhysicalScalingModel",
            "KB = dials.algorithms.scaling.model.model:KBScalingModel",
            "array = dials.algorithms.scaling.model.model:ArrayScalingModel",
            "dose_decay = dials.algorithms.scaling.model.model:DoseDecay",
        ],
        "dials.index.basis_vector_search": [
            "fft1d = dials.algorithms.indexing.basis_vector_search:FFT1D",
            "fft3d = dials.algorithms.indexing.basis_vector_search:FFT3D",
            "real_space_grid_search = dials.algorithms.indexing.basis_vector_search:RealSpaceGridSearch",
        ],
        "dials.index.lattice_search": [
            "low_res_spot_match = dials.algorithms.indexing.lattice_search:LowResSpotMatch"
        ],
        "dials.integration.background": [
            "Auto = dials.extensions.auto_background_ext:AutoBackgroundExt",
            "glm = dials.extensions.glm_background_ext:GLMBackgroundExt",
            "gmodel = dials.extensions.gmodel_background_ext:GModelBackgroundExt",
            "simple = dials.extensions.simple_background_ext:SimpleBackgroundExt",
            "null = dials.extensions.null_background_ext:NullBackgroundExt",
            "median = dials.extensions.median_background_ext:MedianBackgroundExt",
        ],
        "dials.integration.centroid": [
            "simple = dials.extensions.simple_centroid_ext:SimpleCentroidExt"
        ],
        "dials.spotfinder.threshold": [
            "dispersion = dials.extensions.dispersion_spotfinder_threshold_ext:DispersionSpotFinderThresholdExt",
            "dispersion_extended = dials.extensions.dispersion_extended_spotfinder_threshold_ext:DispersionExtendedSpotFinderThresholdExt",
        ],
    }
)


try:
    from dials.util.version import dials_version

    print(dials_version())
except Exception:
    pass

dials.precommitbx.nagger.nag()


def _create_dials_env_script():
    """
    write dials environment setup script and clobber cctbx setup scripts
    does nothing unless a file named 'dials'/'dials.bat' exists above
    the build/ directory
    """
    import os

    import libtbx.load_env

    if os.name == "nt":
        filename = abs(libtbx.env.build_path.dirname() / "dials.bat")
    else:
        filename = abs(libtbx.env.build_path.dirname() / "dials")

    if not os.path.exists(filename):
        return

    if os.name == "nt":
        script = """
rem enable conda environment
call %~dp0conda_base\\condabin\\activate.bat
rem prepend cctbx /build/bin directory to PATH
set PATH=%~dp0build\\bin;%PATH%
"""
    else:
        script = """
#!/bin/bash

if [ ! -z "${LIBTBX_BUILD_RELOCATION_HINT:-}" ]; then
  # possibly used for some logic in the installer
  LIBTBX_BUILD="${LIBTBX_BUILD_RELOCATION_HINT}"
  LIBTBX_BUILD_RELOCATION_HINT=
  export LIBTBX_BUILD_RELOCATION_HINT
elif [ -n "$BASH_SOURCE" ]; then
  LIBTBX_BUILD="$(dirname -- "${BASH_SOURCE[0]}")/build"
else
  LIBTBX_BUILD="%s"
fi

# make path absolute and resolve symlinks
LIBTBX_BUILD=$(cd -P -- "${LIBTBX_BUILD}" && pwd -P)

# enable conda environment
source ${LIBTBX_BUILD}/../conda_base/etc/profile.d/conda.sh
conda activate $(dirname -- "${LIBTBX_BUILD}")/conda_base

# prepend cctbx /build/bin directory to PATH
PATH="${LIBTBX_BUILD}/bin:${PATH}"
export PATH

# enable DIALS command line completion
[ -n "$BASH_VERSION" ] && {
  source $(libtbx.find_in_repositories dials/util/autocomplete.sh) && \
  source ${LIBTBX_BUILD}/dials/autocomplete/bash.sh || \
    echo dials command line completion not available
}

unset LIBTBX_BUILD
""" % abs(
            libtbx.env.build_path
        )
    with open(filename, "w") as fh:
        fh.write(script.lstrip())

    if os.name != "nt":
        mode = os.stat(filename).st_mode
        mode |= (mode & 0o444) >> 2  # copy R bits to X
        os.chmod(filename, mode)

    if os.name == "nt":
        clobber = """
echo {stars}
echo The script to set up the DIALS environment has changed
echo Please source or run {newscript} instead
echo {stars}
"""
        clobber_extensions = (".sh", ".csh", ".bat")
    else:
        clobber = """
echo '{stars}'
echo The script to set up the DIALS environment has changed
echo Please source or run '{newscript}' instead
echo '{stars}'
"""
        clobber_extensions = (".sh", ".csh", ".bat")

    for clobberfile_name in (
        "setpaths",
        "setpaths_all",
        "setpaths_debug",
    ):
        for clobber_ext in clobber_extensions:
            with open(
                abs(libtbx.env.build_path / (clobberfile_name + clobber_ext)), "w"
            ) as fh:
                fh.write(clobber.format(newscript=filename, stars="*" * 74))


def _install_dials_autocompletion():
    """generate bash.sh and SConscript file in /build/dials/autocomplete"""
    import os  # required due to cctbx weirdness

    import libtbx.load_env

    # Find the dials source directory
    dist_path = libtbx.env.dist_path("dials")

    # Set the location of the output directory
    output_directory = libtbx.env.under_build(os.path.join("dials", "autocomplete"))
    try:
        os.makedirs(output_directory)
    except OSError:
        pass

    # Build a list of autocompleteable commands
    commands_dir = os.path.join(dist_path, "src", "dials", "command_line")
    command_list = []
    for filename in sorted(os.listdir(commands_dir)):
        if not filename.startswith("_") and filename.endswith(".py"):
            # Check if this file marks itself as completable
            with open(os.path.join(commands_dir, filename), "rb") as f:
                if b"DIALS_ENABLE_COMMAND_LINE_COMPLETION" in f.read():
                    command_name = f"dials.{filename[:-3]}"
                    command_list.append(command_name)
    print("Identified autocompletable commands: " + " ".join(command_list))

    # Generate the autocompletion SConscript.
    with open(os.path.join(output_directory, "SConscript"), "w") as builder:
        builder.write(
            """import os.path
import libtbx.load_env\n
Import("env")\n\n
def dispatcher_outer(name):
    return os.path.join(libtbx.env.under_build("bin"), name)\n\n
def dispatcher_inner(name):
    return os.path.join(
        libtbx.env.dist_path("dials"), "src", "dials", "command_line", "%s.py" % name.partition(".")[2]
    )\n\n
env.Append(
    BUILDERS={{
        "AutoComplete": Builder(action="-$SOURCE --export-autocomplete-hints > $TARGET")
    }}
)
env["ENV"]["DIALS_NOBANNER"] = "1"
for cmd in [
{}
]:
    ac = env.AutoComplete(cmd, [dispatcher_outer(cmd), dispatcher_inner(cmd)])
    Requires(ac, Dir(libtbx.env.under_build("lib")))
    Depends(ac, os.path.join(libtbx.env.dist_path("dials"), "util", "options.py"))
    Depends(ac, os.path.join(libtbx.env.dist_path("dials"), "util", "autocomplete.sh"))
""".format(
                "\n".join([f'    "{cmd}",' for cmd in command_list])
            )
        )

    # Generate a bash script activating command line completion for each relevant command
    with open(os.path.join(output_directory, "bash.sh"), "w") as script:
        script.write("type compopt &>/dev/null && {\n")
        for cmd in command_list:
            script.write(f" complete -F _dials_autocomplete {cmd}\n")
        script.write("}\n")
        script.write("type compopt &>/dev/null || {\n")
        for cmd in command_list:
            script.write(f" complete -o nospace -F _dials_autocomplete {cmd}\n")
        script.write("}\n")


_create_dials_env_script()
_install_dials_autocompletion()
