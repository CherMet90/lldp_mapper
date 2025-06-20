 ## Анализ импортов и зависимостей между модулями

### 1. Текущая структура импортов

```python
# main.py импортирует:
from topology import Topology
from device_collector import snmp_query_device
from config import NETWORK_ROLES, NETBOX_CF
# + внешние модули: custom_modules.netbox_connector, custom_modules.error_handling, custom_modules.errors, custom_modules.log

# device_collector.py импортирует:
# только внешние модули: custom_modules.snmp, custom_modules.errors, custom_modules.log

# topology.py импортирует:
from config import DOT_GLOBAL_SETTINGS, DRAWIO_SETTINGS, NODE_STYLES, PORT_NAME_SUBSTITUTIONS, CACHE_FILE, CISCO_STYLES
# + внешние модули: custom_modules.log

# config.py:
# Не импортирует ничего (только стандартная библиотека typing)
```

### 2. Анализ текущей архитектуры

**Плюсы:**
- Нет циклических зависимостей
- config.py является чистым модулем настроек без зависимостей
- Четкое разделение ответственности между модулями

**Минусы:**
- topology.py перегружен функциональностью (1000+ строк)
- Прямые зависимости от внешних модулей разбросаны по коду
- Отсутствуют абстракции для внешних сервисов

### 3. Предложения по рефакторингу

#### 3.1. Разделение topology.py

```python
# topology/core.py - Основная логика топологии
class Topology:
    def __init__(self, site_slug=None)
    def add_device(self, cd)
    def _make_link_key(self, a_dev, a_port, b_dev, b_port)
    def is_link_permitted(self, a_dev, b_dev, meta, allow_oneway)
    def get_bidirectional_topology(self, allow_oneway)
    def show(self)

# topology/cache.py - Работа с кешем
class TopologyCache:
    def __init__(self, site_slug)
    def load(self, filename=CACHE_FILE)
    def save(self, topology, filename=CACHE_FILE)
    def _cleanup_outdated_connections(self, connections, current_time)

# topology/exporters/dot_exporter.py
class DotExporter:
    def export(self, topology, filename)
    def _generate_svg(self, dot_filename)

# topology/exporters/drawio_exporter.py
class DrawioExporter:
    def export(self, topology, filename, custom_settings=None)
    def _aggregate_links(self, connections)
```

#### 3.2. Создание абстракций для внешних сервисов

```python
# interfaces/netbox_interface.py
from abc import ABC, abstractmethod

class NetboxInterface(ABC):
    @abstractmethod
    def get_devices(self, site_slug, roles):
        pass

# interfaces/snmp_interface.py
class SNMPInterface(ABC):
    @abstractmethod
    def query_device(self, ip, community, version):
        pass

# interfaces/logger_interface.py
class LoggerInterface(ABC):
    @abstractmethod
    def info(self, message):
        pass
    
    @abstractmethod
    def error(self, message):
        pass
```

#### 3.3. Внедрение зависимостей

```python
# main.py - с внедрением зависимостей
class TopologyBuilder:
    def __init__(self, netbox_client: NetboxInterface, 
                 snmp_client: SNMPInterface,
                 logger: LoggerInterface):
        self.netbox = netbox_client
        self.snmp = snmp_client
        self.logger = logger
    
    def process_site(self, site_slug, topology=None):
        # логика без прямых импортов custom_modules
        pass

# device_collector.py - рефакторинг
class DeviceCollector:
    def __init__(self, snmp_client: SNMPInterface, logger: LoggerInterface):
        self.snmp = snmp_client
        self.logger = logger
    
    def collect_device_data(self, nb_device, community_cf, version_cf):
        # использует self.snmp вместо прямого импорта
        pass
```

#### 3.4. Новая структура проекта

```
NetTopographer/
├── main.py
├── config.py
├── interfaces/
│   ├── __init__.py
│   ├── netbox_interface.py
│   ├── snmp_interface.py
│   └── logger_interface.py
├── implementations/
│   ├── __init__.py
│   ├── netbox_client.py
│   ├── snmp_client.py
│   └── logger_client.py
├── collectors/
│   ├── __init__.py
│   └── device_collector.py
├── topology/
│   ├── __init__.py
│   ├── core.py
│   ├── cache.py
│   └── exporters/
│       ├── __init__.py
│       ├── base_exporter.py
│       ├── dot_exporter.py
│       └── drawio_exporter.py
├── models/
│   ├── __init__.py
│   └── device_models.py
└── utils/
    ├── __init__.py
    └── port_normalizer.py
```

### 4. Преимущества предложенной архитектуры

1. **Модульность**: Каждый модуль отвечает за одну задачу
2. **Тестируемость**: Легко создавать моки для интерфейсов
3. **Расширяемость**: Новые экспортеры добавляются без изменения core
4. **Независимость**: Замена SNMP на другой протокол требует изменения только implementation
5. **Читаемость**: Файлы меньше, логика яснее

### 5. Пример рефакторинга для внедрения

```python
# models/device_models.py
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class CollectedInterface:
    name: str
    lldp_rem_name: str = ''
    lldp_rem_port: Optional[str] = None

@dataclass
class CollectedDevice:
    nb_name: str
    ip: str
    hostname: str
    model: str
    serial: str
    role: str = ''
    interfaces: List[CollectedInterface] = field(default_factory=list)

# topology/exporters/base_exporter.py
from abc import ABC, abstractmethod

class BaseExporter(ABC):
    @abstractmethod
    def export(self, topology, filename, **kwargs):
        pass
```

Такая архитектура обеспечит лучшую поддерживаемость, тестируемость и возможность расширения функциональности без изменения существующего кода.