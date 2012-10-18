#!/usr/bin/env python


import argparse
import json
import urllib
from pprint import pprint
from twisted.internet import reactor

from libsaas.executors import base, twisted_executor
base.use_executor(twisted_executor.TwistedExecutor(None, True))
from libsaas.services import ducksboard, twilio

from autobahn.websocket import (connectWS, WebSocketClientFactory,
                                WebSocketClientProtocol)


TWIML_URL = 'http://aitorciki.net:8080/?message={0}'


def parse_arguments():
    description = ('Uh... kind of notifies stuff through Twilio '
                   'based on Ducksboard updates')
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('-a', '--api_key', required=True,
                        help='your Ducksboard API key, please')
    parser.add_argument('-w', '--widget_id', required=True,
                        help='the data source to track')
    parser.add_argument('-s', '--sid', required=True,
                        help='Twilio SID')
    parser.add_argument('-t', '--token', required=True,
                        help='Twilio auth token')
    parser.add_argument('--from', dest='from_', required=True,
                        help='Twilio number to send SMS/call from')
    parser.add_argument('--to', required=True,
                        help='Twilio number to send SMS/call to')

    return parser.parse_args()


def get_data_source_id(api_key, widget_id):
    dc = ducksboard.Ducksboard(api_key)
    d = dc.widget(widget_id).get()
    return d.addCallback(lambda r: r['slots']['1']['label'])


def start_tracker(data_source_id, args):
    twilio_client = twilio.Twilio(args.sid, args.token)

    tracker =  DucksboardTracker(
        data_source_id, twilio_client, args.sid, args.from_, args.to)

    factory = DucksboardWebSocketClientFactory(
        args.api_key, tracker, 'wss://api.ducksboard.com/websocket')
    factory.protocol = DucksboardNotificationProtocol
    connectWS(factory)


class DucksboardWebSocketClientFactory(WebSocketClientFactory):

    def __init__(self, api_key, tracker, *args, **kwargs):
        self.api_key = api_key
        self.tracker = tracker
        WebSocketClientFactory.__init__(self, *args, **kwargs)


class DucksboardNotificationProtocol(WebSocketClientProtocol):

    def send_message(self, message):
        msg = json.dumps(message)
        print msg
        self.sendMessage(msg)

    def login(self):
        msg = {
            'message': 'login',
            'api_key': self.factory.api_key,
            'timezone': 'America/Los_Angeles'
        }
        self.send_message(msg)

    def subscribe(self, msg):
        msg = {
            'message': 'subscribe',
            'label': self.factory.tracker.data_source_id
        }
        self.send_message(msg)

    def alert(self, msg):
        self.factory.tracker.alert(msg['data'])

    def onOpen(self):
        self.login()

    def onMessage(self, msg, binary):
        handlers = {
            'welcome': self.subscribe,
            'data': self.alert,
            'subscribed': lambda _: None,
            'unsubscribed': lambda _: None,
            'fetched': lambda _: None,
            'tick': lambda _: None
        }

        print 'Ducksboard talked! {0}'.format(json.loads(msg))
        msg = json.loads(msg)
        handler = handlers.get(msg['message'])
        handler(msg)


class DucksboardTracker(object):

    def __init__(self, data_source_id, twilio_client, twilio_sid, from_, to):
        self.data_source_id = data_source_id
        self.ta = twilio_client.account(twilio_sid)
        self.from_ = from_
        self.to = to

    def alert(self, data):
        self.send_sms(data['value']['content'])
        self.make_call(data['value']['content'])

    def send_sms(self, body):
        d = self.ta.sms().messages().create({
            'From': self.from_,
            'To': self.to,
            'Body': body
        })
        d.addCallback(lambda r: pprint(r))

    def make_call(self, message):
        d = self.ta.calls().create({
            'From': self.from_,
            'To': self.to,
            'Url': TWIML_URL.format(urllib.quote(message))
        })
        d.addCallback(lambda r: pprint(r))



if __name__ == '__main__':
    args = parse_arguments()

    d = get_data_source_id(args.api_key, args.widget_id)
    d.addCallback(start_tracker, args)

    reactor.run()
