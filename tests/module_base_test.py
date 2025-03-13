from sonic_platform_base.module_base import ModuleBase
import pytest
import json
import os
import fcntl
from unittest.mock import patch, mock_open, MagicMock, call

class TestModuleBase:

    def test_module_base(self):
        module = ModuleBase()
        not_implemented_methods = [
                [module.get_dpu_id],
                [module.get_reboot_cause],
                [module.get_state_info],
                [module.get_pci_bus_info],
                [module.pci_detach],
                [module.pci_reattach],
            ]

        for method in not_implemented_methods:
            exception_raised = False
            try:
                func = method[0]
                args = method[1:]
                func(*args)
            except NotImplementedError:
                exception_raised = True

            assert exception_raised

    def test_sensors(self):
        module = ModuleBase()
        assert(module.get_num_voltage_sensors() == 0)
        assert(module.get_all_voltage_sensors() == [])
        assert(module.get_voltage_sensor(0) == None)
        module._voltage_sensor_list = ["s1"]
        assert(module.get_all_voltage_sensors() == ["s1"])
        assert(module.get_voltage_sensor(0) == "s1")
        assert(module.get_num_current_sensors() == 0)
        assert(module.get_all_current_sensors() == [])
        assert(module.get_current_sensor(0) == None)
        module._current_sensor_list = ["s1"]
        assert(module.get_all_current_sensors() == ["s1"])
        assert(module.get_current_sensor(0) == "s1")

    def test_get_pci_bus_from_platform_json(self):
        module = ModuleBase()
        module.pci_bus_info = "0000:00:00.0"
        assert module.get_pci_bus_from_platform_json() == "0000:00:00.0"
        mock_json_data = {
            "DPUS": {
                "DPU0": {"bus_info": "0000:01:00.0"}
            }
        }
        module.pci_bus_info = None
        platform_json_path = "/usr/share/sonic/platform/platform.json"
        with patch('builtins.open', mock_open(read_data=json.dumps(mock_json_data))) as mock_open_call, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.get_pci_bus_from_platform_json() == "0000:01:00.0"
            mock_open_call.assert_called_once_with(platform_json_path, 'r')
            assert module.pci_bus_info == "0000:01:00.0"

        module.pci_bus_info = None
        with patch('builtins.open', mock_open(read_data=json.dumps(mock_json_data))) as mock_open_call, \
             patch.object(module, 'get_name', return_value="ABC"):
            assert module.get_pci_bus_from_platform_json() is None
            mock_open_call.assert_called_once_with(platform_json_path, 'r')

        with patch('builtins.open', side_effect=Exception()) as mock_open_call:
            assert module.get_pci_bus_from_platform_json() is None

    def test_pci_entry_state_db(self):
        module = ModuleBase()
        mock_connector = MagicMock()
        module.state_db_connector = mock_connector

        module.pci_entry_state_db("0000:00:00.0", "detaching")
        mock_connector.hset.assert_called_with("PCIE_DETACH_INFO", "0000:00:00.0", "detaching")

        module.pci_entry_state_db("0000:00:00.0", "attaching")
        mock_connector.hdel.assert_called_with("PCIE_DETACH_INFO", "0000:00:00.0")

        mock_connector.hset.side_effect = Exception("DB Error")
        module.pci_entry_state_db("0000:00:00.0", "detaching")

    def test_pci_operation_lock(self):
        module = ModuleBase()
        mock_file = MagicMock()
        mock_open_obj = mock_open()
        mock_open_obj.reset_mock()
        with patch('builtins.open', mock_open_obj) as mock_file_open, \
             patch('fcntl.flock') as mock_flock, \
             patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.makedirs') as mock_makedirs:

            with module._pci_operation_lock():
                mock_flock.assert_called_with(mock_file_open().fileno(), fcntl.LOCK_EX)

            mock_flock.assert_has_calls([
                call(mock_file_open().fileno(), fcntl.LOCK_EX),
                call(mock_file_open().fileno(), fcntl.LOCK_UN)
            ])

    @patch('builtins.open')
    def test_pci_removal_from_platform_json(self, mock_open):
        module = ModuleBase()
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file

        with patch.object(module, 'get_pci_bus_from_platform_json', return_value="0000:00:00.0"), \
             patch.object(module, 'pci_entry_state_db') as mock_db, \
             patch.object(module, '_pci_operation_lock') as mock_lock, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.pci_removal_from_platform_json() is True
            mock_db.assert_called_with("0000:00:00.0", "detaching")
            mock_file.write.assert_called_with("1")
            mock_open.assert_called_with("/sys/bus/pci/devices/0000:00:00.0/remove", 'w')
            mock_lock.assert_called_once()
        mock_open.reset_mock()
        with patch.object(module, 'get_pci_bus_from_platform_json', return_value=None):
            assert module.pci_removal_from_platform_json() is False
            mock_open.assert_not_called()

    @patch('builtins.open')
    def test_pci_reattach_from_platform_json(self, mock_open):
        module = ModuleBase()
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file

        with patch.object(module, 'get_pci_bus_from_platform_json', return_value="0000:00:00.0"), \
             patch.object(module, 'pci_entry_state_db') as mock_db, \
             patch.object(module, '_pci_operation_lock') as mock_lock, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.pci_reattach_from_platform_json() is True
            mock_db.assert_called_with("0000:00:00.0", "attaching")
            mock_file.write.assert_called_with("1")
            mock_open.assert_called_with("/sys/bus/pci/rescan", 'w')
            mock_lock.assert_called_once()

        mock_open.reset_mock()
        with patch.object(module, 'get_pci_bus_from_platform_json', return_value=None):
            assert module.pci_reattach_from_platform_json() is False
            mock_open.assert_not_called()
        mock_open.reset_mock()

    def test_handle_pci_removal(self):
        module = ModuleBase()

        with patch.object(module, 'get_pci_bus_info', return_value=["0000:00:00.0"]), \
             patch.object(module, 'pci_entry_state_db') as mock_db, \
             patch.object(module, 'pci_detach', return_value=True), \
             patch.object(module, '_pci_operation_lock') as mock_lock, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.handle_pci_removal() is True
            mock_db.assert_called_with("0000:00:00.0", "detaching")
            mock_lock.assert_called_once()

        with patch.object(module, 'get_pci_bus_info', side_effect=NotImplementedError()), \
             patch.object(module, 'pci_removal_from_platform_json', return_value=True):
            assert module.handle_pci_removal() is True

        with patch.object(module, 'get_pci_bus_info', side_effect=Exception()):
            assert module.handle_pci_removal() is False

    def test_handle_pci_rescan(self):
        module = ModuleBase()

        with patch.object(module, 'get_pci_bus_info', return_value=["0000:00:00.0"]), \
             patch.object(module, 'pci_entry_state_db') as mock_db, \
             patch.object(module, 'pci_reattach', return_value=True), \
             patch.object(module, '_pci_operation_lock') as mock_lock, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.handle_pci_rescan() is True
            mock_db.assert_called_with("0000:00:00.0", "attaching")
            mock_lock.assert_called_once()

        with patch.object(module, 'get_pci_bus_info', side_effect=NotImplementedError()), \
             patch.object(module, 'pci_reattach_from_platform_json', return_value=True):
            assert module.handle_pci_rescan() is True

        with patch.object(module, 'get_pci_bus_info', side_effect=Exception()):
            assert module.handle_pci_rescan() is False

    def test_module_cleanup(self):
        module = ModuleBase()

        with patch.object(module, 'get_pci_bus_info', return_value=["0000:00:00.0"]), \
             patch.object(module, 'pci_entry_state_db') as mock_db:
            module.__del__()
            mock_db.assert_called_with("0000:00:00.0", "attaching")

        with patch.object(module, 'get_pci_bus_info', side_effect=NotImplementedError()), \
             patch.object(module, 'get_pci_bus_from_platform_json', return_value="0000:01:00.0"), \
             patch.object(module, 'pci_entry_state_db') as mock_db:
            module.__del__()
            mock_db.assert_called_with("0000:01:00.0", "attaching")

        with patch.object(module, 'get_pci_bus_info', side_effect=Exception()), \
             patch.object(module, 'get_pci_bus_from_platform_json', return_value=None):
            module.__del__()

