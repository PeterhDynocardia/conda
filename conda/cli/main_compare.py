# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""CLI implementation for `conda compare`.

Compare the packages in an environment with the packages listed in an environment file.
"""

from __future__ import annotations

import logging
import os
import subprocess
from os.path import abspath, expanduser, expandvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction

log = logging.getLogger(__name__)


def configure_parser(sub_parsers: _SubParsersAction, **kwargs) -> ArgumentParser:
    from ..auxlib.ish import dals
    from .helpers import add_parser_json, add_parser_prefix

    summary = "Compare packages between conda environments."
    description = summary
    epilog = dals(
        """++
        Examples:

        Compare packages in the current environment with respect
        to 'environment.yml' located in the current working directory::

            conda compare environment.yml

        Compare packages installed into the environment 'myenv' with respect
        to 'environment.yml' in a different directory::

            conda compare -n myenv path/to/file/environment.yml
            
        Compare packages between two conda environments with the -diff flag::

            conda compare -diff env1 env2

        """
    )

    p = sub_parsers.add_parser(
        "compare",
        help=summary,
        description=description,
        epilog=epilog,
        **kwargs,
    )
    add_parser_json(p)
    add_parser_prefix(p)
    p.add_argument(
        "file",
        action="store",
        help="Path to the environment file that is to be compared against.",
    )
    

    p.add_argument(
        "-diff",
        action="store_true",
        help="Show differences between two environments.",
    )
    p.add_argument(
        "env1",
        nargs=1,
        action="store",
        help="First environment to compare against if using -diff.",
    )
    
    p.add_argument(
        "env2",
        nargs=1,
        action="store",
        help="Second environment to compare against if using -diff.",
    )
    p.set_defaults(func="conda.cli.main_compare.execute")


    return p


def get_packages(prefix):
    from ..core.prefix_data import PrefixData
    from ..exceptions import EnvironmentLocationNotFound

    if not os.path.isdir(prefix):
        raise EnvironmentLocationNotFound(prefix)

    return sorted(
        PrefixData(prefix, pip_interop_enabled=True).iter_records(),
        key=lambda x: x.name,
    )


def compare_packages(active_pkgs, specification_pkgs) -> tuple[int, list[str]]:
    from ..models.match_spec import MatchSpec

    output = []
    miss = False
    for pkg in specification_pkgs:
        pkg_spec = MatchSpec(pkg)
        if (name := pkg_spec.name) in active_pkgs:
            if not pkg_spec.match(active_pkg := active_pkgs[name]):
                miss = True
                output.append(
                    f"{name} found but mismatch. Specification pkg: {pkg}, "
                    f"Running pkg: {active_pkg.name}=={active_pkg.version}={active_pkg.build}"
                )
        else:
            miss = True
            output.append(f"{name} not found")
    if not miss:
        output.append(
            "Success. All the packages in the "
            "specification file are present in the environment "
            "with matching version and build string."
        )
    return int(miss), output


    
def check_diff_installed():
    if subprocess.call(["which", "diff"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) != 0:
        print("diff command could not be found. Please install it to proceed.")
        exit(1)

def display_table(diff_output, env1, env2):
    print("\nPackage Differences:\n")
    print(f"{'Package':<40} {env1:<20} {env2:<20}")
    print(f"{'-------':<40} {'----':<20} {'----':<20}")

    for line in diff_output.splitlines():
        if line.startswith('<'):
            package = line[2:]
            print(f"\033[41m{package:<40} {'Present':<20} {'Absent':<20}\033[0m")
        elif line.startswith('>'):
            package = line[2:]
            print(f"\033[44m{package:<40} {'Absent':<20} {'Present':<20}\033[0m")

def find_conda_setup():
    conda_path = subprocess.check_output(["which", "conda"]).decode("utf-8").strip()
    conda_setup = os.path.join(os.path.dirname(os.path.dirname(conda_path)), 'etc', 'profile.d', 'conda.sh')
    
    return conda_setup
    
def compare_envs(env1, env2):
    check_diff_installed()

    # Source the conda setup script
    conda_setup = find_conda_setup()
    command = f"source {conda_setup} && conda activate {env1} && conda list > env1_packages.txt && conda activate {env2} && conda list > env2_packages.txt && conda deactivate"
    os.system(command)

    # Generate the differences using diff
    result = subprocess.run(["diff", "env1_packages.txt", "env2_packages.txt"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    diff_output = result.stdout.decode('utf-8')

    # Display the differences in a color-coded table
    display_table(diff_output, env1, env2)

    # Clean up temporary files
    os.remove("env1_packages.txt")
    os.remove("env2_packages.txt")

def execute(args, parser):
    from ..base.context import context
    from ..env import specs
    from ..exceptions import EnvironmentLocationNotFound, SpecNotFound
    from ..gateways.connection.session import CONDA_SESSION_SCHEMES
    from ..gateways.disk.test import is_conda_environment
    from .common import stdout_json

    if args.diff:
        compare_envs(args.env1, args.env2)
        return 0

    prefix = context.target_prefix
    if not is_conda_environment(prefix):
        raise EnvironmentLocationNotFound(prefix)

    try:
        url_scheme = args.file.split("://", 1)[0]
        if url_scheme in CONDA_SESSION_SCHEMES:
            filename = args.file
        else:
            filename = abspath(expanduser(expandvars(args.file)))

        spec = specs.detect(name=args.name, filename=filename, directory=os.getcwd())
        env = spec.environment

        if args.prefix is None and args.name is None:
            args.name = env.name
    except SpecNotFound:
        raise

    active_pkgs = {pkg.name: pkg for pkg in get_packages(prefix)}
    specification_pkgs = []
    if "conda" in env.dependencies:
        specification_pkgs = specification_pkgs + env.dependencies["conda"]
    if "pip" in env.dependencies:
        specification_pkgs = specification_pkgs + env.dependencies["pip"]

    exitcode, output = compare_packages(active_pkgs, specification_pkgs)

    if context.json:
        stdout_json(output)
    else:
        print("\n".join(map(str, output)))

    return exitcode
