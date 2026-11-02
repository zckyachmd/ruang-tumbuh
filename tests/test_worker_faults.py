import unittest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from ruang_tumbuh.chat_worker import _process_claimed
from ruang_tumbuh.privacy import DataCipher


class WorkerFaultTests(unittest.TestCase):
    def test_corrupt_row_is_quarantined_without_running_provider(self):
        store, provider = MagicMock(), MagicMock()
        store.data_cipher = DataCipher('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
        self.assertTrue(_process_claimed(store, provider, (7, 9, 'broken-envelope'), 'lease'))
        provider.propose.assert_not_called()
        store.create_events.assert_not_called()
        calls = store.connect.return_value.__enter__.return_value.execute.call_args_list
        self.assertTrue(any("status='failed'" in call.args[0] for call in calls))
        self.assertFalse(any('INSERT INTO chat_outbox' in call.args[0] for call in calls))

    def test_other_child_name_never_reaches_provider_or_event_write(self):
        store, provider = MagicMock(), MagicMock()
        cipher = DataCipher('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
        store.data_cipher = cipher
        store.families.return_value = [(1,'Keluarga','Asia/Jakarta','owner')]
        store.chat_selection.return_value = (1,2,'Keluarga','Asia/Jakarta','Alya')
        store.children.return_value = [(2,'Alya',None,None,None),(3,'Bima',None,None,None)]
        message = {'message':{'text':'Bima minum 60 ml hari ini jam 09.00','date':int(datetime.now(timezone.utc).timestamp())}}
        sealed = cipher.seal_json(message,'inbound_updates.payload')
        self.assertTrue(_process_claimed(store,provider,(7,9,sealed),'lease'))
        provider.propose.assert_not_called()
        store.create_events.assert_not_called()
        calls = store.connect.return_value.__enter__.return_value.execute.call_args_list
        outbox = next(call.args[1][3] for call in calls if 'INSERT INTO chat_outbox' in call.args[0])
        response = cipher.open(outbox,'chat_outbox.body')
        self.assertIn('Alya',response)
        self.assertIn('Pilih anak',response)


if __name__ == '__main__':
    unittest.main()
