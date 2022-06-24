from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup, SoupStrainer
from datetime import datetime, date, timedelta
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
import http.server
import socketserver

logging.basicConfig(
    datefmt='%Y-%m-%d %H:%M:%S',
    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


try:
    PORT = int(os.environ['PORT'])
    #PORT = 8080

    # Berlin.de requires the user agent to include your email
    #email = os.environ['BOOKING_TOOL_EMAIL']
    email = 'mkysoft@gmail.com'
    # This allows Berlin.de to distinguish different people running the same tool
    #script_id = os.environ['BOOKING_TOOL_ID']
    script_id = 'mkysoft-dev'
except KeyError:
    logger.exception("You must set the BOOKING_TOOL_EMAIL and BOOKING_TOOL_ID environment variables.")


timezone = pytz.timezone('Europe/Berlin')
appointments_url = {}
appointments_url['anmeldung'] = 'https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=1&anliegen[]=120686&dienstleisterlist=122210,122217,327316,122219,327312,122227,327314,122231,122243,327348,122252,329742,122260,329745,122262,329748,122254,329751,122271,327278,122273,327274,122277,327276,330436,122280,327294,122282,327290,122284,327292,327539,122291,327270,122285,327266,122286,327264,122296,327268,150230,329760,122301,327282,122297,327286,122294,327284,122312,329763,122314,329775,122304,327330,122311,327334,122309,327332,122281,327352,122279,329772,122276,327324,122274,327326,122267,329766,122246,327318,122251,327320,122257,327322,122208,327298,122226,327300&herkunft=http%3A%2F%2Fservice.berlin.de%2Fdienstleistung%2F120686%2F'
appointments_url['aufenthaltserlaubnis'] = 'https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=1&anliegen[]=324269&dienstleisterlist=122210,122217,122219,122227,122231,122238,122243,122252,122260,122262,122254,122271,122273,122277,122280,122282,122284,122291,122286,122296,150230,122301,122297,122294,122312,122314,122304,122311,122309,122281,122279,122276,122274,122267,122246,122251,122257,122208,122226&herkunft=http%3A%2F%2Fservice.berlin.de%2Fdienstleistung%2F324269%2Fen%2F'
delay = 180  # Minimum allowed by Berlin.de's IKT-ZMS team


def datetime_to_json(datetime_obj):
    return datetime_obj.strftime('%Y-%m-%dT%H:%M:%SZ')


connected_clients = []
last_message = {
    'time': datetime_to_json(datetime.now()),
    'status': 200,
    'appointmentDates': [],
    'connectedClients': len(connected_clients)
}


def get_appointments(appointment_type):
    today = timezone.localize(datetime.now())
    next_month = timezone.localize(datetime(today.year, today.month % 12 + 1, 1))
    next_month_timestamp = int(next_month.timestamp())

    session = requests.Session()
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': f"Mozilla/5.0 AppointmentBookingTool/1.1 (https://github.com/mkysoft/berlin-burgeramt-appointments; {email}; {script_id})",
        'Accept-Language': 'en-gb',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    }

    # Load the first two months
    response_p1 = session.get(appointments_url[appointment_type], headers=headers)
    response_p1.raise_for_status()
    time.sleep(1)

    # Load the next two months
    response_p2 = session.get(
        f'https://service.berlin.de/terminvereinbarung/termin/day/{next_month_timestamp}/',
        headers=headers
    )
    response_p2.raise_for_status()

    return sorted(list(set(parse_appointment_dates(response_p1.text) + parse_appointment_dates(response_p2.text))))


def parse_appointment_dates(page_content):
    appointment_strainer = SoupStrainer('a', title='An diesem Tag einen Termin buchen')
    bookable_cells = BeautifulSoup(page_content, 'lxml', parse_only=appointment_strainer).find_all('a')
    appointment_dates = []
    for bookable_cell in bookable_cells:
        timestamp = int(bookable_cell['href'].rstrip('/').split('/')[-1])
        appointment_dates.append(timezone.localize(datetime.fromtimestamp(timestamp)))

    return appointment_dates


def look_for_appointments(appointment_type):
    global delay
    try:
        appointments = get_appointments(appointment_type)
        delay = 180
        logger.info(f"Found {len(appointments)} appointments: {[datetime_to_json(d) for d in appointments]}")
        return {
            'time': datetime_to_json(datetime.now()),
            'status': 200,
            'message': None,
            'appointmentDates': [datetime_to_json(d) for d in appointments],
        }
    except requests.HTTPError as err:
        delay = 360
        logger.warning(f"Got {err.response.status_code} error. Checking in {delay} seconds")
        return {
            'time': datetime_to_json(datetime.now()),
            'status': 502,
            'message': f'Could not fetch results from Berlin.de - Got HTTP {err.response.status_code}.',
            'appointmentDates': [],
        }
    except Exception as err:
        logger.exception("Could not fetch results due to an unexpected error.")
        return {
            'time': datetime_to_json(datetime.now()),
            'status': 500,
            'message': f'An unknown error occured: {str(err)}',
            'appointmentDates': [],
        }

class HttpRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Sending an '200 OK' response
        self.send_response(200)

        # Setting the header
        self.send_header("Content-type", "text/html")

        # Whenever using 'send_header', you also have to call 'end_headers'
        self.end_headers()

        # Extract query param
        appointment_type = 'aufenthaltserlaubnis'
        query_components = parse_qs(urlparse(self.path).query)
        if 'appointment_type' in query_components:
            appointment_type = query_components["appointment_type"][0]

        # Some custom HTML code, possibly generated by another function
        html = look_for_appointments(appointment_type)

        # Writing the HTML contents with UTF-8
        self.wfile.write(bytes(json.dumps(html), "utf8"))

        return

http_handler_object = HttpRequestHandler
my_http_server = socketserver.TCPServer(("", PORT), http_handler_object)    
# Star the server
my_http_server.serve_forever()
