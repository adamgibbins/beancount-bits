"""Monzo JSON file importer

This importer parses a list of transactions in JSON format obtained from the Monzo API:

https://monzo.com/docs/#list-transactions
/transactions?expand[]=merchant&account_id=$account_id
"""
import json
import re
from os import path

from beancount.ingest import importer
from beancount.core import data, flags
from beancount.core.number import D
from beancount.utils.date_utils import parse_date_liberally

__author__ = 'Adam Gibbins <adam@adamgibbins.com>'
__license__ = 'MIT'


def get_transactions(file):
    if not re.match('.*\.json', path.basename(file.name)):
        return False

    with open(file.name) as data_file:
        return json.load(data_file)['transactions']


def get_unit_price(transaction):
    # local_amount is 0 when the transaction is an active card check,
    # putting a price in for this throws a division by zero error
    if transaction['local_currency'] != transaction['currency'] and transaction['local_amount'] != 0:
        total_local_amount = D(transaction['amount'])
        total_foreign_amount = D(transaction['local_amount'])
        # all prices need to be positive
        unit_price = round(abs(total_foreign_amount / total_local_amount), 5)
        return data.Amount(unit_price, transaction['local_currency'])
    else:
        return None


def get_payee(transaction):
    if transaction['merchant']:
        return transaction['merchant']['name']
    elif 'prefered_name' in transaction['counterparty']:
        return transaction['counterparty']['prefered_name']
    elif 'name' in transaction['counterparty']:
        return transaction['counterparty']['name']
    else:
        return None


def get_narration(transaction):
    if transaction['notes'] != '':
        return transaction['notes']
    elif transaction['scheme'] == 'uk_retail_pot':
        return 'Internal pot transfer'
    elif get_payee(transaction) is None:
        return transaction['description']


class Importer(importer.ImporterProtocol):
    def __init__(self, account_id, account):
        self.account_id = account_id
        self.account = account

    def name(self):
        return '{}: "{}"'.format(super().name(), self.account)

    def identify(self, file):
        transactions = get_transactions(file)

        if transactions:
            account_id = transactions[0]['account_id']

            if account_id:
                return account_id == self.account_id

    def extract(self, file):
        entries = []
        transactions = get_transactions(file)

        for transaction in transactions:

            metadata = {
                'bank_id': transaction['id'],
                'bank_dedupe_id': transaction['dedupe_id'],
                'bank_description': transaction['description'],
                'bank_created_date': transaction['created'],
                'bank_settlement_date': transaction['settled'],
                'bank_updated_date': transaction['updated'],
            }

            if 'account_number' in transaction['counterparty']:
                metadata['counterparty_account_number'] = transaction['counterparty']['account_number']
                metadata['counterparty_sort_code'] = transaction['counterparty']['sort_code']
            elif 'number' in transaction['counterparty']:
                metadata['counterparty_phone_number'] = transaction['counterparty']['number']
                metadata['counterparty_user_id'] = transaction['counterparty']['user_id']

            meta = data.new_metadata(file.name, 0, metadata)

            if transaction['notes'].lower() == 'pin change':
                entries.append(
                    data.Note(meta, parse_date_liberally(transaction['created']), self.account, 'PIN Change')
                )
                continue

            if 'decline_reason' in transaction:
                note = "%s transaction declined with reason %s" % (get_payee(transaction), transaction['decline_reason'])
                entries.append(
                    data.Note(meta, parse_date_liberally(transaction['created']), self.account, note)
                )
                continue

            date = parse_date_liberally(transaction['created'])
            price = get_unit_price(transaction)
            payee = get_payee(transaction)
            narration = get_narration(transaction)

            postings = []
            unit = data.Amount(D(transaction['amount']) / 100, transaction['currency'])
            postings.append(data.Posting(self.account, unit, None, price, None, None))

            # Default to warning as requires human review/categorisation
            flag = flags.FLAG_WARNING
            second_account = 'Expenses:Unknown'
            link = set()

            if transaction['scheme'] == 'uk_retail_pot':
                second_account = self.account
                flag = None
                link = {transaction['metadata']['pot_id']}

            postings.append(data.Posting(second_account, None, None, None, flag, None))

            entries.append(data.Transaction(meta, date, flags.FLAG_OKAY, payee, narration, set(), link, postings))

        return entries

    def file_account(self, file):
        return self.account

    def file_name(self, file):
        return 'json'

    def file_date(self, file):
        transactions = get_transactions(file)
        last = len(transactions) - 1
        return parse_date_liberally(transactions[last]['created'])
