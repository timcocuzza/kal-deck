from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from backend.catalog import RefreshService
from backend.college import college_matchups, college_rankings, reconcile_college_schedule
from backend.college_markets import attach_college_markets, college_team_links, TEAM_ALIASES
from backend.sources.college_schedule import parse_week, load_current_schedule
from backend.sources.college_markets import load_college_markets
from backend.sources.common import Resource, SourceData, SourceError
from backend.storage import SnapshotStore

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
HOME = '00000000-0000-0000-0000-000000000001'
AWAY = '00000000-0000-0000-0000-000000000002'
EVENT = 'KXNCAAFSPREAD-26OCT24BYUUCF'


def baseline():
    return {'game_id': '123', 'season': '2026', 'week': '8', 'season_type': 'regular',
            'home_id': '2116', 'away_id': '252', 'home_team': 'UCF', 'away_team': 'BYU',
            'home_division': 'fbs', 'away_division': 'fbs', 'fbs_game': 'true', 'fbs_participant': 'true',
            'start_date': '2026-10-24T04:00:00Z', 'start_time_tbd': 'true', 'neutral_site': 'false', 'completed': 'false'}


def espn():
    status = {'type': {'name': 'STATUS_SCHEDULED', 'state': 'pre', 'completed': False}}
    teams = [{'id': tid, 'homeAway': side, 'score': '0',
              'team': {'id': tid, 'displayName': full, 'location': name, 'abbreviation': name, 'shortDisplayName': name}}
             for tid, side, full, name in [('2116', 'home', 'UCF Knights', 'UCF'), ('252', 'away', 'BYU Cougars', 'BYU')]]
    event = {'id': '123', 'date': '2026-10-24T19:30Z', 'season': {'year': 2026, 'type': 2}, 'week': {'number': 8},
             'status': deepcopy(status), 'competitions': [{'id': '123', 'date': '2026-10-24T19:30Z', 'timeValid': True,
             'dateValid': True, 'neutralSite': False, 'status': status, 'competitors': teams}]}
    return {'season': {'year': 2026, 'type': 2}, 'week': {'number': 8}, 'events': [event]}


def current(data=None):
    return parse_week(data or espn(), 2026, 8, {'123': baseline()}, {'2116': 'fbs', '252': 'fbs'})


def market_bundle():
    targets = [{'id': uid, 'name': name, 'type': 'football_team', 'details': {
        'league': 'NCAAFB', 'division': 'FBS', 'team_name': full, 'abbreviation': name, 'market': name}}
        for uid, name, full in [(HOME, 'UCF', 'UCF Knights'), (AWAY, 'BYU', 'BYU Cougars')]]
    milestone = {'id': '00000000-0000-0000-0000-000000000003', 'type': 'football_game',
                 'start_date': '2026-10-24T15:30:00-04:00', 'related_event_tickers': [EVENT], 'primary_event_tickers': [EVENT],
                 'details': {'league': 'NCAAFB', 'division': 'FBS', 'status': 'scheduled', 'home_team_id': HOME, 'away_team_id': AWAY,
                             'season': {'year': 2026, 'type': 'REG', 'week': 8}}}
    market = {'ticker': EVENT + '-BYU8', 'event_ticker': EVENT, 'market_type': 'binary', 'status': 'active',
              'custom_strike': {'football_team': AWAY}, 'strike_type': 'greater', 'floor_strike': 7.5,
              'title': 'BYU wins by over 7.5 points', 'yes_sub_title': 'BYU wins by over 7.5 points',
              'yes_bid_dollars': '0.47', 'yes_ask_dollars': '0.48', 'volume_fp': '100',
              'rules_primary': 'If BYU wins by more than 7.5 points in the BYU vs UCF college football game originally scheduled for Oct 24, 2026, then the market resolves to Yes.',
              'rules_secondary': 'Postponement terms.'}
    return {'targets': targets, 'milestones': [milestone], 'markets': [market]}


def report(schedule=None, markets=None):
    schedule = current() if schedule is None else schedule
    result = college_matchups({'schedule': schedule}, 2026, week=8, now=NOW)
    return attach_college_markets(result, schedule, market_bundle() if markets is None else markets, 2026)


