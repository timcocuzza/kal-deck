"""Permanent, manually entered tickets. No exchange calls or order placement."""

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path
import re
import sqlite3
from uuid import UUID

from .sources.common import utc_now


class TrackerError(ValueError):
    pass


class TrackerConflict(TrackerError):
    pass


def amount(value, label, positive=False, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,12})?', value):
        raise TrackerError(f'{label}: enter a nonnegative dollar amount as plain decimal text (up to 12 decimal places).')
    if positive and Fraction(value) <= 0:
        raise TrackerError(f'{label} must be greater than zero.')
    return money(Fraction(value))


def money(value):
    # All money inputs have terminating decimal representations; do not round them.
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + len(str(value.denominator)) + 20
        text = format(Decimal(value.numerator) / Decimal(value.denominator), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def units(value):
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + len(str(value.denominator)) + 20
        display = format(Decimal(value.numerator) / Decimal(value.denominator), '.6f').rstrip('0').rstrip('.')
    if display == '-0':
        display = '0'
    return {'display': display, 'exact': str(value), 'rounded': Fraction(display) != value}


def text_field(value, label, maximum, optional=False):
    if optional and value is None:
        return ''
    if not isinstance(value, str) or len(value) > maximum or (not optional and not value.strip()):
        raise TrackerError(f'{label} is required and must be at most {maximum} characters.' if not optional
                           else f'{label} must be text of at most {maximum} characters.')
    return value.strip()


def date_field(value, label):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError()
        return date.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, AttributeError, OverflowError):
        raise TrackerError(f'{label} must include a valid date, time and timezone.') from None


