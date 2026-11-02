import json
import threading
import unittest
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ruang_tumbuh.agent import FakeProvider, OpenAICompatibleProvider, ProviderError, ai_consent_scope


BASE_URL = 'https://ai.example/v1'


def tool_response(name, arguments='{}', usage=None):
    result = {'choices': [{'message': {'tool_calls': [{'type': 'function', 'function': {
        'name': name, 'arguments': arguments}}]}}]}
    if usage is not None:
        result['usage'] = usage
    return result


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        self.zone = ZoneInfo('Asia/Jakarta')

    def test_ai_consent_scope_tracks_provider_endpoint_and_model(self):
        config = {'AI_PROVIDER': 'openai-compatible', 'AI_BASE_URL': 'https://ai.example/v1', 'AI_MODEL': 'model-a'}
        with patch.dict('ruang_tumbuh.agent.os.environ', config, clear=True):
            original = ai_consent_scope()
        with patch.dict('ruang_tumbuh.agent.os.environ', {**config, 'AI_BASE_URL': 'https://ai.example/v1/'}, clear=True):
            self.assertEqual(ai_consent_scope(), original)
        for changed in (
            {**config, 'AI_BASE_URL': 'https://other.example/v1'},
            {**config, 'AI_MODEL': 'model-b'},
            {**config, 'AI_PROVIDER': 'fake'},
        ):
            with self.subTest(changed=changed), patch.dict('ruang_tumbuh.agent.os.environ', changed, clear=True):
                self.assertNotEqual(ai_consent_scope(), original)

    def test_fake_does_not_treat_question_as_fact(self):
        provider = FakeProvider()
        self.assertEqual(provider.propose('terakhir pup kapan?', self.now, self.zone), {'kind': 'find_events', 'category': 'poop'})
        self.assertEqual(provider.propose('besok jam 9 pup', self.now, self.zone)['kind'], 'clarify')

    def test_compatible_proposal_is_validated_and_needs_confirmation(self):
        calls = []
        args = {'events': [{'kind': 'diaper', 'occurred_at': '2026-01-01T09:30:00+07:00', 'payload_json': '{"type":"pup"}'}]}
        def transport(request):
            calls.append(request)
            return tool_response('create_events', json.dumps(args))
        result = OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, transport).propose('pup', self.now, self.zone)
        self.assertTrue(result['requires_confirmation'])
        self.assertNotIn('store', calls[0])
        self.assertEqual(calls[0]['messages'][0]['role'], 'system')
        self.assertNotIn('family_id', calls[0]['messages'][1]['content'])
        self.assertEqual(calls[0]['tool_choice'], 'required')
        self.assertEqual(calls[0]['tools'][0]['type'], 'function')
        self.assertIn('function', calls[0]['tools'][0])
        instruction = calls[0]['messages'][0]['content']
        self.assertIn('length only when the caregiver explicitly says', instruction)
        self.assertIn('height only when explicitly taken standing', instruction)
        self.assertIn('If position is missing or unclear, call clarify', instruction)
        self.assertIn('never convert it or infer a WHO result', instruction)
        args['events'][0]['occurred_at'] = '2026-01-01T11:00:00+07:00'
        with self.assertRaises(ProviderError):
            OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, transport).propose('pup', self.now, self.zone)

    def test_compatible_growth_requires_explicit_matching_measurement_position(self):
        args = {'events': [{'kind': 'growth', 'occurred_at': '2026-01-01T09:30:00+07:00',
                            'payload_json': '{"type":"height","value":70,"unit":"cm","position":"standing"}'}]}
        provider = OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL,
                                            lambda _: tool_response('create_events', json.dumps(args)))
        self.assertEqual(provider.propose('tinggi 70 cm, diukur sambil berdiri jam 9', self.now, self.zone)['kind'], 'create_events')
        self.assertEqual(provider.propose('tinggi 70 cm jam 9', self.now, self.zone)['kind'], 'clarify')
        self.assertEqual(provider.propose('tinggi 70 cm, diukur sambil berbaring jam 9', self.now, self.zone)['kind'], 'clarify')
        self.assertEqual(provider.propose('panjang 70 cm, diukur sambil berbaring jam 9', self.now, self.zone)['kind'], 'clarify')
        args['events'][0]['payload_json'] = '{"type":"height","value":70,"unit":"cm"}'
        self.assertEqual(provider.propose('tinggi 70 cm, diukur sambil berdiri jam 9', self.now, self.zone)['kind'], 'clarify')
        args['events'][0]['payload_json'] = '{"type":"height","value":70,"unit":"cm","position":"recumbent"}'
        self.assertEqual(provider.propose('tinggi 70 cm, diukur sambil berdiri jam 9', self.now, self.zone)['kind'], 'clarify')
        args['events'][0]['payload_json'] = '{"type":"length","value":70,"unit":"cm","position":"recumbent"}'
        self.assertEqual(provider.propose('panjang 70 cm, diukur sambil berbaring jam 9', self.now, self.zone)['kind'], 'create_events')

    def test_compatible_redacts_known_names_and_common_contact_patterns(self):
        calls = []
        response = tool_response('clarify')
        provider = OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, lambda request: calls.append(request) or response)
        provider.propose('Lili minum 120 ml, email ibu@example.com, telepon +628123456789; alamat rumah: Jl. Mawar No. 12, Jakarta', self.now, self.zone,
                         known_names=['Keluarga Mawar', 'Lili'])
        sent = json.loads(calls[0]['messages'][1]['content'])['message']
        for private_value in ('Lili', 'Keluarga Mawar', 'ibu@example.com', '+628123456789', 'Jl. Mawar No. 12', 'Jakarta'):
            self.assertNotIn(private_value, sent)

    def test_compatible_redacts_labeled_unknown_name_and_identity_number(self):
        calls = []
        response = tool_response('clarify')
        provider = OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, lambda request: calls.append(request) or response)
        provider.propose('Nama anak: Kirana Putri minum 120 ml; NIK: 3171234567890123', self.now, self.zone)
        sent = json.loads(calls[0]['messages'][1]['content'])['message']
        self.assertNotIn('Kirana', sent)
        self.assertNotIn('Putri', sent)
        self.assertNotIn('3171234567890123', sent)
        self.assertIn('minum 120 ml', sent)

    def test_compatible_redacts_profile_birth_date_only_in_birth_context(self):
        calls = []
        response = tool_response('clarify')
        provider = OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, lambda request: calls.append(request) or response)
        for birth_text in ('2024-02-01', '1 Februari 2024', '01/02/2024', '01-02-2024', '1 February 2024', 'February 1, 2024'):
            provider.propose(f'tanggal lahir {birth_text}; pup tanggal 2024-02-01', self.now, self.zone,
                             known_birth_dates=[date(2024, 2, 1)])
            sent = json.loads(calls[-1]['messages'][1]['content'])['message']
            self.assertEqual(sent, 'tanggal lahir [tanggal lahir disamarkan]; pup tanggal 2024-02-01')
        provider.propose('pup tanggal 2024-02-01; lahir kemarin', self.now, self.zone,
                         known_birth_dates=[date(2024, 2, 1)])
        sent = json.loads(calls[-1]['messages'][1]['content'])['message']
        self.assertEqual(sent, 'pup tanggal 2024-02-01; lahir kemarin')

    def test_compatible_can_only_return_a_bounded_out_of_scope_signal(self):
        response = tool_response('out_of_scope')
        result = OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, lambda _: response).propose('berapa dosis obat?', self.now, self.zone)
        self.assertEqual(result['kind'], 'out_of_scope')

    def test_compatible_base_url_requires_tls_except_loopback(self):
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            OpenAICompatibleProvider('synthetic', 'test-model', 'http://ai.example/v1')
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider('synthetic', 'test-model', 'https://user:pass@ai.example/v1')
        with self.assertRaisesRegex(ValueError, 'not OpenAI directly'):
            OpenAICompatibleProvider('synthetic', 'test-model', 'https://api.openai.com/v1')
        self.assertTrue(OpenAICompatibleProvider('synthetic', 'test-model', 'http://127.0.0.1:1234/v1'))

    def test_compatible_request_posts_chat_completion_to_configured_endpoint(self):
        provider = OpenAICompatibleProvider('synthetic-key', 'test-model', 'https://ai.example/custom/v1/')

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, _limit):
                return b'{"choices":[]}'

        class Opener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response()

        opener = Opener()
        with patch('ruang_tumbuh.agent.urllib.request.build_opener', return_value=opener) as build_opener:
            provider._request({'model': 'test-model'})
        request = opener.request
        self.assertEqual(build_opener.call_args.args[0].__name__, '_RejectRedirects')
        self.assertEqual(opener.timeout, 20)
        self.assertEqual(request.full_url, 'https://ai.example/custom/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-key')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(request.get_method(), 'POST')

    def test_compatible_provider_round_trips_to_local_http_endpoint(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.server.request_path = self.path
                self.server.authorization = self.headers.get('Authorization')
                self.server.payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                body = json.dumps(tool_response('clarify')).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider('synthetic-key', 'test-model',
                f'http://127.0.0.1:{server.server_port}/v1')
            result = provider.propose('uji', self.now, self.zone)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(result['kind'], 'clarify')
        self.assertEqual(server.request_path, '/v1/chat/completions')
        self.assertEqual(server.authorization, 'Bearer synthetic-key')
        self.assertEqual(server.payload['messages'][1]['role'], 'user')
        self.assertEqual(server.payload['tools'][0]['type'], 'function')

    def test_compatible_provider_rejects_redirect_without_forwarding_credentials(self):
        class Receiver(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.request_received = True
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        receiver = HTTPServer(('127.0.0.1', 0), Receiver)
        class Redirector(BaseHTTPRequestHandler):
            def do_POST(self):
                self.server.authorization = self.headers.get('Authorization')
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{receiver.server_port}/collect')
                self.end_headers()

            def log_message(self, *_):
                pass

        redirector = HTTPServer(('127.0.0.1', 0), Redirector)
        receiver.request_received = False
        receiver_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
        redirector_thread = threading.Thread(target=redirector.serve_forever, daemon=True)
        receiver_thread.start()
        redirector_thread.start()
        try:
            provider = OpenAICompatibleProvider('synthetic-key', 'test-model',
                f'http://127.0.0.1:{redirector.server_port}/v1')
            with self.assertRaises(ProviderError):
                provider.propose('uji', self.now, self.zone)
        finally:
            redirector.shutdown()
            receiver.shutdown()
            redirector.server_close()
            receiver.server_close()
            redirector_thread.join()
            receiver_thread.join()

        self.assertEqual(redirector.authorization, 'Bearer synthetic-key')
        self.assertFalse(receiver.request_received)

    def test_reject_unknown_malformed_and_provider_failures(self):
        cases = [
            tool_response('run_shell'),
            tool_response('find_events', '{"category":"poop","category":"feeding"}'),
            {'choices': []},
            {'choices': [{'message': {'content': 'plain text'}}]},
        ]
        for response in cases:
            with self.subTest(response=response), self.assertRaises(ProviderError):
                OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, lambda _: response).propose('uji', self.now, self.zone)
        with self.assertRaises(ProviderError):
            OpenAICompatibleProvider('synthetic', 'test-model', BASE_URL, lambda _: 1 / 0).propose('uji', self.now, self.zone)
