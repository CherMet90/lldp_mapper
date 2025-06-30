import fnmatch
import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional
from functools import lru_cache

from config import DOT_GLOBAL_SETTINGS, DRAWIO_SETTINGS, NODE_STYLES, PORT_NAME_SUBSTITUTIONS, CACHE_FILE, CISCO_STYLES
from custom_modules.log import logger

# размер LRU-кеша
PORT_NORM_CACHE_SIZE = 10000

EPOCH = lambda: int(time.time())

# Скомпилированные регулярные выражения для нормализации портов
COMPILED_PORT_PATTERNS = [(re.compile(pat, re.I), rep) for pat, rep in PORT_NAME_SUBSTITUTIONS]

class DeviceCacheError(Exception):
    """Ошибка при работе с кешем устройств."""
    pass


class Topology:
    """Хранит устройства и их связи, поддерживает экспорт и кеширование."""

    def __init__(self, site_slug=None):
        self.devices = {}        # name -> CollectedDevice
        # key = (devA,portA,devB,portB)  value = {"bidirectional":bool, "last_seen":epoch}
        self.connections = {}
        self.site = site_slug    # Текущая площадка
        self.current_time = EPOCH()  # Время создания снимка топологии
        # Кеш для стилей ролей устройств
        self._role_style_cache = {}
        # Для оптимизации: набор обратных ключей для быстрой проверки bidirectional
        self._reverse_keys = set()

    @staticmethod
    @lru_cache(maxsize=PORT_NORM_CACHE_SIZE)
    def _norm(port: str) -> str:
        """
        Нормализует имя порта с использованием скомпилированных regex.
        """
        if not port or not isinstance(port, str):
            return 'unknown'

        p = port.lower()

        # процедура нормализации через регулярные выражения
        for pattern, rep in COMPILED_PORT_PATTERNS:
            p = pattern.sub(rep, p)

        return p

    # ---------- работа со связями ----------
    def _make_link_key(self, a_dev, a_port, b_dev, b_port):
        """
        Создает ключ для хранения соединения с нормализацией портов.
        """
        return (a_dev, self._norm(a_port or ""), b_dev, self._norm(b_port or ""))

    def _device_to_dict(self, device) -> dict:
        """
        Преобразует устройство в словарь.
        Поддерживает объекты dataclass и словари.
        """
        if isinstance(device, dict):
            return device

        # Используем asdict если доступно (для dataclass)
        try:
            from dataclasses import asdict
            return asdict(device)
        except (ImportError, TypeError):
            # Fallback для не-dataclass объектов
            return {
                'hostname': getattr(device, 'hostname', ''),
                'ip': getattr(device, 'ip', ''),
                'model': getattr(device, 'model', ''),
                'serial': getattr(device, 'serial', ''),
                'role': getattr(device, 'role', '')
            }

    def _get_device_role(self, device_name: str) -> Optional[str]:
        """
        Получает роль устройства из структуры devices.
        """
        if device_name not in self.devices:
            return None

        device = self.devices[device_name]
        device_dict = self._device_to_dict(device)
        return device_dict.get('role', '')

    def _matches_pattern(self, device_name: str, patterns: Set[str]) -> bool:
        """
        Проверяет, соответствует ли имя устройства одному из шаблонов.
    
        Args:
            device_name: Имя устройства для проверки
            patterns: Множество шаблонов (может содержать маски и точные имена)
    
        Returns:
            True если имя соответствует хотя бы одному шаблону
        """
        for pattern in patterns:
            # Точное совпадение
            if device_name == pattern:
                return True
            # Проверка по маске (если содержит специальные символы)
            if '*' in pattern or '?' in pattern or '[' in pattern:
                if fnmatch.fnmatch(device_name, pattern):
                    return True
        return False

    def is_link_permitted(self, a_dev: str, b_dev: str, meta: dict, allow_oneway: Set[str]) -> bool:
        """
        Проверяет, разрешена ли связь согласно правилам фильтрации.
        Поддерживает маски устройств (ap-*, NWA*, etc.)

        Args:
            a_dev: Имя устройства A
            b_dev: Имя устройства B
            meta: Метаданные соединения
            allow_oneway: Множество имен/ролей/масок, для которых разрешены односторонние связи

        Returns:
            True если связь разрешена, иначе False
        """
        # Всегда разрешаем двусторонние связи
        if meta.get('bidirectional', False):
            return True
    
        # Получаем роли устройств
        a_role = self._get_device_role(a_dev)
        b_role = self._get_device_role(b_dev)
    
        # Проверяем разрешения для устройства A
        a_allowed = (
            self._matches_pattern(a_dev, allow_oneway) or  # По маске/имени
            (a_role and a_role in allow_oneway)            # По роли
        )
    
        # Проверяем разрешения для устройства B
        b_allowed = (
            self._matches_pattern(b_dev, allow_oneway) or  # По маске/имени
            (b_role and b_role in allow_oneway)            # По роли
        )
    
        return a_allowed or b_allowed

    def add_device(self, cd):
        """
        Добавляет устройство и его соединения, обновляя last_seen.
        Оптимизировано для снижения лишних поисков в словаре.
        """
        now = self.current_time
        self.devices[cd.nb_name] = cd

        for intf in cd.interfaces:
            # создаём ключи
            k_fwd = self._make_link_key(cd.nb_name, intf.name,
                                        intf.lldp_rem_name, intf.lldp_rem_port)
            k_rev = self._make_link_key(intf.lldp_rem_name, intf.lldp_rem_port,
                                        cd.nb_name, intf.name)

            # Случай 1: Если прямой ключ уже есть в обратном словаре, значит зеркальная связь уже была добавлена ранее в текущем run
            if k_fwd in self._reverse_keys:
                self.connections[k_rev]['bidirectional'] = True
                self.connections[k_rev]['last_seen'] = now
                continue
            
            # Случай 2: Поиск закешированного соединения
            if k_fwd in self.connections:
                self.connections[k_fwd]['last_seen'] = now
                self._reverse_keys.add(k_rev)
                if k_rev in self.connections:
                    # Удаляем зеркальное соединение, если оно есть
                    del self.connections[k_rev]
            else:
                # Случай 3: Создаем новое соединение
                self.connections[k_fwd] = {
                    "bidirectional": False,
                    "last_seen": now
                }
                self._reverse_keys.add(k_rev)

    # ---------- работа с кешем ----------
    def _read_cache_file(self, filename: str) -> dict:
        """
        Читает и возвращает данные из кеш-файла.
        Обработка ошибок вынесена и использует исключения.
        """
        if not os.path.isfile(filename):
            return {}

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            self._backup_invalid_cache(filename)
            raise DeviceCacheError(f"Invalid JSON in cache file {filename}: {e}")
        except Exception as e:
            self._backup_invalid_cache(filename)
            raise DeviceCacheError(f"Unexpected error loading cache: {e}")

    def _backup_invalid_cache(self, filename: str) -> None:
        """
        Создает резервную копию невалидного кеш-файла.
        """
        invalid_filename = f"{filename}.invalid.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            os.rename(filename, invalid_filename)
            logger.warning(f"Invalid cache backed up to {invalid_filename}")
        except OSError as e:
            logger.error(f"Failed to backup invalid cache: {e}")

    def load_cache(self, filename=CACHE_FILE):
        """
        Загружает кеш связей для текущей площадки.
        Обработка ошибок выполняется через исключения.
        """
        if not self.site:
            logger.error("Cannot load cache: no site specified")
            return

        try:
            # Чтение файла с обработкой ошибок через исключения
            cache_data = self._read_cache_file(filename)

            # Площадка отсутствует в кеше - нечего загружать
            if self.site not in cache_data:
                logger.info(f"No cached data found for site {self.site}")
                return

            # Загружаем данные текущей площадки
            site_connections = cache_data[self.site].get('connections', [])
            loaded_count = 0

            for entry in site_connections:
                try:
                    # Проверяем наличие всех необходимых полей
                    source_device = entry['source_device']
                    source_port = entry['source_port_norm']
                    target_device = entry['target_device']
                    target_port = entry['target_port_norm']
                    bidirectional = entry.get('bidirectional', False)
                    last_seen = entry.get('last_seen', 0)

                    k = (source_device, source_port, target_device, target_port)
                    self.connections[k] = {
                        "bidirectional": bidirectional,
                        "last_seen": last_seen
                    }

                    loaded_count += 1
                except KeyError:
                    # Пропускаем запись, если не хватает ключевых полей
                    continue

            logger.info(f"Loaded {loaded_count} cached connections for site {self.site}")
        except DeviceCacheError as e:
            logger.error(f"Cache loading error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during cache loading: {e}")

    def _cleanup_outdated_connections(self):
        """
        Удаляет соединения, не обновленные с момента создания снимка.
        """
        original_count = len(self.connections)

        # Оптимизировано - создаем новый словарь вместо удаления элементов
        updated_connections = {}
        for key, meta in self.connections.items():
            if meta['last_seen'] >= self.current_time:
                updated_connections[key] = meta

        self.connections = updated_connections

        removed_count = original_count - len(self.connections)
        if removed_count:
            logger.info(f"Removed {removed_count} outdated connections from cache")

    def save_cache(self, filename=CACHE_FILE):
        """
        Сохраняет кеш с учетом площадок.
        Оптимизировано для больших наборов данных.
        """
        if not self.site:
            logger.error("Cannot save cache: no site specified")
            return

        # Очищаем устаревшие соединения перед сохранением
        self._cleanup_outdated_connections()

        try:
            # Читаем существующий кеш других площадок
            existing_data = {}

            try:
                existing_data = self._read_cache_file(filename)
            except DeviceCacheError:
                # Если чтение не удалось, начинаем с пустого словаря
                logger.warning("Starting with empty cache due to previous errors")

            # Формируем данные текущей площадки
            connection_entries = []
            for (a_dev, a_port, b_dev, b_port), meta in self.connections.items():
                connection_entries.append({
                    "source_device": a_dev,
                    "source_port_norm": a_port,
                    "target_device": b_dev,
                    "target_port_norm": b_port,
                    "bidirectional": meta['bidirectional'],
                    "last_seen": meta['last_seen']
                })

            # Обновляем данные текущей площадки в общем словаре
            existing_data[self.site] = {"connections": connection_entries}

            # Сохраняем обновленные данные с минимальным форматированием для больших кешей
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2)
            logger.info(f"Cache saved for site {self.site}: {filename}")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    # ---------- вывод в консоль ----------
    def show(self):
        for (a_dev,a_port,b_dev,b_port),meta in self.connections.items():
            direction = '<->' if meta['bidirectional'] else '->'
            logger.info(f'{a_dev}:{a_port} {direction} {b_dev}:{b_port}')

    # ----------- Утилиты для экспорта -----------
    def _style_dict_to_str(self, style_dict: dict) -> str:
        """
        Преобразует словарь стилей в строку для вставки в графические форматы.
        """
        return ', '.join([f'{k}="{v}"' for k, v in style_dict.items()])

    def _build_port_label(self, ports: List[Tuple[str, str]], position: int, is_lag: bool, 
                         max_ports: int) -> str:
        """
        Создает метку для портов с учетом LAG и максимального количества портов.

        Args:
            ports: Список кортежей (порт_источника, порт_назначения)
            position: 0 для источника, 1 для назначения
            is_lag: True если это LAG-соединение
            max_ports: Максимальное кол-во портов в метке

        Returns:
            Отформатированная строка метки
        """
        if not ports:
            return ""

        if not is_lag:
            # Для обычного соединения показываем только порт
            port = ports[0][position]
            return port if port else ""

        # Для LAG формируем список портов
        label = "LAG: "

        # Собираем до max_ports портов
        for port_pair in ports[:max_ports]:
            port = port_pair[position]
            if port:
                label += f"{port} "

        # Если портов больше чем лимит - добавляем "и еще X"
        if len(ports) > max_ports:
            label += f"&lt;div&gt;...и ещё {len(ports) - max_ports}&lt;/div&gt;"

        return label

    # ---------- экспорт в DOT ----------
    def export_to_dot_pretty(self, filename=None):
        """
        Export topology to DOT format with pretty settings for draw.io
        Refactored for better separation of concerns.
        """
        if filename is None:
            filename = f"topology_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dot"

        # Проверка, что есть устройства для экспорта
        if not self.devices:
            logger.warning("No devices to export!")
            return None

        with open(filename, 'w', encoding='utf-8') as f:
            # Экспортируем заголовок и глобальные настройки
            self._export_dot_header(f)

            # Экспортируем узлы
            self._export_dot_nodes(f)

            f.write('\n')

            # Экспортируем связи
            self._export_dot_edges(f)

            f.write('}\n')

        logger.info(f"Pretty DOT exported to: {filename}")

        # Создаем SVG если доступен Graphviz
        self._generate_svg(filename)

        return filename

    def _export_dot_header(self, file):
        """
        Записывает заголовок и глобальные настройки DOT.
        """
        file.write('digraph network {\n')
        file.write(f'  rankdir={DOT_GLOBAL_SETTINGS["rankdir"]};\n')

        # Настройки узлов по умолчанию
        node_defaults = DOT_GLOBAL_SETTINGS['node_default']
        file.write(f'  node [fontname="{node_defaults["fontname"]}", fontsize="{node_defaults["fontsize"]}"];\n')

        # Настройки рёбер по умолчанию
        edge_defaults = DOT_GLOBAL_SETTINGS['edge_default']
        file.write(f'  edge [fontname="{edge_defaults["fontname"]}", fontsize="{edge_defaults["fontsize"]}"];\n\n')

    def _export_dot_nodes(self, file):
        """
        Записывает описание узлов в DOT файл.
        """
        for name, device_obj in self.devices.items():
            # Преобразуем в словарь, если это объект
            device = self._device_to_dict(device_obj)

            # Получаем роль устройства и соответствующий стиль
            role = device.get('role', '')

            # Используем кеш стилей для ролей
            if role not in self._role_style_cache:
                style_dict = NODE_STYLES.get(role, NODE_STYLES['DEFAULT'])
                self._role_style_cache[role] = self._style_dict_to_str(style_dict)

            style_str = self._role_style_cache[role]

            # Записываем узел с необходимыми атрибутами
            model = device.get('model', '')
            ip = device.get('ip', '')
            file.write(f'  "{name}" [{style_str}, label="{name}\\n{model}", tooltip="{ip}"];\n')

    def _export_dot_edges(self, file):
        """
        Записывает описание связей в DOT файл.
        """
        for (a_dev, a_port, b_dev, b_port), meta in self.connections.items():
            if meta['bidirectional']:
                file.write(f'  "{a_dev}" -> "{b_dev}" [dir=both, label="{a_port}\\n{b_port}"];\n')
            else:
                file.write(f'  "{a_dev}" -> "{b_dev}" [label="{a_port}"];\n')

    def _generate_svg(self, dot_filename):
        """
        Генерирует SVG из DOT файла используя Graphviz.
        """
        try:
            import subprocess
            svg_file = f"{dot_filename}.svg"
            subprocess.run(['dot', '-Tsvg', dot_filename, '-o', svg_file], check=True)
            logger.info(f"SVG created: {svg_file} - import this into draw.io")
        except Exception as e:
            logger.warning(f"Could not create SVG (is Graphviz installed?): {e}")
            logger.info(f"Install Graphviz and run: dot -Tsvg {dot_filename} -o {dot_filename}.svg")

    # ---------- Агрегация связей для экспорта ----------
    def _aggregate_links(self):
        """
        Агрегирует множественные соединения между одинаковыми парами устройств (LAG).

        Оптимизировано для исключения повторного вызова `sorted` в цикле.

        Returns:
            dict: {(dev_a, dev_b): {'ports': [(port_a1, port_b1), ...], 'bidirectional': bool}}
        """
        aggregated_links = {}

        for (a_dev, a_port, b_dev, b_port), meta in self.connections.items():
            # Создаем ключ, сравнивая строки напрямую (без вызова sorted)
            if a_dev < b_dev:
                devices_pair = (a_dev, b_dev)
                port_pair = (a_port, b_port)
            else:
                devices_pair = (b_dev, a_dev)
                port_pair = (b_port, a_port)

            # Если это первая связь между этими устройствами, инициализируем запись
            if devices_pair not in aggregated_links:
                aggregated_links[devices_pair] = {
                    'ports': [],
                    'bidirectional': meta.get('bidirectional', False)
                }
            else:
                # Обновляем bidirectional, если хотя бы одна связь двунаправленная
                aggregated_links[devices_pair]['bidirectional'] |= meta.get('bidirectional', False)

            # Добавляем пару портов в список
            aggregated_links[devices_pair]['ports'].append(port_pair)

        return aggregated_links

    # ---------- Слияние настроек ----------
    def _merge_settings(self, base_settings: dict, custom_settings: Optional[dict] = None) -> dict:
        """
        Рекурсивно объединяет базовые настройки с пользовательскими.

        Args:
            base_settings: Исходные настройки
            custom_settings: Пользовательские настройки (опционально)

        Returns:
            dict: Объединенный словарь настроек
        """
        if not custom_settings:
            return base_settings

        result = base_settings.copy()

        for k, v in custom_settings.items():
            if k in result and isinstance(v, dict) and isinstance(result[k], dict):
                result[k] = self._merge_settings(result[k], v)
            else:
                result[k] = v

        return result

    # ---------- Методы записи XML ----------
    def _write_xml_to_file(self, filename: str, xml_lines: List[str]):
        """
        Записывает список строк XML в файл.
        Оптимизировано для больших объемов данных.
        """
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                for line in xml_lines:
                    f.write(line + '\n')
        except Exception as e:
            logger.error(f"Failed to write XML file {filename}: {e}")
            raise

    def _generate_xml_header(self) -> List[str]:
        """
        Генерирует заголовок XML для draw.io.

        Returns:
            List[str]: Строки XML-заголовка
        """
        return [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<mxfile host="NetTopographer" agent="NetTopographer/1.0" version="1.0">',
            '  <diagram name="Page-1" id="network_topology">',
            '    <mxGraphModel dx="1434" dy="844" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1100" pageHeight="1100" math="0" shadow="0">',
            '      <root>',
            '        <mxCell id="0" />',
            '        <mxCell id="1" parent="0" />'
        ]

    def _generate_xml_footer(self) -> List[str]:
        """
        Генерирует завершающую часть XML для draw.io.

        Returns:
            List[str]: Строки XML-футера
        """
        return [
            '      </root>',
            '    </mxGraphModel>',
            '  </diagram>',
            '</mxfile>'
        ]

    def _generate_device_xml(self, settings: dict) -> Tuple[List[str], Dict[str, str]]:
        """
        Генерирует XML для устройств.

        Args:
            settings: Настройки для экспорта

        Returns:
            Tuple[List[str], Dict[str, str]]: XML строки и словарь device_ids
        """
        device_style = settings['device_style']
        grid_settings = settings['grid']
        cols = grid_settings['columns']
        h = grid_settings['horizontal_step']
        v = grid_settings['vertical_step']
        offset = grid_settings['initial_offset']

        devices_xml = []
        device_ids = {}

        for idx, (name, device_obj) in enumerate(self.devices.items()):
            # Вычисляем позицию в сетке
            x = (idx % cols) * h + offset
            y = (idx // cols) * v + offset

            # Преобразуем в словарь
            device = self._device_to_dict(device_obj)

            # Получаем роль устройства и соответствующий стиль
            role = device.get('role', '')
            cisco_style = CISCO_STYLES.get(role, CISCO_STYLES['default'])

            # Генерируем уникальный ID для устройства
            device_id = f"device_{idx}"
            device_ids[name] = device_id

            # Формируем стиль устройства
            style_parts = [cisco_style]
            for k, v in device_style.items():
                style_parts.append(f"{k}={v}")
            style_str = ''.join(f"{p};" for p in style_parts)

            # Создаем ячейку устройства
            devices_xml.append(f'        <mxCell id="{device_id}" value="{name}" style="{style_str}" vertex="1" parent="1">')
            devices_xml.append(f'          <mxGeometry x="{x}" y="{y}" width="{device_style["width"]}" height="{device_style["height"]}" as="geometry" />')
            devices_xml.append(f'        </mxCell>')

        return devices_xml, device_ids

    def _add_port_label(self, connections_xml: List[str], conn_id: str, label: str, 
                       position: str, align: str, label_id: str):
        """
        Добавляет метку порта к соединению в XML.

        Args:
            connections_xml: Список для добавления XML строк
            conn_id: ID соединения
            label: Текст метки
            position: Позиция на линии
            align: Выравнивание текста
            label_id: ID метки
        """
        connections_xml.append(f'        <mxCell id="{label_id}" value="{label}" style="edgeLabel;html=1;align={align};verticalAlign=middle;resizable=0;points=[];" vertex="1" connectable="0" parent="{conn_id}">')
        connections_xml.append(f'          <mxGeometry x="{position}" y="0" relative="1" as="geometry">')
        connections_xml.append(f'            <mxPoint as="offset" />')
        connections_xml.append(f'          </mxGeometry>')
        connections_xml.append(f'        </mxCell>')

    def _generate_connections_xml(self, device_ids: Dict[str, str], settings: dict) -> List[str]:
        """
        Генерирует XML для связей между устройствами.

        Args:
            device_ids: Словарь ID устройств
            settings: Настройки для экспорта

        Returns:
            List[str]: Список строк XML для соединений
        """
        connection_style = settings['connection_style']
        port_labels = settings['port_labels']
        max_ports = port_labels['max_ports']

        connections_xml = []
        aggregated_links = self._aggregate_links()
        conn_idx = 0

        for (dev_a, dev_b), link_data in aggregated_links.items():
            # Пропускаем, если одно из устройств не найдено
            if dev_a not in device_ids or dev_b not in device_ids:
                continue

            conn_id = f"conn_{conn_idx}"
            conn_idx += 1

            # Получаем информацию о портах
            ports = link_data['ports']
            is_lag = len(ports) > 1

            # Формируем метки для портов
            source_label = self._build_port_label(ports, 0, is_lag, max_ports)
            target_label = self._build_port_label(ports, 1, is_lag, max_ports)

            # Определяем стиль соединения
            link_type = 'normal' if link_data.get('bidirectional', False) else 'oneway'
            conn_type = 'lag' if is_lag else 'single'
            edge_style = connection_style[link_type][conn_type]

            # Добавляем соединение
            connections_xml.append(f'        <mxCell id="{conn_id}" value="" style="{edge_style}" edge="1" parent="1" source="{device_ids[dev_a]}" target="{device_ids[dev_b]}">')
            connections_xml.append(f'          <mxGeometry width="50" height="50" relative="1" as="geometry">')
            connections_xml.append(f'            <mxPoint x="0" y="0" as="sourcePoint" />')
            connections_xml.append(f'            <mxPoint x="0" y="0" as="targetPoint" />')
            connections_xml.append(f'          </mxGeometry>')
            connections_xml.append(f'        </mxCell>')

            # Добавляем исходную метку (для портов устройства A)
            if source_label:
                self._add_port_label(connections_xml, conn_id, source_label, 
                                   port_labels['source']['position'], 
                                   port_labels['source']['align'], 
                                   f"source_label_{conn_idx}")

            # Добавляем целевую метку (для портов устройства B)
            if target_label:
                self._add_port_label(connections_xml, conn_id, target_label, 
                                   port_labels['target']['position'], 
                                   port_labels['target']['align'], 
                                   f"target_label_{conn_idx}")

        return connections_xml

    # ---------- Главный метод экспорта в draw.io ----------
    def export_to_drawio_cisco(self, filename: str, custom_settings: Optional[dict] = None):
        """
        Экспортирует топологию в формат draw.io с использованием Cisco иконок
        и агрегацией LAG-соединений. Разбито на отдельные методы для лучшей читаемости.

        Args:
            filename: имя файла для сохранения
            custom_settings: Настройки для переопределения значений из config.py
        """
        if not self.devices:
            logger.warning("No devices to export!")
            return

        # Применяем пользовательские настройки
        settings = self._merge_settings(DRAWIO_SETTINGS, custom_settings)

        # Генерируем XML по частям
        xml_lines = []

        # Заголовок
        xml_lines.extend(self._generate_xml_header())

        # Устройства
        devices_xml, device_ids = self._generate_device_xml(settings)

        # Соединения
        connections_xml = self._generate_connections_xml(device_ids, settings)

        # Определяем порядок добавления элементов согласно настройкам
        layer_order = settings['layer_order']
        elements_by_type = {
            'devices': devices_xml,
            'connections': connections_xml
        }

        # Добавляем элементы в соответствии с порядком слоев
        for layer in layer_order:
            if layer in elements_by_type:
                xml_lines.extend(elements_by_type[layer])

        # Футер
        xml_lines.extend(self._generate_xml_footer())

        # Записываем в файл
        self._write_xml_to_file(filename, xml_lines)
        logger.info(f"Draw.io diagram exported to: {filename}")

    # ---------- Фильтрация топологии ----------
    def _create_placeholder(self, dev_name: str) -> dict:
        """Создаёт минимальную запись устройства для отрисовки."""
        return {
            'nb_name': dev_name,
            'hostname': dev_name,
            'ip': '',
            'model': '',
            'serial': '',
            'role': ''
        }

    def get_bidirectional_topology(self, allow_oneway: Set[str]) -> 'Topology':
        """
        Возвращает топологию, содержащую:
        • все bidirectional-связи
        • а также любые связи, если в них участвует устройство,
          указанное в allow_oneway (по имени или по роли).

        Args:
            allow_oneway: Множество имен устройств или ролей, для которых разрешены односторонние связи

        Returns:
            Topology: Новый экземпляр топологии с отфильтрованными связями
        """
        if allow_oneway is None:
            allow_oneway = set()

        # Создаем новую топологию с той же площадкой
        filtered_topo = Topology(self.site)
        filtered_topo.devices = self.devices.copy()  # Копируем все известные устройства
    
        for (a, ap, b, bp), meta in self.connections.items():
            if self.is_link_permitted(a, b, meta, allow_oneway):
                # Добавляем связь
                filtered_topo.connections[(a, ap, b, bp)] = meta

                # Создаём placeholder только для разрешённых устройств, которых ещё нет
                if a not in filtered_topo.devices and self._matches_pattern(a, allow_oneway):
                    filtered_topo.devices[a] = self._create_placeholder(a)
                if b not in filtered_topo.devices and self._matches_pattern(b, allow_oneway):
                    filtered_topo.devices[b] = self._create_placeholder(b)

        return filtered_topo