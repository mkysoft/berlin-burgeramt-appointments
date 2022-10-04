from email.utils import localtime
from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup, SoupStrainer
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import asyncio
import csv
import json
import logging
import os
import pytz
import random
import requests
import time

tarih = datetime.strptime("2022-08-21T22:00:00Z", '%Y-%m-%dT%H:%M:%SZ')
tarih = tarih.time
print(tarih)
t0 = datetime(1970, 1, 1, tzinfo=None)
print(t0)
print((tarih - t0).total_seconds())
print(datetime.fromtimestamp())