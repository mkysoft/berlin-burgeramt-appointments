# Bürgeramt appointment finder

This server looks for Bürgeramt appointment every few seconds, and serve the results via http. This project based on https://github.com/nicbou/burgeramt-appointments-websockets

## Supported appointment
- Anmeldung einer Wohnung / Registration of an apartment
- Residence permit for a foreign child born in Germany - Issuance / Aufenthaltserlaubnis für im Bundesgebiet geborene Kinder - Erteilung

## Setup

### Standalone

1. Set the required environment variables:
    ```
    export PORT=8080
    export BOOKING_TOOL_EMAIL=your@email.com
    export BOOKING_TOOL_ID=johnsmith-dev
    ```

2. Run the appointment booking tool
    ```
    pip install -r requirements.txt
    python3 appointments.py
    ```

The tool outputs the appointments it finds and the errors to the console, and serve them with http.

### Heroku

A heroku configuration is supplied with the repository.

## Notes

The polling rate is limited to 180 seconds (3 minutes), as required by the Berlin.de IKT-ZMS team (ikt-zms@seninnds.berlin.de).
