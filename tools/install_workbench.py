# SPDX-License-Identifier: MIT OR Apache-2.0
"""Install the source workbench into an explicitly selected FreeCAD Mod directory."""
import argparse
import importlib.metadata
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def install(destination, *, radiation=False):
    distribution = importlib.metadata.distribution('h5py') if radiation else None
    if radiation and distribution.version != '3.12.1':
        raise ValueError('host_hdf5_version')
    destination=Path(destination).resolve()/'FCST'
    if destination.exists():
        raise ValueError('workbench_destination_exists')
    destination.mkdir(parents=True)
    for source in (ROOT/'freecad/FCST').glob('*.py'):
        shutil.copyfile(source,destination/source.name)
    # FreeCAD adds each Mod directory to sys.path; keep the adapter install offline.
    for name in ('fcst_host','fcst_app','fcst_contracts'):
        shutil.copytree(ROOT/'python'/name,destination/name,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'))
    shutil.copyfile(ROOT/'LICENSE',destination/'LICENSE')
    shutil.copytree(ROOT/'LICENSES',destination/'LICENSES')
    if distribution is not None:
        # The pinned Windows host supplies NumPy. Keep the optional HDF5 wheel
        # and its DLLs isolated in this workbench rather than modifying the host.
        for entry in distribution.files:
            if entry.parts[0] not in {'h5py', 'h5py.libs', 'h5py-3.12.1.dist-info'} or entry.suffix == '.pyc':
                continue
            target = destination / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(distribution.locate_file(entry), target)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod-directory',type=Path,required=True)
    parser.add_argument('--with-radiation', action='store_true')
    args=parser.parse_args()
    install(args.mod_directory, radiation=args.with_radiation)
    print('FCST workbench installed; native worker selected separately in Solve.')
