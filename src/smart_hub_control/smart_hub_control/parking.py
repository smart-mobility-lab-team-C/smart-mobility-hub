"""Atomic sensor-backed parking state, independent of ROS scheduling."""

import heapq
import math
import threading
import uuid


def entrance_distances(config):
    """Compute nearest available parking by car-network distance from entrance U."""
    graph = {node: [] for node in config['nodes']}
    for edge in config['edges']:
        if 'car' in edge['agents']:
            a, b = edge['nodes']
            length = math.dist(config['nodes'][a], config['nodes'][b])
            graph[a].append((b, length))
            graph[b].append((a, length))
    distances, pending = {'U': 0.}, [(0., 'U')]
    while pending:
        distance, node = heapq.heappop(pending)
        if distance > distances[node]:
            continue
        for neighbor, length in graph[node]:
            candidate = distance + length
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                heapq.heappush(pending, (candidate, neighbor))
    return distances


class Parking:
    """Serialize sensing, expiry and idempotent ownership operations."""

    def __init__(self, slots=('P1', 'P2', 'P3'), distances=None, max_requests=10000):
        """Start with unknown sensing and no administrative owners."""
        self.lock = threading.RLock()
        self.slots = {key: {'sample': None, 'since': None, 'owner': None}
                      for key in slots}
        self.requests = {}
        self.distances = distances or {'P1': 5.5, 'P2': 4.0, 'P3': 2.5}
        self.max_requests = max_requests

    def observe(self, observations, now):
        """Debounce valid occupancy; omitted and invalid sensors become unknown."""
        with self.lock:
            for key, slot in self.slots.items():
                value = observations.get(key)
                old = slot['sample']
                if (value is None or old is None or old[0] != value
                        or now - old[1] > 1.0):
                    slot['since'] = now
                slot['sample'] = None if value is None else (value, now)

    def snapshot(self, now):
        """Expire only ownership, never infer vacancy from administrative expiry."""
        with self.lock:
            result = {}
            for key, slot in self.slots.items():
                owner = slot['owner']
                if owner and now >= owner[2]:
                    slot['owner'] = owner = None
                sample = slot['sample']
                valid = (sample is not None and 0 <= now - sample[1] <= 1.0
                         and sample[1] - slot['since'] >= 0.5)
                state = 'UNKNOWN'
                if valid:
                    state = 'OCCUPIED' if sample[0] else ('RESERVED' if owner else 'FREE')
                result[key] = (state, owner)
            return result

    def reserve(self, request_id, vehicle, preferred, ttl, now):
        """Return immutable retry results and enforce one slot per vehicle."""
        with self.lock:
            payload = (vehicle, preferred, ttl)
            cache_key = ('reserve', request_id)
            if cache_key in self.requests:
                old, result = self.requests[cache_key]
                return result if old == payload else (False, '', '', 0., 'ID_CONFLICT')
            if len(self.requests) >= self.max_requests:
                return (False, '', '', 0., 'REQUEST_CAPACITY_RESET_REQUIRED')
            result = (False, '', '', 0., 'INVALID_REQUEST')
            states = self.snapshot(now)
            if (request_id and vehicle and math.isfinite(ttl) and 5 <= ttl <= 120
                    and (not preferred or preferred in self.slots)):
                result = (False, '', '', 0., 'NO_CAPACITY')
                if any(owner and owner[0] == vehicle for _, owner in states.values()):
                    result = (False, '', '', 0., 'VEHICLE_ALREADY_RESERVED')
                else:
                    choices = sorted(states, key=lambda key: (
                        key != preferred, self.distances.get(key, math.inf), key))
                    for key in choices:
                        if states[key][0] == 'FREE':
                            token = uuid.uuid4().hex
                            expiry = now + ttl
                            self.slots[key]['owner'] = (vehicle, token, expiry)
                            result = (True, token, key, expiry, 'RESERVED')
                            break
            if request_id:
                self.requests[cache_key] = (payload, result)
            return result

    def release(self, request_id, token, vehicle, now):
        """Require live matching ownership and preserve occupied sensing."""
        with self.lock:
            key = ('release', request_id)
            payload = (token, vehicle)
            if key in self.requests:
                old, result = self.requests[key]
                return result if old == payload else (False, 'ID_CONFLICT')
            if len(self.requests) >= self.max_requests:
                return (False, 'REQUEST_CAPACITY_RESET_REQUIRED')
            self.snapshot(now)
            result = (False, 'INVALID_OWNER')
            if request_id and token and vehicle:
                for slot in self.slots.values():
                    owner = slot['owner']
                    if owner and owner[:2] == (vehicle, token):
                        slot['owner'] = None
                        result = (True, 'RELEASED')
                        break
                self.requests[key] = (payload, result)
            return result
