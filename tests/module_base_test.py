from sonic_platform_base.module_base import ModuleBase
import pytest
import json
import os
import fcntl
from unittest.mock import patch, MagicMock, call
from io import StringIO
import shutil

class MockFile:
    def __init__(self, data=None):
        self.data = data
        self.written_data = None
        self.closed = False
        self.fileno_called = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self):
        return self.data

    def write(self, data):
        self.written_data = data

    def fileno(self):
        self.fileno_called = True
        return 123


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

        with patch('builtins.open', return_value=MockFile(json.dumps(mock_json_data))) as mock_open_call, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.get_pci_bus_from_platform_json() == "0000:01:00.0"
            mock_open_call.assert_called_once_with(platform_json_path, 'r')
            assert module.pci_bus_info == "0000:01:00.0"

        module.pci_bus_info = None
        with patch('builtins.open', return_value=MockFile(json.dumps(mock_json_data))) as mock_open_call, \
             patch.object(module, 'get_name', return_value="ABC"):
            assert module.get_pci_bus_from_platform_json() is None
            mock_open_call.assert_called_once_with(platform_json_path, 'r')

        with patch('builtins.open', side_effect=Exception()):
            assert module.get_pci_bus_from_platform_json() is None

    def test_pci_entry_state_db(self):
        module = ModuleBase()
        mock_connector = MagicMock()
        module.state_db_connector = mock_connector

        module.pci_entry_state_db("0000:00:00.0", "detaching")
        mock_connector.hset.assert_has_calls([
            call("PCIE_DETACH_INFO|0000:00:00.0", "bus_info", "0000:00:00.0"),
            call("PCIE_DETACH_INFO|0000:00:00.0", "dpu_state", "detaching")
        ])

        module.pci_entry_state_db("0000:00:00.0", "attaching")
        mock_connector.delete.assert_called_with("PCIE_DETACH_INFO|0000:00:00.0")

        mock_connector.hset.side_effect = Exception("DB Error")
        module.pci_entry_state_db("0000:00:00.0", "detaching")

    def test_pci_operation_lock(self):
        module = ModuleBase()
        mock_file = MockFile()

        with patch('builtins.open', return_value=mock_file) as mock_file_open, \
             patch('fcntl.flock') as mock_flock, \
             patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.makedirs') as mock_makedirs:

            with module._pci_operation_lock():
                mock_flock.assert_called_with(123, fcntl.LOCK_EX)

            mock_flock.assert_has_calls([
                call(123, fcntl.LOCK_EX),
                call(123, fcntl.LOCK_UN)
            ])
            assert mock_file.fileno_called

    def test_pci_removal_from_platform_json(self):
        module = ModuleBase()
        mock_file = MockFile()
        with patch('builtins.open', return_value=mock_file) as mock_open, \
             patch.object(module, 'get_pci_bus_from_platform_json', return_value="0000:00:00.0"), \
             patch.object(module, 'pci_entry_state_db') as mock_db, \
             patch.object(module, '_pci_operation_lock') as mock_lock, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.pci_removal_from_platform_json() is True
            mock_db.assert_called_with("0000:00:00.0", "detaching")
            assert mock_file.written_data == "1"
            mock_open.assert_called_with("/sys/bus/pci/devices/0000:00:00.0/remove", 'w')
            mock_lock.assert_called_once()

        with patch.object(module, 'get_pci_bus_from_platform_json', return_value=None):
            assert module.pci_removal_from_platform_json() is False

    def test_pci_reattach_from_platform_json(self):
        module = ModuleBase()
        mock_file = MockFile()

        with patch('builtins.open', return_value=mock_file) as mock_open, \
             patch.object(module, 'get_pci_bus_from_platform_json', return_value="0000:00:00.0"), \
             patch.object(module, 'pci_entry_state_db') as mock_db, \
             patch.object(module, '_pci_operation_lock') as mock_lock, \
             patch.object(module, 'get_name', return_value="DPU0"):
            assert module.pci_reattach_from_platform_json() is True
            mock_db.assert_called_with("0000:00:00.0", "attaching")
            assert mock_file.written_data == "1"
            mock_open.assert_called_with("/sys/bus/pci/rescan", 'w')
            mock_lock.assert_called_once()

        with patch.object(module, 'get_pci_bus_from_platform_json', return_value=None):
            assert module.pci_reattach_from_platform_json() is False

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

    def test_handle_sensor_removal(self):
        module = ModuleBase()

        with patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.path.exists', return_value=True), \
             patch('shutil.copy2') as mock_copy, \
             patch('os.system') as mock_system:
            assert module.handle_sensor_removal() is True
            mock_copy.assert_called_once_with("/usr/share/sonic/platform/dpu_ignore_conf/ignore_DPU0.conf",
                                             "/etc/sensors.d/ignore_DPU0.conf")
            mock_system.assert_called_once_with("service sensord restart")

        with patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.path.exists', return_value=False), \
             patch('shutil.copy2') as mock_copy, \
             patch('os.system') as mock_system:
            assert module.handle_sensor_removal() is True
            mock_copy.assert_not_called()
            mock_system.assert_not_called()

        with patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.path.exists', return_value=True), \
             patch('shutil.copy2', side_effect=Exception("Copy failed")):
            assert module.handle_sensor_removal() is False

    def test_handle_sensor_addition(self):
        module = ModuleBase()

        with patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.path.exists', return_value=True), \
             patch('os.remove') as mock_remove, \
             patch('os.system') as mock_system:
            assert module.handle_sensor_addition() is True
            mock_remove.assert_called_once_with("/etc/sensors.d/ignore_DPU0.conf")
            mock_system.assert_called_once_with("service sensord restart")

        with patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.path.exists', return_value=False), \
             patch('os.remove') as mock_remove, \
             patch('os.system') as mock_system:
            assert module.handle_sensor_addition() is True
            mock_remove.assert_not_called()
            mock_system.assert_not_called()

        with patch.object(module, 'get_name', return_value="DPU0"), \
             patch('os.path.exists', return_value=True), \
             patch('os.remove', side_effect=Exception("Remove failed")):
            assert module.handle_sensor_addition() is False