class CurrentScheduleTests(unittest.TestCase):
    def test_confirmed_kickoff_replaces_placeholder_but_not_statistics(self):
        original = {'schedule': [baseline()], 'adv_team': [{'unchanged': True}]}
        merged, warnings = reconcile_college_schedule(original, current())
        self.assertFalse(warnings)
        self.assertEqual(merged['schedule'][0]['start_date'], '2026-10-24T19:30Z')
        self.assertIs(merged['adv_team'], original['adv_team'])
        self.assertEqual(original['schedule'][0]['start_time_tbd'], 'true')

    def test_zero_scores_are_not_finals_and_live_games_are_hidden(self):
        data = espn()
        self.assertEqual(current(data)[0]['completed'], 'false')
        for name, state, completed in [('STATUS_IN_PROGRESS', 'in', False), ('STATUS_END_PERIOD', 'in', False), ('STATUS_FINAL', 'post', True), ('STATUS_CANCELED', 'post', False)]:
            data = espn()
            for obj in [data['events'][0], data['events'][0]['competitions'][0]]:
                obj['status']['type'].update(name=name, state=state, completed=completed)
            self.assertEqual(report(current(data))['games'], [])

    def test_tbd_postponed_and_neutral_site(self):
        data = espn(); data['events'][0]['competitions'][0]['timeValid'] = False
        self.assertEqual(report(current(data))['games'][0]['markets'], [])
        data = espn(); data['events'][0]['competitions'][0]['neutralSite'] = True
        self.assertTrue(report(current(data))['games'][0]['neutral'])
        data = espn()
        for obj in [data['events'][0], data['events'][0]['competitions'][0]]:
            obj['status']['type']['name'] = 'STATUS_POSTPONED'
        self.assertEqual(report(current(data))['games'][0]['markets'], [])

    def test_missing_or_conflicting_source_fields_fail_closed(self):
        mutations = [lambda d: d['week'].update(number=7),
                     lambda d: d['events'].append(deepcopy(d['events'][0])),
                     lambda d: d['events'][0]['competitions'][0].pop('timeValid'),
                     lambda d: d['events'][0]['competitions'][0]['competitors'][0].update(homeAway='away'),
                     lambda d: d['events'][0]['status']['type'].update(completed=True),
                     lambda d: d['events'][0]['competitions'][0]['competitors'][0]['team'].update(id='999')]
        for change in mutations:
            data = espn(); change(data)
            with self.assertRaises(SourceError): current(data)

    def test_placeholder_participants_remain_unmatchable(self):
        data = espn(); event = data['events'][0]; event['id'] = '999'
        comp = event['competitions'][0]; comp['id'] = '999'
        comp['competitors'][1].update(id='-2', team={'id': '-2', 'displayName': 'TBD'})
        rows = current(data)
        self.assertFalse(rows[0]['participants_confirmed'])
        self.assertEqual(report(rows)['games'][0]['markets'], [])

    def test_new_final_increases_expected_coverage_without_invented_statistics(self):
        from test_college import bundle
        data = bundle()
        new_final = {**data['schedule'][-1], 'completed': 'true', 'start_date': '2026-10-23T19:30Z'}
        merged, _ = reconcile_college_schedule(data, [new_final])
        ranks = college_rankings(merged, 2026, now=NOW)
        metric = ranks['teams']['1']['categories']['passing_offense']
        self.assertEqual((metric['games_used'], metric['games_expected']), (2, 3))
        self.assertEqual(ranks['missing_completed_games'], 1)
        self.assertNotEqual(ranks['latest_completed_kickoff'], new_final['start_date'])

    def test_truncated_week_preserves_saved_snapshot(self):
        def fetch(url):
            week = int(parse_qs(urlsplit(url).query)['week'][0])
            data = espn(); data['week']['number'] = week; data['events'] = []
            return Resource(json.dumps(data).encode(), url, NOW.isoformat())
        with tempfile.TemporaryDirectory() as folder:
            store = SnapshotStore(Path(folder) / 'db'); store.initialize()
            store.save('cfb_research:2026', SourceData([{'schedule': [baseline()]}], 'test', NOW.isoformat()))
            store.save('cfb_schedule:2026', SourceData(current(), 'test', NOW.isoformat()))
            result = RefreshService(store, fetch).refresh('cfb_schedule', 2026)
            self.assertEqual(result['status'], 'refresh_failed')
            self.assertIn('omitted', result['error'])
            self.assertEqual(store.read('cfb_schedule:2026').rows, current())


