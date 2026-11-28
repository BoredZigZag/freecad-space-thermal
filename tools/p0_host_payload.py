# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise the P0 fixture in the existing pinned FreeCAD process."""
from copy import deepcopy
import json

import FreeCAD as App
from PySide6 import QtCore, QtTest, QtWidgets

from fcst_app.persistence import semantic_hash
from fcst_app.store import ProjectStore
from fcst_host import review, workbench
from fcst_host.controller import Session
from fcst_host.widgets import EntityEditor, NativeJob
from p0_fixture import CASE, LOAD, MODEL, NODES, ROOT, SURFACES, edits, temperature_hash, temperature_series


def check(folder, wait, rejects, worker):
    criteria = json.loads((ROOT/'ci/p0-acceptance.json').read_bytes())
    session = Session.open(folder/'p0-scaffold.fcst', folder/'p0-build')
    panel = workbench.show(session)
    panel.worker = worker
    for entity in edits(session.store.snapshot()):
        editor = EntityEditor(session, entity, panel)
        editor.commit()
        assert editor.result() == QtWidgets.QDialog.Accepted, editor.error.text()
        editor.deleteLater()
    panel.cases.setCurrentIndex(panel.cases.findData(CASE))
    assert session.case_id == CASE
    expected_hash = semantic_hash(session.store.snapshot())
    session.save(folder/'p0.FCStd', folder/'p0.fcst')
    session.close()
    App.closeDocument(session.doc.Name)

    session = Session.open(folder/'p0.fcst', folder/'p0-reopened')
    panel = workbench.show(session)
    panel.worker = worker
    assert session.case_id == CASE
    assert semantic_hash(session.store.snapshot()) == expected_hash
    QtTest.QTest.mouseClick(panel.run, QtCore.Qt.LeftButton)
    wait(lambda: session.job is not None and session.job.state not in ('queued', 'running'))
    assert session.job.state == 'succeeded', session.job.state
    result_id = session.result_id
    result = review.query_result(session.store, result_id)
    assert result['native']['exchange_builds'] == 1
    times, values = temperature_series(result)
    panel.time.setValue(len(times)-1)
    lower = min(min(row) for row in values)
    upper = max(max(row) for row in values)
    contour_error = 0
    for index, surface in enumerate(SURFACES):
        panel.select_entity(surface)
        assert panel.selected == surface
        assert panel.history.points == [(t, row[index]) for t, row in zip(times, values)]
        obj = session.objects[surface]
        assert len(obj.Shape.Faces) == 1
        target = review.colour(values[-1][index], lower, upper)
        contour_error = max(contour_error, *(abs(a-b) for a,b in zip(obj.ViewObject.ShapeColor, target)))
    assert contour_error <= criteria['contour_rgb_error']
    assert 'radiation in W' in panel.budget.toPlainText()

    load = deepcopy(next(e for e in session.store.snapshot()['entities'] if e['id'] == LOAD))
    editor = EntityEditor(session, load, panel)
    editor.fields['power'][1].setText(str(MODEL['edited_load_W']))
    editor.commit()
    assert editor.result() == QtWidgets.QDialog.Accepted
    editor.deleteLater()
    edited_hash = semantic_hash(session.store.snapshot())
    assert edited_hash != expected_hash
    assert not panel.history.points and not panel.time.isEnabled()
    rejects(lambda: review.query_result(session.store, result_id), 'stale_result')
    assert review.query_result(session.store, result_id, historical=True)['historical']
    session.save(folder/'p0-edited.FCStd', folder/'p0-edited.fcst')

    jobs = {}
    for state in ('cancelled', 'interrupted'):
        job = NativeJob(session, worker)
        session.job = job
        job.changed.connect(panel.job_changed)

        def act(status):
            if status == 'running':
                if state == 'cancelled':
                    QtTest.QTest.mouseClick(panel.cancel, QtCore.Qt.LeftButton)
                else:
                    QtCore.QTimer.singleShot(0, job.process.kill)

        job.changed.connect(act)
        job.start()
        wait(lambda: job.process.state() == QtCore.QProcess.NotRunning and job.state not in ('queued', 'running'))
        assert job.state == state, job.state
        assert session.result is None
        jobs[job.id] = state
    assert [(d['id'], d['stale']) for d in session.store.state()['derived']] == [(result_id, True)]
    database = session.store.path
    session.close()
    App.closeDocument(session.doc.Name)
    with ProjectStore(database) as operational:
        assert dict(row for row in operational.db.execute(
            "SELECT id,state FROM host_runs WHERE state IN ('cancelled','interrupted')")) == jobs
    session = Session.open(folder/'p0-edited.fcst', folder/'p0-recovered')
    try:
        assert semantic_hash(session.store.snapshot()) == edited_hash
        assert session.result is None
        assert [(d['id'], d['stale']) for d in session.store.state()['derived']] == [(result_id, True)]
    finally:
        session.close()
        App.closeDocument(session.doc.Name)
    return dict(model_hash=expected_hash, edited_model_hash=edited_hash, temperature_hash=temperature_hash(times, values),
                samples=len(times), contour_error=contour_error, history_matches=True, stale_rejected=True,
                terminal_states=['cancelled','interrupted'], partial_results=0, recovered=True)
