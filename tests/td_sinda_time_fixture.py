# SPDX-License-Identifier: MIT OR Apache-2.0
"""Owned sources for the same time-power oracle in both adapter profiles."""
from fcst_exchange.sinda import SindaUnits
from fcst_exchange.td_writer import load_payload, node_payload

UNITS = SindaUnits('K', 'J/K', 'W/K', 'W', 's')
SINDA = b'''HEADER REGISTER DATA
GAIN = 2.0
HEADER NODE DATA, MAIN
1, 300, 2
2, 300, 4
HEADER ARRAY DATA, TABLES
1 = 0.0, 1.0, 2.0
2 = 0.0, 2.0, 0.0
3 = 0.0, 0.5, 1.0
4 = 2.0, 6.0, 4.0
HEADER SOURCE DATA, MAIN
TVS 1, TABLES.A1, TABLES.A2, GAIN
PER 2, TABLES.A3, TABLES.A4, 1.0, 0.0, 1.0
END OF DATA
'''


def td_records(table=((0, 1), (.5, 3), (1, 2)), *, multiplier=2, steady_mode=1):
    return [node_payload('MAIN', 1, 300, 4, 'capacitive'),
            load_payload(99, 1, time_table=table, multiplier=multiplier, steady_mode=steady_mode)]


def td_preview(root, records=None, units=UNITS):
    from fcst_exchange.independent_td import DwgPreview
    from fcst_exchange.source_tree import capture_project
    from td_fixture import drawing

    (root / 'network.dwg').write_bytes(b'AC1032-owned')
    return DwgPreview(capture_project(root, 'network.dwg'), drawing(records or td_records()), units)
