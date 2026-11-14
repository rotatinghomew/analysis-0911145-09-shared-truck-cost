import unittest
from app.coalitions import quote
from app.tariffs import load_cost
from app.store import load_case


class CostTests(unittest.TestCase):
    def test_empty_coalition_is_free(self):
        self.assertEqual(quote(load_case('standard'), [])['cost_cents'], 0)

    def test_loads_conserve_members_and_cost(self):
        case = load_case('standard')
        identifiers = [member['id'] for member in case['members']]
        result = quote(case, identifiers)
        self.assertTrue(result['feasible'])
        self.assertEqual(sorted(identifier for load in result['loads'] for identifier in load['members']), identifiers)
        self.assertEqual(sum(load['cost_cents'] for load in result['loads']), result['cost_cents'])

    def test_incompatible_members_do_not_share_vehicle(self):
        case = load_case('standard')
        members = [case['members'][2], case['members'][5]]
        self.assertIsNone(load_cost(case, case['fleet'][1], members))

    def test_cooperation_is_not_continuous_per_box_price(self):
        case = load_case('standard')
        together = quote(case, ['a', 'b'])['cost_cents']
        separate = quote(case, ['a'])['cost_cents'] + quote(case, ['b'])['cost_cents']
        self.assertLess(together, separate)
