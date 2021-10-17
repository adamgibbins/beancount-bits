#!/usr/bin/env python3

import sys
from os import path
sys.path.insert(0, path.join(path.dirname(__file__)))

from importers.monzo_debit import Importer as monzo_debit_importer
from beancount.ingest import extract

account_id = "acc_yourMonzoAccountId"
account = "Assets:Monzo:Something"

CONFIG = [
    monzo_debit_importer(account_id, account),
]


extract.HEADER = ';; -*- mode: org; mode: beancount; coding: utf-8; -*-\n'

