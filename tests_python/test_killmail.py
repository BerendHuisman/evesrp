from __future__ import absolute_import
from unittest import TestCase
from decimal import Decimal
import json
from httmock import HTTMock, all_requests, urlmatch
from evesrp import killmail
from .util_tests import TestApp, all_mocks, response
from .test_systems import jita_lookup, kimotoro_lookup, forge_lookup


class TestKillmail(TestCase):

    def test_default_values(self):
        km = killmail.Killmail()
        attrs = (u'kill_id', u'ship_id', u'ship', u'pilot_id', u'pilot',
            u'corp_id', u'corp', u'alliance_id', u'alliance', u'verified',
            u'url', u'value', u'timestamp', u'system', u'constellation',
            u'region')
        for attr in attrs:
            self.assertIsNone(getattr(km, attr))

    def test_hidden_data(self):
        km = killmail.Killmail()
        old_dir = dir(km)
        km.foo = 'bar'
        new_dir = dir(km)
        self.assertEqual(old_dir, new_dir)
        self.assertIn(u'foo', km._data)
        self.assertEqual(km.foo, 'bar')

    def test_keyword_arguments(self):
        km = killmail.Killmail(kill_id=123456)
        self.assertEqual(km.kill_id, 123456)


class TestNameMixin(TestCase):

    def setUp(self):
        self.NameMixed = type('NameMixed', (killmail.Killmail,
                killmail.ShipNameMixin), dict())

    def test_devoter_id(self):
        km = self.NameMixed(ship_id=12017)
        self.assertEqual(km.ship, u'Devoter')


class TestLocationMixin(TestApp):

    def setUp(self):
        super(TestLocationMixin, self).setUp()
        self.LocationMixed = type('LocationMixed', (killmail.Killmail,
                killmail.LocationMixin), dict())

    def test_system(self):
        with self.app.test_request_context():
            with HTTMock(jita_lookup, kimotoro_lookup, forge_lookup):
                km = self.LocationMixed(system_id=30000142)
                self.assertEqual(km.system, u'Jita')

    def test_constellation(self):
        with self.app.test_request_context():
            with HTTMock(jita_lookup, kimotoro_lookup, forge_lookup):
                km = self.LocationMixed(system_id=30000142)
                self.assertEqual(km.constellation, u'Kimotoro')

    def test_region(self):
        with self.app.test_request_context():
            with HTTMock(jita_lookup, kimotoro_lookup, forge_lookup):
                km = self.LocationMixed(system_id=30000142)
                self.assertEqual(km.region, u'The Forge')


class TestRequestsMixin(TestCase):

    def setUp(self):
        self.SessionMixed = type('SessionMixed', (killmail.Killmail,
                killmail.RequestsSessionMixin), dict())

    def test_default_creation(self):
        km = self.SessionMixed()
        self.assertIsNotNone(km.requests_session)

    def test_provided_session(self):
        session = object()
        km = self.SessionMixed(requests_session=session)
        self.assertIs(km.requests_session, session)


class TestLegacyZKillmail(TestCase):

    def test_fw_killmail(self):

        @urlmatch(netloc=r'(.*\.)?zkillboard\.com', path=r'.*37637533.*')
        def legacy_fw_response(url, request):
            resp = [{
                'killID': 37637533,
                'solarSystemID': 30001228,
                'killTime': '2014-03-20 02:32:00',
                'moonID': 0,
                'victim': {
                    'shipTypeID': 12017,
                    'damageTaken': 25198,
                    'factionName': 'Caldari State',
                    'factionID': 500001,
                    'allianceName': 'Test Alliance Please Ignore',
                    'allianceID': 498125261,
                    'corporationName': 'Dreddit',
                    'corporationID': 1018389948,
                    'characterName': 'Paxswill',
                    'characterID': 570140137,
                },
                'zkb': {
                    'totalValue': 273816945.63,
                    'points': 22,
                }
            }]
            return response(content=json.dumps(resp))

        with HTTMock(legacy_fw_response):
            # Actual testing
            km = killmail.LegacyZKillmail(
                'https://zkillboard.com/kill/37637533/')
            expected_values = {
                u'pilot': u'Paxswill',
                u'ship': u'Devoter',
                u'corp': u'Dreddit',
                u'alliance': u'Test Alliance Please Ignore',
                u'system': u'TA3T-3',
                u'domain': u'zkillboard.com',
                u'value': Decimal('273816945.63'),
            }
            for attr, value in expected_values.items():
                self.assertEqual(getattr(km, attr), value,
                        msg=u'{} is not {}'.format(attr, value))

    def test_no_alliance_killmail(self):
        
        @urlmatch(netloc=r'(.*\.)?zkillboard\.com', path=r'.*38862043.*')
        def legacy_no_alliance_response(url, request):
            # NOTE: Keep integers wrapped up as strings in this response to
            # simulate old zKillboard behavior.
            resp = [{
                'killID': '38862043',
                'solarSystemID': '30002811',
                'killTime': '2014-05-15 03:11:00',
                'moonID': '0',
                'victim': {
                    'shipTypeID': '598',
                    'damageTaken': '1507',
                    'factionName': '',
                    'factionID': '0',
                    'allianceName': '',
                    'allianceID': '0',
                    'corporationName': 'Omega LLC',
                    'corporationID': '98070272',
                    'characterName': 'Dave Duclas',
                    'characterID': '90741463',
                    'victim': '',
                },
                'zkb': {
                    'totalValue': '10432408.70',
                    'points': '8',
                    'involved': 1,
                }
            }]
            return response(content=json.dumps(resp))

        with HTTMock(legacy_no_alliance_response):
            # Actual testing
            km = killmail.LegacyZKillmail(
                'https://zkillboard.com/kill/38862043/')
            expected_values = {
                u'pilot': u'Dave Duclas',
                u'ship': u'Breacher',
                u'corp': u'Omega LLC',
                u'alliance': None,
                u'system': u'Onatoh',
                u'domain': u'zkillboard.com',
                u'value': Decimal('10432408.70'),
            }
            for attr, value in expected_values.items():
                self.assertEqual(getattr(km, attr), value,
                        msg=u'{} is not {}'.format(attr, value))

    def test_invalid_zkb_url(self):
        with self.assertRaisesRegexp(ValueError,
                u"'.*' is not a valid zKillboard killmail"):
            killmail.LegacyZKillmail('foobar')

    def test_invalid_zkb_response(self):
        @all_requests
        def bad_response(url, request):
            return response(status_code=403, content=u'')

        with HTTMock(bad_response):
            url = 'https://zkillboard.com/kill/38862043/'
            with self.assertRaisesRegexp(LookupError,
                    u"Error retrieving killmail data:.*"):
                killmail.LegacyZKillmail(url)

    def test_invalid_kill_ids(self):
        @all_requests
        def empty_response(url, request):
            return response(content='[]')

        with HTTMock(empty_response):
            url = 'https://zkillboard.com/kill/0/'
            with self.assertRaisesRegexp(LookupError, u"Invalid killmail: .*"):
                killmail.LegacyZKillmail(url)

