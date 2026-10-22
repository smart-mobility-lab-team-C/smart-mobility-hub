#!/usr/bin/env python3
"""Check M1 source contracts and geometry; this is not ROS integration evidence."""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def intersects(a, b, rect):
    """Return closed segment/rectangle intersection using slab clipping."""
    low, high = 0.0, 1.0
    for axis, key in enumerate(('x', 'y')):
        delta = b[axis] - a[axis]
        start, end = rect[key]
        if delta == 0:
            if not start <= a[axis] <= end:
                return False
            continue
        enter, leave = sorted(((start - a[axis]) / delta,
                               (end - a[axis]) / delta))
        low, high = max(low, enter), min(high, leave)
        if low > high:
            return False
    return True


def check():
    """Validate transcription, package metadata and approved map contracts."""
    manifest = json.loads((ROOT / 'docs/contracts/m1-fields.json').read_text())
    interface = ROOT / 'src/smart_hub_interfaces'
    actual = {str(p.relative_to(interface)) for kind in ('msg', 'srv', 'action')
              for p in (interface / kind).glob('*.' + kind)}
    assert actual == set(manifest), 'Missing or extra interface files'
    assert [sum(p.startswith(k + '/') for p in actual)
            for k in ('msg', 'srv', 'action')] == [14, 6, 3]
    cmake = (interface / 'CMakeLists.txt').read_text()
    for rel, fields in manifest.items():
        observed = [line.split('#')[0].strip()
                    for line in (interface / rel).read_text().splitlines()]
        assert [line for line in observed if line] == fields, rel
        assert f'"{rel}"' in cmake, rel
    packages = list((ROOT / 'src').glob('*/package.xml'))
    assert len(packages) == 8
    for path in packages:
        package = ET.parse(path).getroot()
        assert package.findtext('name') == path.parent.name
        assert package.find('export/build_type') is not None
    m = json.loads((ROOT / 'src/smart_hub_sim/config/map_m1.yaml').read_text())
    nodes, edges = m['nodes'], m['edges']
    assert not m['directed']
    assert set(nodes) == {'A', 'E', 'N', 'Cn', 'Cs', 'J', 'U', 'B',
                          'R', 'W', 'D', 'P1', 'P2', 'P3'}
    for xy in nodes.values():
        assert all(m['bounds'][key][0] <= xy[i] <= m['bounds'][key][1]
                   for i, key in enumerate(('x', 'y')))
    source_nodes = {'A': [1, 2], 'E': [11, 2], 'B': [8, 4],
                    'R': [3, 6], 'D': [9, 1], 'W': [5, 6],
                    'P1': [8, 6.5], 'P2': [9.5, 6.5], 'P3': [11, 6.5]}
    assert all(nodes[name] == xy for name, xy in source_nodes.items())
    assert m['bounds'] == {'x': [0, 12], 'y': [0, 8]}
    assert m['footprint_radius_m'] == {'robot': 0.2, 'bus': 0.3, 'car': 0.3}
    assert m['zones'] == {'C': {'x': [4.5, 5.5], 'y': [1.25, 4.75]},
                          'Q': {'x': [2, 6], 'y': [5, 7]}}
    assert m['obstacles']['O']['center'] == [7, 2]
    assert m['obstacles']['O']['radius'] == 0.35
    assert nodes['N'] == [1, 4] and nodes['Cn'] == [5, 4]
    assert nodes['Cs'] == [5, 2] and nodes['J'] == [9, 2]
    assert nodes['U'] == [11, 4]
    expected = {
        'bus': 'A-Cs Cs-J J-E A-N N-Cn Cn-B B-U U-E',
        'car': 'A-Cs Cs-J J-E A-N N-Cn Cn-B B-U U-E U-P3 P3-P2 P2-P1',
        'robot': 'R-W W-Cn Cn-Cs Cs-J J-D Cn-B B-U U-E E-J',
    }
    assert len({e['id'] for e in edges}) == len(edges) == 15
    for edge in edges:
        assert len(edge['nodes']) == 2 and len(set(edge['nodes'])) == 2
        assert all(node in nodes for node in edge['nodes'])
        assert edge['id'] == '-'.join(sorted(edge['nodes']))
        assert edge['agents'] and len(edge['agents']) == len(set(edge['agents']))
    for agent, pairs in expected.items():
        required = {frozenset(pair.split('-')) for pair in pairs.split()}
        observed = {frozenset(e['nodes']) for e in edges if agent in e['agents']}
        assert observed == required, agent
        reached = {next(iter(next(iter(required))))}
        while True:
            more = reached | {n for pair in required if pair & reached for n in pair}
            if more == reached:
                break
            reached = more
        assert reached == set().union(*required), agent
    crossing = {e['id'] for e in edges if intersects(
        *(nodes[n] for n in e['nodes']), m['zones']['C'])}
    assert crossing == {'Cn-N', 'B-Cn', 'A-Cs', 'Cs-J', 'Cn-Cs', 'Cn-W'}
    # W-Cn also intersects at Cn; source list says "includes", not exhaustive.
    for route, length in [('A Cs J E', 10), ('A N Cn B U E', 14)]:
        names = route.split()
        assert math.isclose(sum(math.dist(nodes[a], nodes[b])
                                for a, b in zip(names, names[1:])), length)
    assert intersects([0, 3], [10, 3], m['zones']['C'])
    assert not intersects([0, 5], [10, 5], m['zones']['C'])
    assert intersects([4.5, 0], [4.5, 8], m['zones']['C'])
    assert intersects([5, 2], [5, 2], m['zones']['C'])
    print('PASS: 23 interface transcriptions; 8 package metadata files; map bounds,')
    print('permissions, undirected connectivity, 10/14 m routes and crossing geometry')
    print('Crossing edges: ' + ', '.join(sorted(crossing)))


if __name__ == '__main__':
    check()
