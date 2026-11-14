from functools import lru_cache
from app.tariffs import load_cost
from app.store import unique


def quote(case, subset):
    members = unique(case['members'], 'id')
    selected = sorted(set(subset))
    if any(identifier not in members for identifier in selected):
        raise ValueError('unknown coalition member')
    fleet = case['fleet']
    configurations = {}
    for mask in range(1, 1 << len(selected)):
        load = [members[selected[index]] for index in range(len(selected)) if mask & (1 << index)]
        for vehicle_index, vehicle in enumerate(fleet):
            cost = load_cost(case, vehicle, load)
            if cost is not None:
                configurations[(mask, vehicle_index)] = cost

    @lru_cache(None)
    def search(mask, available):
        if mask == 0:
            return 0, ()
        best = None
        first = mask & -mask
        submask = mask
        while submask:
            if submask & first:
                for vehicle_index, vehicle in enumerate(fleet):
                    price = configurations.get((submask, vehicle_index))
                    if price is None or available[vehicle_index] <= 0:
                        continue
                    remaining = list(available)
                    remaining[vehicle_index] -= 1
                    tail = search(mask ^ submask, tuple(remaining))
                    if tail is not None:
                        candidate = (price['cost_cents'] + tail[0], ((submask, vehicle_index),) + tail[1])
                        if best is None or candidate < best:
                            best = candidate
            submask = (submask - 1) & mask
        return best

    result = search((1 << len(selected)) - 1, tuple(vehicle['available'] for vehicle in fleet))
    if result is None:
        return {'feasible': False, 'cost_cents': None, 'loads': []}
    loads = []
    for mask, vehicle_index in result[1]:
        identifiers = [selected[index] for index in range(len(selected)) if mask & (1 << index)]
        loads.append({'members': identifiers, 'vehicle': fleet[vehicle_index]['id'],
                      **configurations[(mask, vehicle_index)]})
    return {'feasible': True, 'cost_cents': result[0], 'loads': loads}


def preview(case):
    return {'snapshot': case['_snapshot'], 'grand_coalition': quote(case, [member['id'] for member in case['members']]),
            'standalone': {member['id']: quote(case, [member['id']]) for member in case['members']},
            'allocation_not_computed': True}