class CollegeMarketTests(unittest.TestCase):
    def test_verified_market_default_price_and_secondary_rules(self):
        result = report(); self.assertEqual(result['issues'], [])
        game = result['games'][0]
        self.assertEqual(game['default_market_ticker'], EVENT + '-BYU8')
        self.assertEqual(game['markets'][0]['midpoint'], .475)
        self.assertEqual(game['markets'][0]['yes_ask_dollars'], '0.48')
        self.assertEqual(game['markets'][0]['rules_secondary'], 'Postponement terms.')

    def test_clock_hides_game_regardless_of_open_contract(self):
        result = college_matchups({'schedule': current()}, 2026, now=datetime(2026, 10, 24, 19, 30, tzinfo=timezone.utc))
        self.assertEqual(attach_college_markets(result, current(), market_bundle(), 2026)['games'], [])

    def test_bulk_schedule_alone_never_attaches_quotes(self):
        self.assertEqual(report([baseline()])['games'][0]['markets'], [])

    def test_identity_and_contract_conflicts_withhold_quotes(self):
        mutations = [lambda b: b['milestones'][0].update(start_date='2026-10-24T20:30Z'),
                     lambda b: b['milestones'][0]['details'].update(home_team_id=AWAY, away_team_id=HOME),
                     lambda b: b['milestones'][0]['details']['season'].update(week=9),
                     lambda b: b['milestones'][0]['details']['season'].update(year=2025),
                     lambda b: b['milestones'][0]['details'].update(league='NFL'),
                     lambda b: b['milestones'].append(deepcopy(b['milestones'][0])),
                     lambda b: b['targets'][0]['details'].update(division='FCS'),
                     lambda b: b['targets'][0]['details'].update(abbreviation='BYU'),
                     lambda b: b['markets'][0].update(status='closed'),
                     lambda b: b['markets'][0].update(floor_strike=8.5),
                     lambda b: b['markets'][0].update(rules_primary='Unrecognized settlement rules'),
                     lambda b: b['markets'][0].update(custom_strike={'football_team': HOME})]
        for change in mutations:
            data = market_bundle(); change(data)
            result = report(markets=data)
            self.assertEqual(result['games'][0]['markets'], [])
            self.assertTrue(result['issues'])

    def test_missing_quotes_selectable_and_malformed_contract_does_not_hide_valid(self):
        data = market_bundle(); data['markets'][0]['yes_bid_dollars'] = '0'
        game = report(markets=data)['games'][0]
        self.assertEqual(len(game['markets']), 1); self.assertIsNone(game['default_market_ticker'])
        data = market_bundle(); bad = deepcopy(data['markets'][0]); bad.update(ticker=EVENT + '-BAD', custom_strike=None)
        data['markets'].append(bad)
        self.assertEqual(len(report(markets=data)['games'][0]['markets']), 1)

    def test_multiple_events_for_one_game_are_not_guessed(self):
        data = market_bundle(); other = deepcopy(data['milestones'][0]); other['id'] = 'another'
        second = EVENT + 'OTHER'; other.update(related_event_tickers=[second], primary_event_tickers=[second])
        data['milestones'].append(other)
        data['markets'].append({**data['markets'][0], 'event_ticker': second, 'ticker': second + '-BYU8'})
        self.assertEqual(report(markets=data)['games'][0]['markets'], [])

    def test_alias_is_bound_to_verified_names_id_and_abbreviation(self):
        for uid, (tid, kalshi_name, espn_name, code) in TEAM_ALIASES.items():
            schedule = current(); schedule[0].update(home_id=tid, home_full_name=espn_name, home_team=espn_name, home_short_name=espn_name, home_abbreviation=code)
            target = {'id': uid, 'type': 'football_team', 'name': kalshi_name, 'details': {'division': 'FBS', 'league': 'NCAAFB', 'team_name': kalshi_name, 'abbreviation': code}}
            self.assertEqual(college_team_links(schedule, [target])[0], {uid: tid})
            target['details']['team_name'] = 'Changed school'
            self.assertEqual(college_team_links(schedule, [target])[0], {})

    def test_market_reader_checks_league_and_retains_snapshot_on_failure(self):
        def fetch(url):
            b = market_bundle(); path = urlsplit(url).path
            data = {'markets': b['markets']} if path.endswith('/markets') else {'structured_targets': b['targets']} if path.endswith('/structured_targets') else {'milestones': b['milestones']}
            return Resource(json.dumps(data).encode(), url, NOW.isoformat())
        result = load_college_markets(2026, fetch)
        self.assertEqual(result.rows[0], market_bundle())
        def bad(url):
            r = fetch(url)
            if '/milestones?' in url:
                payload = json.loads(r.body); payload['milestones'][0]['details']['league'] = 'NFL'
                r.body = json.dumps(payload).encode()
            return r
        with tempfile.TemporaryDirectory() as folder:
            store = SnapshotStore(Path(folder) / 'db'); store.initialize(); store.save('cfb_markets:2026', result)
            self.assertEqual(RefreshService(store, bad).refresh('cfb_markets', 2026)['status'], 'refresh_failed')
            self.assertEqual(store.read('cfb_markets:2026').rows, result.rows)

    def test_fcs_only_events_in_shared_series_are_excluded(self):
        def fetch(url):
            b = market_bundle(); path = urlsplit(url).path
            b['milestones'][0]['details']['division'] = 'FCS'
            payload = {'markets': b['markets']} if path.endswith('/markets') else {'structured_targets': b['targets']} if path.endswith('/structured_targets') else {'milestones': b['milestones']}
            return Resource(json.dumps(payload).encode(), url, NOW.isoformat())
        result = load_college_markets(2026, fetch)
        self.assertEqual(result.rows[0]['markets'], [])
        self.assertEqual(result.rows[0]['milestones'], [])
        self.assertEqual(result.context['excluded_non_fbs_events'], 1)


if __name__ == '__main__': unittest.main()