class TestZKillmail(TestCase):

    def test_fw_killmail(self):
        km = killmail.ZKillmail('https://zkillboard.com/kill/37637533/')
        expected_values = {
            u'pilot': u'Paxswill',
            u'ship': u'Devoter',
            u'corp': u'Dreddit',
            u'alliance': u'Test Alliance Please Ignore',
            u'system': u'TA3T-3',
            u'value': Decimal(266421715.39),
        }
        for attr, value in expected_values.items():
            self.assertEqual(getattr(km, attr), value,
                    msg=u'{} is not {}'.format(attr, value))

    def test_no_alliance_killmail(self):
        km = killmail.ZKillmail('https://zkillboard.com/kill/38862043/')
        expected_values = {
            u'pilot': u'Dave Duclas',
            u'ship': u'Breacher',
            u'corp': u'Omega LLC',
            u'alliance': None,
            u'system': u'Onatoh',
            u'value': Decimal(10810333.33),
        }
        for attr, value in expected_values.items():
            self.assertEqual(getattr(km, attr), value,
                    msg=u'{} is not {}'.format(attr, value))

    def test_invalid_zkb_url(self):
        with self.assertRaisesRegexp(ValueError,
                u"'.*' is not a valid zKillboard killmail"):
            killmail.ZKillmail('foobar')

    def test_invalid_zkb_response(self):
        @all_requests
        def bad_response(url, request):
            return response(status_code=403, content=u'')

        with HTTMock(bad_response):
            url = 'https://zkillboard.com/kill/38862043/'
            with self.assertRaisesRegexp(LookupError,
                    u"Error retrieving zKillboard killmail: .*"):
                killmail.ZKillmail(url)

    def test_invalid_kill_ids(self):
        url = 'https://zkillboard.com/kill/0/'
        with self.assertRaisesRegexp(ValueError,
                                     u".* is not a valid zKillboard "
                                     u"killmail."):
            killmail.ZKillmail(url)

class TestESIMail(TestCase):

    def test_esi_killmails(self):
        with HTTMock(*all_mocks):
            km = killmail.ESIMail('https://esi.tech.ccp.is/'
                                  'v1/killmails/30290604/'
                                  '787fb3714062f1700560d4a83ce32c67640b1797/')
            expected_values = {
                u'pilot': u'CCP FoxFour',
                u'ship': u'Capsule',
                u'corp': u'C C P',
                u'alliance': u'C C P Alliance',
                u'system': u'Todifrauan',
            }
            for attr, value in expected_values.items():
                self.assertEqual(getattr(km, attr), value,
                        msg=u'{} is not {}'.format(attr, value))

    def test_invalid_esi_url(self):
        with self.assertRaisesRegexp(ValueError,
                u"'.*' is not a valid ESI killmail"):
            killmail.ESIMail('foobar')

    def test_invalid_esi_response(self):
        # UNlike the tests that are expected to apass, the error ones are still
        # mocked, as there's error limiting as errors are expensive to process
        # in ESI.
        @all_requests
        def bad_hash(url, request):
            return response(
                content=(u'{"error": '
                         u'"Invalid killmail_id and/or killmail_hash"'),
                status_code=422)

        with HTTMock(bad_hash):
            url = ''.join(('https://esi.tech.ccp.is/v1/killmails/',
                    '30290604/787fb3714062f1700560d4a83ce32c67640b1797/'))
            with self.assertRaisesRegexp(LookupError,
                    u"Error retrieving ESI killmail:.*"):
                killmail.ESIMail(url)
