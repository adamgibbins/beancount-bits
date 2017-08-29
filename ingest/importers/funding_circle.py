"""Funding Circle importer

Import transactions exported from https://www.fundingcircle.com/lenders/statement
"""

import re
import csv
import datetime
from os import path

from beancount.ingest import importer
from beancount.core import data, flags
from beancount.core.number import D
from beancount.utils.date_utils import parse_date_liberally

__author__ = 'Adam Gibbins <adam@adamgibbins.com>'
__license__ = 'MIT'


class Importer(importer.ImporterProtocol):
    def __init__(self, account, default_transfer_account, fee_account, interest_account, loan_account):
        self.account = account
        self.default_transfer_account = default_transfer_account
        self.fee_account = fee_account
        self.interest_account = interest_account
        self.loan_account = loan_account

    def name(self):
        return '{}: "{}"'.format(super().name(), self.account)

    def identify(self, file):
        return (
            re.match('^statement_\d\d\d\d-\d\d_\d\d\d\d-\d\d-\d\d_\d\d-\d\d-\d\d.csv$', path.basename(file.name)) and
            re.match('Date,Description,Paid In,Paid Out', file.head())
        )

    def extract(self, file):
        entries = []

        for index, row in enumerate(csv.DictReader(open(file.name))):
            date = parse_date_liberally(row['Date'])
            desc = row['Description']

            if D(row['Paid Out']) > 0:
                amount = D(row['Paid Out']) / -1
            else:
                amount = D(row['Paid In'])

            unit = data.Amount(amount, 'GBP')

            payee = None
            narration = desc
            flag = flags.FLAG_OKAY
            second_account = 'Unknown'

            if re.match('^(EPDQ\+3DS|FC Len Withdrawal)', desc):
                narration = 'Transfer'
                second_account = self.default_transfer_account
            elif re.match('^('
                          'Loan Part|'
                          'Principal repayment|'
                          'Loan offer|'
                          'Early principal repayment|'
                          'Principal recovery repayment'
                          ')', desc):
                second_account = self.loan_account
            elif re.match('^('
                          'Interest repayment|'
                          'Early interest repayment|'
                          'Interest recovery repayment'
                          ')', desc) and amount > 0:
                payee = 'Funding Circle'
                second_account = self.interest_account
            elif re.match('^Servicing fee', desc) and amount < 0:
                payee = 'Funding Circle'
                second_account = self.fee_account
            elif amount > 0:
                flag = flags.FLAG_WARNING
                second_account = 'Income:Unknown'
            elif amount < 0:
                flag = flags.FLAG_WARNING
                second_account = 'Expenses:Unknown'

            if re.findall('Loan Part ID \d+', desc):
                loan_id = re.findall('Loan Part ID \d+', desc)[0].split(' ')[3]
            elif re.findall('loan part \d+', desc):
                loan_id = re.findall('loan part \d+', desc)[0].split(' ')[2]
            else:
                loan_id = None

            if loan_id:
                link = {'loan_' + loan_id}
            else:
                link = set()

            if desc != narration:
                metadata = {'description': desc}
            else:
                metadata = None

            meta = data.new_metadata(file.name, index, metadata)

            postings = [
                data.Posting(self.account, unit, None, None, None, None),
                data.Posting(second_account, None, None, None, None, None)
            ]

            entries.append(data.Transaction(meta, date, flag, payee, narration, set(), link, postings))

        return entries

    def file_account(self, file):
        return self.account

    def file_name(self, file):
        return 'csv'

    def file_date(self, file):
        return datetime.datetime.strptime(path.basename(file.name).split('_')[1], '%Y-%m').date()
