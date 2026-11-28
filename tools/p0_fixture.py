# SPDX-License-Identifier: MIT OR Apache-2.0
"""Synthetic portable scaffold and fixed-ID edits for the P0 demonstration."""
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    sys.path.insert(0, str(ROOT/'python'))

from fcst_app.arrays import write_arrays
from fcst_app.jobs import reference
from fcst_app.persistence import Package, encode
from fcst_app.store import ProjectStore
from fcst_host.review import new_model, uid

FIXTURE = ROOT / 'tests/fixtures/radiation/p0-two-surfaces.json'
MODEL = json.loads(FIXTURE.read_bytes())
PROJECT, CASE, LOAD = uid(100), uid(111), uid(110)
NODES, SURFACES = [uid(103), uid(104)], [uid(107), uid(108)]


def temperature_hash(times, values):
    return sha256(encode(dict(node_ids=NODES, time_s=times, temperature_K=values))).hexdigest()


def temperature_series(result):
    order = [result['node_ids'].index(node) for node in NODES]
    return ([s['time_s'] for s in result['samples']],
            [[s['temperature_K'][i] for i in order] for s in result['samples']])


def quantity(value, unit):
    return dict(value=value, unit=unit)


def scaffold():
    model = new_model()
    model['project_id'] = PROJECT
    tag = sha256(FIXTURE.read_bytes()).hexdigest()
    mesh = write_arrays('radiation_mesh', tag, {
        'index/entity_uuid': [list(UUID(key).bytes) for key in SURFACES],
        'vertices': MODEL['vertices_m'], 'normals': MODEL['normals'],
        'connectivity/offsets': [0, 3, 6], 'connectivity/vertex_index': list(range(6)),
    })
    path = 'mesh/two-surfaces.h5'
    area = quantity(MODEL['area_m2'], 'm2')
    model['entities'] = [
        dict(id=uid(101), kind='submodel', label='Two-node network'),
        dict(id=uid(102), kind='frame', origin=[quantity(0, 'm')]*3, rotation=[[1,0,0],[0,1,0],[0,0,1]]),
        *[dict(id=node, kind='node', submodel_id=uid(101), classification='capacitive',
               temperature=quantity(300, 'K'), capacity=quantity(1, 'J/K')) for node in NODES],
        dict(id=uid(105), kind='mesh', frame_id=uid(102), role='radiation', artifact=reference(path, mesh)),
        dict(id=uid(106), kind='optics', solar_absorptivity=MODEL['solar_absorptivity'],
             ir_emissivity=MODEL['ir_emissivity'], specular_fraction=0, transmissivity=0),
        *[dict(id=key, kind='facet', mesh_id=uid(105), side='front', area=area, optics_id=uid(106),
               label='Radiating surface '+str(i+1)) for i, key in enumerate(SURFACES)],
    ]
    model['mappings'] = [dict(id=uid(120+i), from_id=key, to_id=node, weight=1, area=area, provenance=tag)
                         for i, (key, node) in enumerate(zip(SURFACES, NODES))]
    return Package.create(model, [(uid(130), 'mesh', path, mesh, [])])


def edits(model):
    def entity(key):
        return next(e for e in model['entities'] if e['id'] == key)

    material = MODEL['material']
    return [
        *[dict(entity(key), temperature=quantity(temperature, 'K'), capacity=quantity(capacity, 'J/K'))
          for key, temperature, capacity in zip(NODES, MODEL['temperature_K'], MODEL['capacity_J_K'])],
        dict(id=uid(113), kind='material', density=quantity(material['density_kg_m3'], 'kg/m3'),
             specific_heat=quantity(material['specific_heat_J_kg_K'], 'J/(kg*K)'),
             conductivity=quantity(material['conductivity_W_m_K'], 'W/(m*K)'),
             valid_temperature=[quantity(200, 'K'), quantity(400, 'K')]),
        dict(id=uid(114), kind='conductor', from_node_id=NODES[0], to_node_id=NODES[1],
             conductance=quantity(MODEL['conductance_W_K'], 'W/K')),
        dict(id=uid(109), kind='environment', frame_id=uid(102), background_temperature=quantity(MODEL['background_K'], 'K'),
             solar_flux=quantity(MODEL['solar_flux_W_m2'], 'W/m2'), epoch='2026-01-01T00:00:00',
             time_scale='TAI', time_origin=quantity(0, 's')),
        dict(id=uid(112), kind='radiation', facet_ids=SURFACES, excluded_facet_ids=[],
             environment_id=uid(109), method='diffuse'),
        dict(id=LOAD, kind='load', node_id=NODES[0], power=quantity(MODEL['load_W'], 'W')),
        dict(id=CASE, kind='case', mode='transient', start=quantity(0, 's'), end=quantity(MODEL['duration_s'], 's'),
             environment_id=uid(109), load_ids=[LOAD], control_ids=[], overlays=[]),
    ]


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.suffix != '.fcst':
        parser.error('Choose a new .fcst package path.')
    seed = scaffold()
    with ProjectStore.create(':memory:', package=seed) as project:
        project.apply('local', {'changes.apply'}, PROJECT, 0, 'build', dict(upsert=edits(seed.model), delete=[]))
        project.save(args.output)
    print('P0 demonstration package saved.')
