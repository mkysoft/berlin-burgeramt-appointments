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
import socket

logging.basicConfig(
    datefmt='%Y-%m-%d %H:%M:%S',
    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


try:
    # heroku http server port
    PORT = int(os.environ['PORT'])
    # Berlin.de requires the user agent to include your email
    email = os.environ['BOOKING_TOOL_EMAIL']
    # This allows Berlin.de to distinguish different people running the same tool
    script_id = os.environ['BOOKING_TOOL_ID']
except KeyError:
    logger.exception("You must set the PORT, BOOKING_TOOL_EMAIL and BOOKING_TOOL_ID environment variables.")


timezone = pytz.timezone('Europe/Berlin')
appointments_url = {}
appointments_url['anmeldung'] = 'https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=1&anliegen[]=120686&dienstleisterlist=122210,122217,327316,122219,327312,122227,327314,122231,122243,327348,122252,329742,122260,329745,122262,329748,122254,329751,122271,327278,122273,327274,122277,327276,330436,122280,327294,122282,327290,122284,327292,327539,122291,327270,122285,327266,122286,327264,122296,327268,150230,329760,122301,327282,122297,327286,122294,327284,122312,329763,122314,329775,122304,327330,122311,327334,122309,327332,122281,327352,122279,329772,122276,327324,122274,327326,122267,329766,122246,327318,122251,327320,122257,327322,122208,327298,122226,327300&herkunft=http%3A%2F%2Fservice.berlin.de%2Fdienstleistung%2F120686%2F'
appointments_url['aufenthaltserlaubnis'] = 'https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=1&anliegen[]=324269&dienstleisterlist=122210,122217,122219,122227,122231,122238,122243,122252,122260,122262,122254,122271,122273,122277,122280,122282,122284,122291,122286,122296,150230,122301,122297,122294,122312,122314,122304,122311,122309,122281,122279,122276,122274,122267,122246,122251,122257,122208,122226&herkunft=http%3A%2F%2Fservice.berlin.de%2Fdienstleistung%2F324269%2Fen%2F'
appointments_url['verpflichtungserklarung'] = 'https://service.berlin.de/terminvereinbarung/termin/restart/?providerList=&requestList=120691&scopeId=3061&source=dldb'
appointments_url['umschreibung'] = 'https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=1&anliegen[]=121598&dienstleisterlist=122210,122217,122219,122227,122231,122238,122243,122254,122252,122260,122262,122271,122273,122277,122280,122282,122284,122291,122285,122286,122296,150230,122297,122294,122312,122314,122304,122311,122309,317869,122281,122279,122276,122274,122267,122246,122251,122257,122208,122226&herkunft=http%3A%2F%2Fservice.berlin.de%2Fdienstleistung%2F121598%2F'
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
        'User-Agent': f"Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/111.0",
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
        logger.info(f"Found {len(appointments)} {appointment_type} appointments: {[datetime_to_json(d) for d in appointments]}")
        return {
            'time': datetime_to_json(datetime.now()),
            'status': 200,
            'message': None,
            'appointmentDates': [d for d in appointments],
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
    except (socket.timeout, socket.error, socket.gaierror) as err:
        delay = 360
        logger.warning(f"Got {err.response.status_code} error. Checking in {delay} seconds")
        return {
            'time': datetime_to_json(datetime.now()),
            'status': 503,
            'message': f'Could not fetch results from Berlin.de - Socket error {type(err)} HTTP Code {err.response.status_code}.',
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
            logger.info(f"Appointments requested for: '{appointment_type}'.")
        
        html = "<!DOCTYPE html>"
        html += "<html lang='en'>"
        html += "<html>"
        html += "<head>"
        html += "<title>Berlin bürgeramt appointment finder: " + appointment_type + "</title>"
        html += "<meta charset='utf-8'>"
        html += "</head>"
        html += "<body>"

        if 'appointment_type' in query_components:
            appoitments = look_for_appointments(appointment_type)
            html += f"Stasus: {appoitments['status']} <br />"
            html += f"Message: {appoitments['message']} <br />"
            last_date = timezone.localize(datetime.fromisoformat("2099-01-01"))
            last_date_str = ""
            if 'last_date' in query_components:
                last_date_str = query_components["last_date"][0]
                last_date = timezone.localize(datetime.fromisoformat(last_date_str))
            for appoitment_date in appoitments['appointmentDates']:
                if appoitment_date < last_date: 
                    html += f"Date: {datetime_to_json(appoitment_date)} <br />"
            if len(appoitments['appointmentDates']) == 0:                    
                html += f"There is no appoitment at he momment.<br />"
            html += f"<p>"
            html += f"<form action=\"/\" method=\"get\" >"
            html += f"<input type=\"hidden\" name=\"appointment_type\" value=\"{appointment_type}\" />"
            html += f"<div style=\"display: inline-block\">"
            html += f"<input type=\"date\" name=\"last_date\" value=\"{last_date_str}\" />"
            html += f"<input type=\"submit\" value=\"Filter\" />"
            html += f"</div>"
            html += f"</form>"
            html += f"</p>"
            html += f"<p><a href=\"{appointments_url[appointment_type]}\">Go</a> to original page.</p>"
            #html = json.dumps(appoitments)
        else:
            logger.info('Homepage requested.')
            html += '<a href="?appointment_type=anmeldung">Anmeldung einer Wohnung / Registration of an apartment</a>'
            html += '<br />'
            html += '<a href="?appointment_type=aufenthaltserlaubnis">Residence permit for a foreign child born in Germany - Issuance / Aufenthaltserlaubnis für im Bundesgebiet geborene Kinder - Erteilung</a>'
            html += '<br />'
            html += '<a href="?appointment_type=verpflichtungserklarung">Letter of commitment for a short stay / Verpflichtungserklärung für einen kurzen Aufenthalt Bearbeiten</a>' 
            html += '<br />'
            html += '<a href="?appointment_type=umschreibung">Driving license - transfer of a foreign driving license from a non-EU/EEA country (third country/Annex 11) / Fahrerlaubnis - Umschreibung einer ausländischen Fahrerlaubnis aus einem Nicht-EU/EWR-Land (Drittstaat/Anlage 11)</a>' 

        html += f"<p><a href=\"https://github.com/mkysoft/berlin-burgeramt-appointments\">source code</a></p"
        html += f"<p>"
        html += f"<form action=\"https://www.paypal.com/donate\" method=\"post\" target=\"_top\">"
        html += f"<input type=\"hidden\" name=\"hosted_button_id\" value=\"3XKHPCSKFXSLW\" />"
        html += f"<input type=\"image\" src=\"https://www.paypalobjects.com/en_US/i/btn/btn_donate_SM.gif\" border=\"0\" name=\"submit\" title=\"PayPal - The safer, easier way to pay online!\" alt=\"Donate with PayPal button\" />"
        html += f"<img alt=\"\" border=\"0\" src=\"https://www.paypal.com/en_DE/i/scr/pixel.gif\" width=\"1\" height=\"1\" />"
        html += f"</form>"
        html += f"</p>"
        html += f"<p>You can use this pages with page monitor tools for getting notification on your browser. For example you can use <a href=\"https://chrome.google.com/webstore/detail/page-monitor/ogeebjpdeabhncjpfhgdibjajcajepgg\" target=\"_blank\">Page Monitor</a> extension for the Chrome browser.</p>"
        html += "</body>"
        html += "</html>"

        # Writing the HTML contents with UTF-8
        self.wfile.write(bytes(html, "utf8"))

        return

http_handler_object = HttpRequestHandler
my_http_server = socketserver.TCPServer(("", PORT), http_handler_object)    
# Star the server
my_http_server.serve_forever()
