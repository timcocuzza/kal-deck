from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from backend.sources.common import SourceData
from backend.storage import SnapshotStore
from backend.tracker import TrackerStore, TrackerError, TrackerConflict


def ticket(**changes):
    value = {'title': 'Seattle spread', 'kind': 'single', 'placed_at': '2026-10-15T16:00:00-04:00',
             'cost': '9.99', 'unit_size': '10', 'potential_payout': '20', 'returned': None, 'closed_at': None,
             'notes': '', 'legs': [{'description': 'Seattle wins by over 2.5 points', 'selection': 'Yes',
                                   'market_ticker': 'KXNFLSPREAD-EXAMPLE', 'game_id': '2026_06_SEA_DEN'}]}
    value.update(changes)
    return value


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'local.sqlite3'
        self.store = TrackerStore(self.path)
        self.store.initialize()

    def add(self, value=None):
        return self.store.save(str(uuid4()), value or ticket())

    def test_fractional_stake_and_closed_profit(self):
        opened = self.add()
        self.assertEqual(opened['stake_units'], {'display': '0.999', 'exact': '999/1000', 'rounded': False})
        self.assertIsNone(opened['profit'])
        closed = self.store.save(opened['id'], ticket(returned='20', closed_at='2026-10-16T04:00:00Z'), opened['revision'])
        self.assertEqual(closed['profit'], '10.01')
        self.assertEqual(closed['profit_units']['display'], '1.001')
        self.assertEqual(self.store.report()['totals']['open_count'], 0)

    def test_potential_payout_never_counts_as_realized_profit(self):
        self.add(ticket(potential_payout='10000'))
        result = self.store.report()['totals']
        self.assertEqual(result['profit'], '0'); self.assertEqual(result['profit_units']['exact'], '0')
        self.assertEqual(result['open_cost'], '9.99'); self.assertEqual(result['open_count'], 1)

    def test_default_unit_changes_do_not_change_existing_ticket_or_totals(self):
        self.store.set_unit('10')
        first = self.add(ticket(cost='10', returned='25', closed_at='2026-10-16T04:00:00Z'))
        self.store.set_unit('20')
        self.add(ticket(cost='20', unit_size='20', returned='35', closed_at='2026-10-16T04:00:00Z'))
        report = self.store.report()
        self.assertEqual(report['default_unit_size'], '20')
        self.assertEqual(report['totals']['profit'], '30')
        self.assertEqual(report['totals']['profit_units']['display'], '2.25')
        self.assertEqual(next(t for t in report['tickets'] if t['id'] == first['id'])['unit_size'], '10')
        with self.assertRaises(TrackerError):
            self.store.save(first['id'], ticket(unit_size='20'), first['revision'])

    def test_exact_units_are_summed_before_display_rounding(self):
        for _ in range(3):
            saved = self.add(ticket(cost='1', unit_size='3', returned='2', closed_at='2026-10-16T04:00:00Z'))
        self.assertEqual(saved['profit_units']['display'], '0.333333')
        self.assertTrue(saved['profit_units']['rounded'])
        self.assertEqual(self.store.report()['totals']['profit_units']['display'], '1')
        self.assertFalse(self.store.report()['totals']['profit_units']['rounded'])

    def test_zero_return_refund_and_early_sale_use_actual_cash(self):
        for received, expected in [('0', '-9.99'), ('9.99', '0'), ('7.25', '-2.74'), ('24', '14.01')]:
            with self.subTest(returned=received):
                result = self.add(ticket(returned=received, closed_at='2026-10-16T00:00:00Z'))
                self.assertEqual(result['profit'], expected)
                self.assertEqual(result['status'], 'closed')

    def test_combo_is_one_cost_and_one_return_not_per_leg_totals(self):
        value = ticket(kind='combo', cost='10', returned='40', closed_at='2026-10-16T04:00:00Z')
        value['legs'].append({'description': 'Receiving yards 50+', 'selection': 'No', 'market_ticker': '', 'game_id': ''})
        self.add(value)
        report = self.store.report()
        self.assertEqual(report['totals']['closed_count'], 1)
        self.assertEqual(report['totals']['profit'], '30')
        self.assertEqual(report['totals']['profit_units']['display'], '3')

    def test_exact_money_survives_storage_and_backup_without_floats(self):
        self.add(ticket(cost='9007199254740993.000000000001', unit_size='10', potential_payout=None))
        backup = self.store.export()
        self.assertEqual(backup['tickets'][0]['cost'], '9007199254740993.000000000001')
        self.assertEqual(self.store.report()['totals']['open_cost'], '9007199254740993.000000000001')
        self.assertEqual(TrackerStore(self.path).export()['tickets'], backup['tickets'])

    def test_retried_save_does_not_duplicate_or_increment_revision(self):
        identifier = str(uuid4())
        first = self.store.save(identifier, ticket())
        retry = self.store.save(identifier, ticket())
        self.assertEqual(first, retry)
        closed_data = ticket(returned='20', closed_at='2026-10-16T04:00:00Z')
        closed = self.store.save(identifier, closed_data, 1)
        retried = self.store.save(identifier, closed_data, 1)
        self.assertEqual(closed, retried)
        self.assertEqual(len(self.store.report()['tickets']), 1)

    def test_stale_edit_cannot_overwrite_another_tab(self):
        saved = self.add()
        self.store.save(saved['id'], ticket(notes='Newer correction'), saved['revision'])
        with self.assertRaises(TrackerConflict):
            TrackerStore(self.path).save(saved['id'], ticket(notes='Stale change'), saved['revision'])
        self.assertEqual(self.store.report()['tickets'][0]['notes'], 'Newer correction')

    def test_editing_and_reopening_recalculates_totals(self):
        saved = self.add(ticket(returned='20', closed_at='2026-10-16T04:00:00Z'))
        reopened = self.store.save(saved['id'], ticket(notes='Correcting an accidental close'), saved['revision'])
        self.assertEqual(reopened['status'], 'open')
        self.assertEqual(self.store.report()['totals']['profit'], '0')
        self.assertEqual(self.store.report()['totals']['open_cost'], '9.99')

    def test_bad_money_is_rejected_without_writing(self):
        for field, invalid in [('cost', '-1'), ('cost', '0'), ('cost', 'NaN'), ('cost', '1e3'),
                               ('cost', 9.99), ('cost', True), ('unit_size', '0'),
                               ('potential_payout', '-3'), ('returned', 'Infinity')]:
            with self.subTest(field=field, value=invalid), self.assertRaises(TrackerError):
                self.add(ticket(**{field: invalid}))
        self.assertEqual(self.store.report()['tickets'], [])

    def test_invalid_dates_status_and_leg_counts_are_rejected(self):
        cases = [ticket(placed_at='2026-10-15'), ticket(placed_at='bad'),
                 ticket(placed_at='0001-01-01T00:00:00+23:00'),
                 ticket(returned='20'), ticket(closed_at='2026-10-16T04:00:00Z'),
                 ticket(returned='20', closed_at='2026-10-14T04:00:00Z'),
                 ticket(kind='combo'), ticket(legs=[]), ticket(kind='unknown')]
        wrong_legs = ticket(); wrong_legs['legs'][0]['selection'] = ''; cases.append(wrong_legs)
        unknown = ticket(); unknown['extra'] = 'field'; cases.append(unknown)
        for value in cases:
            with self.assertRaises(TrackerError): self.add(value)
        self.assertEqual(self.store.report()['tickets'], [])

    def test_ticket_and_settings_survive_source_refresh_and_reinitialization(self):
        snapshots = SnapshotStore(self.path); snapshots.initialize()
        self.store.set_unit('10'); self.add()
        before = self.store.export()['tickets']
        snapshots.save('spreads', SourceData([{'example': 'new'}], 'source', '2026-10-15'))
        snapshots.record_failure('schedule:2027', 'Offline')
        self.store.initialize(); snapshots.initialize()
        self.assertEqual(self.store.export()['tickets'], before)
        self.assertEqual(self.store.report()['default_unit_size'], '10')
        self.assertEqual(snapshots.read('spreads').rows, [{'example': 'new'}])

    def test_additive_schema_keeps_existing_source_cache(self):
        path = Path(self.temp.name) / 'existing.sqlite3'
        snapshots = SnapshotStore(path); snapshots.initialize()
        snapshots.save('spreads', SourceData([{'kept': True}], 'source', '2026-10-15'))
        tracker = TrackerStore(path); tracker.initialize()
        self.assertEqual(snapshots.read('spreads').rows, [{'kept': True}])
        self.assertEqual(tracker.report()['tickets'], [])

    def test_export_import_round_trip_and_duplicate_import(self):
        self.store.set_unit('10'); self.add()
        self.add(ticket(returned='0', closed_at='2026-10-16T04:00:00Z'))
        backup = self.store.export()
        other = TrackerStore(Path(self.temp.name) / 'restored.sqlite3'); other.initialize()
        result = other.import_backup(backup)
        self.assertEqual(result['added'], 2)
        self.assertEqual(other.report(), self.store.report())
        self.assertEqual(other.import_backup(backup)['skipped'], 2)
        self.assertEqual(len(other.report()['tickets']), 2)

    def test_deck_exports_accept_legacy_backup_branding(self):
        self.add()
        backup = self.store.export()
        self.assertEqual(backup['format'], 'deck-tracker')
        backup['format'] = 'kalshi-deck-tracker'
        restored = TrackerStore(Path(self.temp.name) / 'legacy.sqlite3')
        restored.initialize()
        restored.import_backup(backup)
        self.assertEqual(restored.report(), self.store.report())

    def test_import_keeps_current_default_and_ticket_units(self):
        self.store.set_unit('10'); self.add(); backup = self.store.export()
        self.store.set_unit('20')
        result = self.store.import_backup(backup)
        self.assertTrue(result['kept_current_unit_size'])
        self.assertEqual(self.store.report()['default_unit_size'], '20')
        self.assertEqual(self.store.report()['tickets'][0]['unit_size'], '10')

    def test_conflict_rolls_back_entire_import_including_earlier_inserts(self):
        original = self.add(); backup = self.store.export()
        new = deepcopy(backup['tickets'][0]); new['id'] = str(uuid4())
        backup['tickets'].insert(0, new)
        self.store.save(original['id'], ticket(notes='Newer saved data'), original['revision'])
        before = self.store.report()
        with self.assertRaises(TrackerConflict): self.store.import_backup(backup)
        self.assertEqual(self.store.report(), before)

    def test_malformed_or_duplicate_backup_never_partially_imports(self):
        self.add(); backup = self.store.export()
        other = TrackerStore(Path(self.temp.name) / 'empty.sqlite3'); other.initialize()
        for mutate in [lambda b: b.update(version=2), lambda b: b.update(version=True),
                       lambda b: b['tickets'].append(deepcopy(b['tickets'][0])),
                       lambda b: b['tickets'].append({}),
                       lambda b: b['tickets'][0].update(cost=9.99),
                       lambda b: b['tickets'][0].update(id='bad')]:
            candidate = deepcopy(backup); mutate(candidate)
            with self.assertRaises(TrackerError): other.import_backup(candidate)
            self.assertEqual(other.report()['tickets'], [])
            self.assertIsNone(other.report()['default_unit_size'])


if __name__ == '__main__':
    unittest.main()