def identifier(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise TrackerError('Ticket ID must be a valid UUID.') from None


FIELDS = {'title', 'kind', 'placed_at', 'cost', 'unit_size', 'potential_payout', 'returned', 'closed_at', 'notes', 'legs'}


def validate_ticket(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise TrackerError('Ticket fields are missing or unsupported. Reload the tracker and try again.')
    title = text_field(data['title'], 'Ticket description', 240)
    if data['kind'] not in ('single', 'combo'):
        raise TrackerError('Choose Single or Combo / parlay.')
    legs = data['legs']
    if not isinstance(legs, list) or not 1 <= len(legs) <= 100:
        raise TrackerError('Enter between 1 and 100 selections.')
    if (data['kind'] == 'single' and len(legs) != 1) or (data['kind'] == 'combo' and len(legs) < 2):
        raise TrackerError('A single has one selection; a combo needs at least two legs.')
    validated_legs = []
    for leg in legs:
        if not isinstance(leg, dict) or set(leg) != {'description', 'selection', 'market_ticker', 'game_id'}:
            raise TrackerError('Selection fields are missing or unsupported.')
        validated_legs.append({
            'description': text_field(leg['description'], 'Selection description', 500),
            'selection': text_field(leg['selection'], 'Chosen side / outcome', 120),
            'market_ticker': text_field(leg['market_ticker'], 'Market ticker', 240, True),
            'game_id': text_field(leg['game_id'], 'Game ID', 120, True),
        })
    placed = date_field(data['placed_at'], 'Placed at')
    closed = date_field(data['closed_at'], 'Closed at') if data['closed_at'] is not None else None
    returned = amount(data['returned'], 'Actual total returned', optional=True)
    if (closed is None) != (returned is None):
        raise TrackerError('A closed ticket needs both its closing date and actual total returned. Leave both empty for an open ticket.')
    if closed and datetime.fromisoformat(closed) < datetime.fromisoformat(placed):
        raise TrackerError('Closing date cannot be before placement.')
    return {'title': title, 'kind': data['kind'], 'placed_at': placed,
            'cost': amount(data['cost'], 'Actual total cost', positive=True),
            'unit_size': amount(data['unit_size'], 'Original unit size', positive=True),
            'potential_payout': amount(data['potential_payout'], 'Potential total payout', optional=True),
            'returned': returned, 'closed_at': closed,
            'notes': text_field(data['notes'], 'Notes', 10000, True), 'legs': validated_legs}


def ticket_view(ticket):
    cost, unit = Fraction(ticket['cost']), Fraction(ticket['unit_size'])
    profit = Fraction(ticket['returned']) - cost if ticket['returned'] is not None else None
    return {**ticket, 'status': 'closed' if profit is not None else 'open',
            'stake_units': units(cost / unit), 'profit': money(profit) if profit is not None else None,
            'profit_units': units(profit / unit) if profit is not None else None}


def totals(tickets):
    open_cost = open_units = profit = profit_units = Fraction(0)
    open_count = closed_count = 0
    for ticket in tickets:
        cost, unit = Fraction(ticket['cost']), Fraction(ticket['unit_size'])
        if ticket['returned'] is None:
            open_cost += cost; open_units += cost / unit; open_count += 1
        else:
            result = Fraction(ticket['returned']) - cost
            profit += result; profit_units += result / unit; closed_count += 1
    return {'open_count': open_count, 'closed_count': closed_count, 'open_cost': money(open_cost),
            'open_units': units(open_units), 'profit': money(profit), 'profit_units': units(profit_units)}


class TrackerStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS tracker_settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), default_unit_size TEXT)''')
            connection.execute('INSERT OR IGNORE INTO tracker_settings(singleton) VALUES (1)')
            connection.execute('''CREATE TABLE IF NOT EXISTS tracker_tickets (
                id TEXT PRIMARY KEY, record TEXT NOT NULL, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    @staticmethod
    def _ticket(row):
        return {'id': row[0], **json.loads(row[1]), 'revision': row[2], 'created_at': row[3], 'updated_at': row[4]}

    def raw(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('BEGIN')
            setting = connection.execute('SELECT default_unit_size FROM tracker_settings WHERE singleton=1').fetchone()[0]
            tickets = [self._ticket(row) for row in connection.execute('SELECT * FROM tracker_tickets')]
        tickets.sort(key=lambda t: (t['placed_at'], t['created_at'], t['id']), reverse=True)
        return setting, tickets

    def report(self):
        setting, tickets = self.raw()
        return {'default_unit_size': setting, 'tickets': [ticket_view(t) for t in tickets], 'totals': totals(tickets)}

    def set_unit(self, value):
        value = amount(value, 'Default unit size', positive=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('UPDATE tracker_settings SET default_unit_size=? WHERE singleton=1', (value,))
        return {'default_unit_size': value}

    def save(self, ticket_id, data, revision=None):
        ticket_id = identifier(ticket_id)
        record = validate_ticket(data)
        if revision is not None and (type(revision) is not int or revision < 1):
            raise TrackerError('Ticket revision must be a positive integer.')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM tracker_tickets WHERE id=?', (ticket_id,)).fetchone()
            stamp = utc_now()
            if row:
                old = json.loads(row[1])
                if record == old:
                    return ticket_view(self._ticket(row))  # Safe retry after a lost response.
                if revision != row[2]:
                    raise TrackerConflict('This ticket changed or was already saved. Reload before editing; your saved record was not overwritten.')
                if record['unit_size'] != old['unit_size']:
                    raise TrackerError('A saved ticket keeps its original unit size; changing the default only affects new tickets.')
                connection.execute('UPDATE tracker_tickets SET record=?, revision=revision+1, updated_at=? WHERE id=?',
                                   (json.dumps(record), stamp, ticket_id))
            else:
                if revision is not None:
                    raise TrackerConflict('The ticket being edited no longer exists. Reload before saving.')
                connection.execute('INSERT INTO tracker_tickets VALUES (?, ?, 1, ?, ?)',
                                   (ticket_id, json.dumps(record), stamp, stamp))
            saved = connection.execute('SELECT * FROM tracker_tickets WHERE id=?', (ticket_id,)).fetchone()
        return ticket_view(self._ticket(saved))

    def export(self):
        setting, tickets = self.raw()
        return {'format': 'deck-tracker', 'version': 1, 'exported_at': utc_now(),
                'default_unit_size': setting, 'tickets': tickets}

    def import_backup(self, backup):
        if (not isinstance(backup, dict) or set(backup) != {'format', 'version', 'exported_at', 'default_unit_size', 'tickets'}
                or backup['format'] not in ('deck-tracker', 'kalshi-deck-tracker') or type(backup['version']) is not int or backup['version'] != 1):
            raise TrackerError('This is not a supported Deck tracker backup.')
        date_field(backup['exported_at'], 'Backup date')
        setting = amount(backup['default_unit_size'], 'Backup default unit size', positive=True, optional=True)
        incoming = backup['tickets']
        if not isinstance(incoming, list) or len(incoming) > 50000:
            raise TrackerError('Backup must contain a ticket list (at most 50,000 records).')
        validated, seen = [], set()
        for item in incoming:
            if not isinstance(item, dict) or set(item) != FIELDS | {'id', 'revision', 'created_at', 'updated_at'}:
                raise TrackerError('A backup ticket has missing or unsupported fields.')
            ticket_id = identifier(item['id'])
            if ticket_id in seen:
                raise TrackerError('Backup contains duplicate ticket IDs.')
            seen.add(ticket_id)
            if type(item['revision']) is not int or item['revision'] < 1:
                raise TrackerError('Backup ticket revision is invalid.')
            created, updated = date_field(item['created_at'], 'Creation date'), date_field(item['updated_at'], 'Update date')
            if datetime.fromisoformat(updated) < datetime.fromisoformat(created):
                raise TrackerError('Backup update date precedes its creation date.')
            validated.append((ticket_id, validate_ticket({key: item[key] for key in FIELDS}), item['revision'], created, updated))
        # Validate the entire file first, then merge as one transaction. Never replace existing tickets.
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            added = skipped = 0
            for ticket_id, record, revision, created, updated in validated:
                old = connection.execute('SELECT record FROM tracker_tickets WHERE id=?', (ticket_id,)).fetchone()
                if old:
                    if json.loads(old[0]) != record:
                        raise TrackerConflict(f'Backup conflicts with saved ticket {ticket_id}. Nothing was imported; existing tickets were preserved.')
                    skipped += 1
                else:
                    connection.execute('INSERT INTO tracker_tickets VALUES (?, ?, ?, ?, ?)',
                                       (ticket_id, json.dumps(record), revision, created, updated))
                    added += 1
            current = connection.execute('SELECT default_unit_size FROM tracker_settings WHERE singleton=1').fetchone()[0]
            if current is None and setting is not None:
                connection.execute('UPDATE tracker_settings SET default_unit_size=? WHERE singleton=1', (setting,))
            kept_setting = current is not None and setting != current
        return {'added': added, 'skipped': skipped, 'kept_current_unit_size': kept_setting}
