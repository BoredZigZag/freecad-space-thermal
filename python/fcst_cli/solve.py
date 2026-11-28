# SPDX-License-Identifier: MIT OR Apache-2.0
"""Run a saved portable case with the local owned worker."""
import os
from pathlib import Path
import subprocess

from fcst_app.persistence import encode, reject
from fcst_app.radiation_case import read_case_mission
from fcst_contracts import loads
from fcst_host import review


def solve_case(package, case_id, worker):
    if not any(e['kind'] == 'case' and e['id'] == case_id for e in package.model['entities']):
        reject('unknown_case')
    worker = Path(worker).resolve()
    flag, payload = review.request(package.model, review.DEFAULT_SETTINGS, case_id,
                                   read_mesh=package.files.__getitem__,
                                   mission=read_case_mission(package.manifest, package.model, case_id, package.files.__getitem__))
    env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR') if key in os.environ}
    env.update(PATH=str(worker.parent), OMP_NUM_THREADS='1')
    try:
        process = subprocess.run([str(worker), flag], input=encode(payload), capture_output=True,
                                 env=env, timeout=120)
    except subprocess.TimeoutExpired:
        reject('worker_timeout')
    if process.returncode or process.stderr:
        reject('native_solve_failed')
    return review.validate_result(loads(process.stdout), package.model)['native']
