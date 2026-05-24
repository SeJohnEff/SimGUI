"""Focused tests for _parse_shell_public_fields and _read_public_fields_via_shell."""
import textwrap
from unittest.mock import patch

import pytest

from managers.card_manager import CardManager


def _cm():
    cm = CardManager()
    cm.cli_path = None
    return cm


SHELL_STDOUT = textwrap.dedent("""\
    Welcome to pySim-shell!
    {
        "file_descriptor": {}
    }
    {"ACC0": true, "ACC1": false, "ACC2": false, "ACC3": false, "ACC4": false, "ACC5": false, "ACC6": false, "ACC7": false, "ACC8": false, "ACC9": false, "ACC10": false, "ACC11": false, "ACC12": false, "ACC13": false, "ACC14": false, "ACC15": false}
    {
        "file_descriptor": {}
    }
    {"rfu": 63, "hide_in_oplmn": true, "show_in_hplmn": true, "spn": ""}
    {
        "file_descriptor": {}
    }
    [{"mcc": "234", "mnc": "20"}, {"mcc": "234", "mnc": "02"}, {"mcc": "234", "mnc": "07"}, {"mcc": "234", "mnc": "30"}, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null]
""")


class TestParseShellPublicFields:
    def test_acc_single_class_enabled(self):
        cm = _cm()
        output = '{"ACC0": true, "ACC1": false, "ACC2": false, "ACC3": false, "ACC4": false, "ACC5": false, "ACC6": false, "ACC7": false, "ACC8": false, "ACC9": false, "ACC10": false, "ACC11": false, "ACC12": false, "ACC13": false, "ACC14": false, "ACC15": false}'
        cm._parse_shell_public_fields(output)
        assert cm.card_info['ACC'] == 'ACC0'

    def test_acc_multiple_classes_enabled(self):
        cm = _cm()
        data = {f'ACC{i}': (i in (0, 11)) for i in range(16)}
        import json
        cm._parse_shell_public_fields(json.dumps(data))
        assert cm.card_info['ACC'] == 'ACC0,ACC11'

    def test_acc_no_classes_enabled(self):
        cm = _cm()
        data = {f'ACC{i}': False for i in range(16)}
        import json
        cm._parse_shell_public_fields(json.dumps(data))
        assert cm.card_info.get('ACC') == ''

    def test_spn_populated(self):
        cm = _cm()
        cm._parse_shell_public_fields('{"rfu": 0, "hide_in_oplmn": false, "show_in_hplmn": true, "spn": "MyNetwork"}')
        assert cm.card_info['SPN'] == 'MyNetwork'

    def test_spn_empty_not_stored(self):
        cm = _cm()
        cm._parse_shell_public_fields('{"rfu": 63, "hide_in_oplmn": true, "show_in_hplmn": true, "spn": ""}')
        assert 'SPN' not in cm.card_info

    def test_fplmn_nulls_ignored(self):
        cm = _cm()
        cm._parse_shell_public_fields('[{"mcc": "234", "mnc": "20"}, {"mcc": "234", "mnc": "02"}, null, null]')
        assert cm.card_info['FPLMN'] == '23420,23402'

    def test_fplmn_mnc_zero_padded(self):
        cm = _cm()
        cm._parse_shell_public_fields('[{"mcc": "234", "mnc": "2"}]')
        assert cm.card_info['FPLMN'] == '23402'

    def test_fplmn_all_null_not_stored(self):
        cm = _cm()
        cm._parse_shell_public_fields('[null, null, null]')
        assert 'FPLMN' not in cm.card_info

    def test_full_shell_stdout_parses_all_three(self):
        cm = _cm()
        cm._parse_shell_public_fields(SHELL_STDOUT)
        # ACC: only ACC0 enabled on test card
        assert cm.card_info.get('ACC') == 'ACC0'
        # SPN: empty → not stored
        assert 'SPN' not in cm.card_info
        # FPLMN: four entries, nulls stripped
        assert cm.card_info['FPLMN'] == '23420,23402,23407,23430'

    def test_non_json_lines_ignored(self):
        cm = _cm()
        cm._parse_shell_public_fields("Welcome to pySim-shell!\nsome random line\n")
        assert cm.card_info == {}

    def test_existing_iccid_imsi_unaffected(self):
        cm = _cm()
        cm.card_info['ICCID'] = '8988211000000123456'
        cm.card_info['IMSI'] = '001010000012345'
        cm._parse_shell_public_fields(SHELL_STDOUT)
        assert cm.card_info['ICCID'] == '8988211000000123456'
        assert cm.card_info['IMSI'] == '001010000012345'


class TestReadPublicFieldsViaShell:
    def test_skips_when_no_iccid(self):
        """_read_public_fields_via_shell must not call pySim-shell on blank cards."""
        cm = _cm()
        cm.card_info = {}  # no ICCID
        with patch.object(cm, '_run_pysim_shell_safe') as mock_shell:
            cm._read_public_fields_via_shell()
        mock_shell.assert_not_called()

    def test_enriches_card_info_on_success(self):
        cm = _cm()
        cm.card_info = {'ICCID': '8988211000000123456', 'IMSI': '001010000012345'}
        shell_out = '[{"mcc": "234", "mnc": "20"}, null]'
        with patch.object(cm, '_run_pysim_shell_safe', return_value=(True, shell_out, '')), \
             patch('time.sleep'):
            cm._read_public_fields_via_shell()
        assert cm.card_info['FPLMN'] == '23420'

    def test_shell_failure_leaves_card_info_intact(self):
        cm = _cm()
        cm.card_info = {'ICCID': '8988211000000123456'}
        with patch.object(cm, '_run_pysim_shell_safe', return_value=(False, '', 'Card error')), \
             patch('time.sleep'):
            cm._read_public_fields_via_shell()
        assert 'ACC' not in cm.card_info
        assert 'SPN' not in cm.card_info
        assert 'FPLMN' not in cm.card_info
