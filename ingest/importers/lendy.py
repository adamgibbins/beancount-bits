"""Saving Stream Importer

Import transactions from the export function on https://savingstream.co.uk/account/transactions
"""

import re
import datetime
import csv
from dateutil import parser
from os import path

from beancount.ingest import importer
from beancount.core.number import D
from beancount.core import data, flags

__author__ = 'Adam Gibbins <adam@adamgibbins.com>'
__license__ = 'MIT'


class Importer(importer.ImporterProtocol):
    def __init__(self, cash_account, loan_account, interest_account, transfer_account):
        self.cash_account = cash_account
        self.loan_account = loan_account
        self.interest_account = interest_account
        self.transfer_account = transfer_account

    def name(self):
        return '{}: "{}"'.format(super().name(), self.cash_account)

    def identify(self, file):
        return (
            re.match('^Lendy_Statement_\d\d\d\d\d\d\d\d-\d\d\d\d\d\d\d\d.csv$', path.basename(file.name)) and
            re.match('Txn Date,Transaction type,Loan part ID,Loan part value,Loan part detail,' +
                     'Loan ID,Start date,End date,Txn Amount,Balance', file.head())
        )

    def file_account(self, file):
        return self.cash_account

    def file_name(self, file):
        return 'csv'

    def file_date(self, file):
        return datetime.datetime.strptime(path.basename(file.name).split('-')[1], '%Y%m%d.csv').date()

    def extract(self, file):
        entries = []

        for index, row in enumerate(csv.DictReader(open(file.name))):
            txn_type = row['Transaction type']

            if txn_type == 'Opening Balance' or txn_type == 'Available Balance':
                continue

            flag = flags.FLAG_OKAY
            desc = row['Loan part detail']
            narration = desc

            if txn_type == 'Loan part fund' or txn_type == 'Capital repayment' or txn_type == 'Loan part sale':
                second_account = self.loan_account

            elif txn_type == 'Deposit' or txn_type == 'Withdrawal':
                second_account = self.transfer_account
                narration = 'Transfer'

            elif txn_type == 'Interest':
                second_account = self.interest_account

            else:
                second_account = 'Unknown'
                flag = flags.FLAG_WARNING

            loan_part_id = row['Loan part ID']
            if loan_part_id:
                link = {'loan_' + loan_part_id}
            else:
                link = set()

            postings = [
                data.Posting(self.cash_account, data.Amount(D(row['Txn Amount']), 'GBP'), None, None, None, None),
                data.Posting(second_account, None, None, None, None, None)
            ]

            metadata = {'type': txn_type}
            if row['Start date']:
                metadata['start_date'] = parser.parse(row['Start date'], dayfirst=True).date()
            if row['End date']:
                metadata['end_date'] = parser.parse(row['End date'], dayfirst=True).date()
            if row['Loan part value']:
                metadata['loan_part_value'] = D(row['Loan part value'])

            meta = data.new_metadata(file.name, index, metadata)

            date = parser.parse(row['Txn Date'], dayfirst=True).date()
            entries.append(data.Transaction(meta, date, flag, None, narration, set(), link, postings))

        return entries
