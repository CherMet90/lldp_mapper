import unittest
from unittest.mock import Mock, patch
from datetime import datetime

class TestTopology(unittest.TestCase):
    def setUp(self):
        # Импортируем модуль для тестирования
        from topology import Topology

        # Создаем экземпляр с известной временной меткой
        self.now = 1234567890
        with patch('topology.EPOCH', return_value=self.now):
            self.topo = Topology(site_slug="test_site")

        # Создаем моки для устройств и интерфейсов
        self.create_device_mock = lambda name, interfaces: Mock(
            nb_name=name,
            hostname=name,
            ip=f"192.168.1.{name.split('_')[-1]}",
            model="TestModel",
            serial=f"SN{name}",
            role="test-role",
            interfaces=interfaces
        )

    def create_interface_mock(self, name, rem_name, rem_port):
        intf_mock = Mock()
        intf_mock.name = name
        intf_mock.lldp_rem_name = rem_name
        intf_mock.lldp_rem_port = rem_port
        return intf_mock

    def test_new_connection_added(self):
        """Тестирует добавление нового соединения"""
        # Создаем устройство с одним интерфейсом
        device_a = self.create_device_mock("device_1", [
            self.create_interface_mock("Gi0/1", "device_2", "Gi0/2")
        ])

        # Добавляем устройство
        self.topo.add_device(device_a)

        # Проверяем, что устройство добавлено
        self.assertIn("device_1", self.topo.devices)

        # Проверяем, что соединение добавлено
        key = ("device_1", "gi0/1", "device_2", "gi0/2")
        self.assertIn(key, self.topo.connections)

        # Проверяем метаданные соединения
        self.assertEqual(self.topo.connections[key], {
            "bidirectional": False,
            "last_seen": self.now
        })

        # Проверяем, что обратный ключ добавлен в _reverse_keys
        reverse_key = ("device_2", "gi0/2", "device_1", "gi0/1")
        self.assertIn(reverse_key, self.topo._reverse_keys)

    def test_bidirectional_connection_case1(self):
        """
        Тестирует Случай 1: Если прямой ключ уже есть в обратном словаре, 
        значит зеркальная связь уже была добавлена ранее
        """
        # Создаем два устройства с соединением друг к другу
        device_a = self.create_device_mock("device_1", [
            self.create_interface_mock("Gi0/1", "device_2", "Gi0/2")
        ])
        device_b = self.create_device_mock("device_2", [
            self.create_interface_mock("Gi0/2", "device_1", "Gi0/1")
        ])

        # Добавляем первое устройство
        self.topo.add_device(device_a)

        # Ключи соединений
        key_a_to_b = ("device_1", "gi0/1", "device_2", "gi0/2")
        key_b_to_a = ("device_2", "gi0/2", "device_1", "gi0/1")

        # Проверяем первое добавление
        self.assertIn(key_a_to_b, self.topo.connections)
        self.assertFalse(self.topo.connections[key_a_to_b]["bidirectional"])
        self.assertIn(key_b_to_a, self.topo._reverse_keys)

        # Добавляем второе устройство
        self.topo.add_device(device_b)

        # Проверяем, что после добавления device_b:
        # 1. Соединение от B к A не создано отдельно
        self.assertNotIn(key_b_to_a, self.topo.connections)

        # 2. Соединение от A к B помечено двунаправленным
        self.assertIn(key_a_to_b, self.topo.connections)
        self.assertTrue(self.topo.connections[key_a_to_b]["bidirectional"])

    def test_update_existing_connection_case2(self):
        """
        Тестирует Случай 2: Обновление существующего соединения 
        и удаление зеркального, если оно есть
        """
        # Создаем одно устройство
        device_a = self.create_device_mock("device_1", [
            self.create_interface_mock("Gi0/1", "device_2", "Gi0/2")
        ])

        # Ключи соединений
        key_a_to_b = ("device_1", "gi0/1", "device_2", "gi0/2")
        key_b_to_a = ("device_2", "gi0/2", "device_1", "gi0/1")

        # Предварительно добавляем оба соединения (имитация загрузки из кеша)
        time_past = self.now - 3600  # час назад
        self.topo.connections[key_a_to_b] = {"bidirectional": False, "last_seen": time_past}
        self.topo.connections[key_b_to_a] = {"bidirectional": False, "last_seen": time_past}

        # Добавляем устройство
        self.topo.add_device(device_a)

        # Проверяем, что после добавления:
        # 1. Прямое соединение обновлено
        self.assertIn(key_a_to_b, self.topo.connections)
        self.assertEqual(self.topo.connections[key_a_to_b]["last_seen"], self.now)

        # 2. Зеркальное соединение удалено
        self.assertNotIn(key_b_to_a, self.topo.connections)

        # 3. Обратный ключ добавлен в _reverse_keys
        self.assertIn(key_b_to_a, self.topo._reverse_keys)

    def test_complex_scenario(self):
        """Тестирует сложный сценарий с несколькими устройствами"""
        # Создаем три устройства с соединениями
        device_1 = self.create_device_mock("device_1", [
            self.create_interface_mock("Gi0/1", "device_2", "Gi0/1"),
            self.create_interface_mock("Gi0/2", "device_3", "Gi0/1")
        ])

        device_2 = self.create_device_mock("device_2", [
            self.create_interface_mock("Gi0/1", "device_1", "Gi0/1"),
            self.create_interface_mock("Gi0/2", "device_3", "Gi0/2")
        ])

        device_3 = self.create_device_mock("device_3", [
            self.create_interface_mock("Gi0/1", "device_1", "Gi0/2"),
            self.create_interface_mock("Gi0/2", "device_2", "Gi0/2")
        ])

        # Добавляем все устройства
        self.topo.add_device(device_1)
        self.topo.add_device(device_2)
        self.topo.add_device(device_3)

        # Проверяем, что все устройства добавлены
        self.assertEqual(len(self.topo.devices), 3)

        # Ожидаемые ключи соединений
        key_1_to_2 = ("device_1", "gi0/1", "device_2", "gi0/1")
        key_1_to_3 = ("device_1", "gi0/2", "device_3", "gi0/1")
        key_2_to_3 = ("device_2", "gi0/2", "device_3", "gi0/2")

        # Проверяем, что все соединения двунаправленные и нет дубликатов
        self.assertEqual(len(self.topo.connections), 3)

        self.assertIn(key_1_to_2, self.topo.connections)
        self.assertTrue(self.topo.connections[key_1_to_2]["bidirectional"])

        self.assertIn(key_1_to_3, self.topo.connections)
        self.assertTrue(self.topo.connections[key_1_to_3]["bidirectional"])

        self.assertIn(key_2_to_3, self.topo.connections)
        self.assertTrue(self.topo.connections[key_2_to_3]["bidirectional"])

    def test_nonexistent_cached_connection(self):
        """
        Тестирует, что Случай 2 работает даже если зеркального соединения нет
        (проверка отсутствия KeyError)
        """
        # Создаем устройство
        device_a = self.create_device_mock("device_1", [
            self.create_interface_mock("Gi0/1", "device_2", "Gi0/2")
        ])

        # Ключ соединения
        key_a_to_b = ("device_1", "gi0/1", "device_2", "gi0/2")

        # Предварительно добавляем только прямое соединение
        time_past = self.now - 3600  # час назад
        self.topo.connections[key_a_to_b] = {"bidirectional": False, "last_seen": time_past}

        # Этот тест проверяет, что не будет ошибки при обращении к несуществующему ключу
        try:
            self.topo.add_device(device_a)
            # Тест прошел, если не было исключения
            self.assertTrue(True)
        except KeyError:
            self.fail("KeyError был вызван при обращении к несуществующему ключу")

        # Проверяем, что соединение обновлено
        self.assertIn(key_a_to_b, self.topo.connections)
        self.assertEqual(self.topo.connections[key_a_to_b]["last_seen"], self.now)

if __name__ == '__main__':
    unittest.main()