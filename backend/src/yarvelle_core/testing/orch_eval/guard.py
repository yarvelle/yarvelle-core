# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Run gates for the orchestration eval harness.

Two independent checks guard every entry point:

* :func:`ensure_not_ci` refuses to run when any known CI environment variable
  is present. It runs first, it cannot be overridden, and the opt-in variable
  does not bypass it.
* :func:`ensure_opted_in` requires ``YARVELLE_EVAL=1``.

Refusals raise :class:`EvalRefusedError`, which carries the process exit code
the command-line entry points use.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

OPT_IN_ENV_VAR = "YARVELLE_EVAL"

# Exit code for "refused because this looks like CI". Fixed so tests and
# callers can tell a CI refusal from an ordinary failure.
EXIT_CI_REFUSED = 3
# Exit code for "refused because the run was not opted in".
EXIT_NOT_OPTED_IN = 4

# Environment variables set by common CI systems. Presence with any non-empty
# value counts as CI, including values such as "false" or "0": the harness
# never guesses that a CI runner is safe.
CI_ENV_VARS: tuple[str, ...] = (
    "CI",
    "CONTINUOUS_INTEGRATION",
    "GITHUB_ACTIONS",
    "GITHUB_RUN_ID",
    "RUNNER_NAME",
    "RUNNER_OS",
    "GITLAB_CI",
    "CIRCLECI",
    "TRAVIS",
    "BUILDKITE",
    "JENKINS_URL",
    "TEAMCITY_VERSION",
    "TF_BUILD",
    "BITBUCKET_BUILD_NUMBER",
    "CODEBUILD_BUILD_ID",
    "DRONE",
    "APPVEYOR",
)

_OUTPUT_ROOT_DIRNAME = ".yarvelle-evals"


class EvalRefusedError(RuntimeError):
    """Raised when an eval entry point must not run in this environment."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _env(environ: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def detect_ci(environ: Optional[Mapping[str, str]] = None) -> list[str]:
    """Returns the names of CI environment variables that are set, in a fixed order.

    Only names are returned, never values.
    """
    env = _env(environ)
    return [name for name in CI_ENV_VARS if env.get(name, "") != ""]


def is_opted_in(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True only when ``YARVELLE_EVAL`` is exactly ``"1"``."""
    return _env(environ).get(OPT_IN_ENV_VAR, "") == "1"


def ci_refusal_message(detected: list[str]) -> str:
    """Builds the message shown when a CI environment is detected."""
    names = ", ".join(detected)
    return (
        "Orchestration evals never run on CI. "
        f"Detected CI environment variable(s): {names}. "
        "Run them on a local machine; there is no override."
    )


def not_opted_in_message() -> str:
    """Builds the message shown when the opt-in variable is missing."""
    return (
        "Orchestration evals are local-only and need an explicit opt-in. "
        f"Set {OPT_IN_ENV_VAR}=1 to run them."
    )


def ensure_not_ci(environ: Optional[Mapping[str, str]] = None) -> None:
    """Raises :class:`EvalRefusedError` (exit 3) when any CI variable is set."""
    detected = detect_ci(environ)
    if detected:
        raise EvalRefusedError(ci_refusal_message(detected), EXIT_CI_REFUSED)


def ensure_opted_in(environ: Optional[Mapping[str, str]] = None) -> None:
    """Refuses on CI first, then requires ``YARVELLE_EVAL=1`` (exit 4)."""
    ensure_not_ci(environ)
    if not is_opted_in(environ):
        raise EvalRefusedError(not_opted_in_message(), EXIT_NOT_OPTED_IN)


def default_output_root() -> Path:
    """Directory that holds run reports, outside any repository checkout."""
    return Path.home() / _OUTPUT_ROOT_DIRNAME
