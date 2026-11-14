def load_cost(case, vehicle, members):
    if not members or len({member['lane'] for member in members}) != 1:
        return None
    identifiers = {member['id'] for member in members}
    if any(identifiers.intersection(member['incompatible']) for member in members):
        return None
    boxes = sum(member['boxes'] for member in members)
    weight = sum(member['kg'] for member in members)
    if boxes > vehicle['max_boxes'] or weight > vehicle['max_kg']:
        return None
    tariff = next((row for row in case['tariffs'] if row['vehicle'] == vehicle['id'] and row['lane'] == members[0]['lane']), None)
    if tariff is None:
        return None
    qualifies = (tariff['eligible_green'] and all(member['fresh'] for member in members) and
                 boxes >= case['green_min_fill'] * vehicle['max_boxes'])
    return {'cost_cents': tariff['base_cents'] + (0 if qualifies else tariff['toll_cents']),
            'green': qualifies, 'boxes': boxes, 'kg': weight}
