"""The API's request/response schemas, split per domain behind this wildcard barrel (Mf-avo9).

Each domain module is lane-able on its own; this barrel, with its import list, MODULES
tuple and __all__, is the shared surface every schema-adding lane must not edit unless it
adds a domain. A domain module imports its siblings DIRECTLY (`from .assets import
AssetOut`) and never through this barrel, which would re-enter the partially-initialised
package - that rule is also why the order below does not matter.

Dependency DAG, the only cross-domain edges that exist (everything else is
self-contained): assets <- batch <- projects <- imports.
"""

# ruff: noqa: F403
from . import (
  asset_files,
  assets,
  audit_log,
  auth_users,
  batch,
  folders,
  import_runs,
  imports,
  library,
  mfa,
  projects,
  settings,
  snapshots,
  trash,
)
from .asset_files import *
from .assets import *
from .audit_log import *
from .auth_users import *
from .batch import *
from .folders import *
from .import_runs import *
from .imports import *
from .library import *
from .mfa import *
from .projects import *
from .settings import *
from .snapshots import *
from .trash import *

MODULES = (asset_files, assets, audit_log, auth_users, batch, folders, import_runs, imports, library, mfa, projects, settings, snapshots, trash)

# Sorted, not raw module-alphabetical concatenation: module order is not class-name order
# (auth_users' names sit inside assets' range), so the two readings of the pin cannot both
# hold literally. Sortedness is mandated by AC-1; the partition is asserted exactly in
# tests/test_openapi_contract.py as sorted(concat of MODULES' __all__) == __all__.
__all__ = sorted(
  [
    *asset_files.__all__,
    *assets.__all__,
    *audit_log.__all__,
    *auth_users.__all__,
    *batch.__all__,
    *folders.__all__,
    *import_runs.__all__,
    *imports.__all__,
    *library.__all__,
    *mfa.__all__,
    *projects.__all__,
    *settings.__all__,
    *snapshots.__all__,
    *trash.__all__,
  ]
)
