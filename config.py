"""
Главный конфиг проекта для задания глобальных констант, паттернов нормализации, и настроек взаимодействия с NetBox.
"""

from typing import Dict, List, Tuple

# Роли устройств, которые участвуют в построении топологии (преимущественно свичи)
NETWORK_ROLES: List[str] = [
    'poe-switch',
    'access-switch',
    'aggregation-switch',
    'industrial-switch',
    'l3-switch',
    'server-switch',
]

# NetBox custom fields для получения SNMP community и версии
NETBOX_CF = {
    'SNMP_COMMUNITY': 'snmp_community',  # Имя поля для community
    'SNMP_VERSION': 'snmp_version',      # Имя поля для версии SNMP
}

# Шаблоны для нормализации имен портов (например, Gi0/1 == GigabitEthernet0/1)
PORT_NAME_SUBSTITUTIONS: List[Tuple[str, str]] = [
    (r'GigabitEthernet',    'gi'),
    (r'TenGigabitEthernet', 'te'),
    (r'FortyGigabitEthernet','fo'),
    (r'HundredGigabitEthernet','hu'),
    (r'FastEthernet',       'fa'),
    (r'Ethernet',           'et'),
    (r'Port-Channel',       'po'),
]

# Имя файла для кеширования топологии
CACHE_FILE = 'topology_cache.json'

# Стили узлов для каждой роли в DOT (Graphviz)
# По умолчанию устройства получают стиль DEFAULT если нет соответствия
NODE_STYLES: Dict[str, Dict[str, str]] = {
    'poe-switch': {
        'fillcolor': 'lightblue',
        'style': 'rounded,filled',
        'shape': 'box',
    },
    'access-switch': {
        'fillcolor': 'lightyellow',
        'style': 'rounded,filled',
        'shape': 'box',
    },
    'aggregation-switch': {
        'fillcolor': 'lightgreen',
        'style': 'rounded,filled',
        'shape': 'box',
    },
    'industrial-switch': {
        'fillcolor': 'lightsalmon',
        'style': 'rounded,filled',
        'shape': 'box',
    },
    'l3-switch': {
        'fillcolor': 'lightpink',
        'style': 'rounded,filled',
        'shape': 'box',
    },
    'server-switch': {
        'fillcolor': 'lightcyan',
        'style': 'rounded,filled',
        'shape': 'box',
    },
    'DEFAULT': {
        'fillcolor': 'white',
        'style': 'rounded',
        'shape': 'box',
    }
}

# Общие настройки для Graphviz
DOT_GLOBAL_SETTINGS = {
    'rankdir': 'TB',  # направление графа (TB = сверху вниз)
    'node_default': {
        'fontname': 'Arial',
        'fontsize': '10',
    },
    'edge_default': {
        'fontname': 'Arial',
        'fontsize': '8',
    }
}

CISCO_STYLES = {
    'default': 'shape=mxgraph.cisco_safe.design.blank_device;',
    'poe-switch': 'shape=mxgraph.cisco19.rect;prIcon=l2_switch;',
    'access-switch': 'shape=mxgraph.cisco19.rect;prIcon=l2_switch;',
    'aggregation-switch': 'shape=mxgraph.cisco19.rect;prIcon=l2_switch;',
    'industrial-switch': 'shape=mxgraph.cisco19.rect;prIcon=l2_switch;',
    'l3-switch': 'shape=mxgraph.cisco19.rect;prIcon=l3_switch;',
    'server-switch': 'shape=mxgraph.cisco19.rect;prIcon=l2_switch;',
}

# Настройки экспорта в draw.io
DRAWIO_SETTINGS = {
    # Общие настройки
    'grid': {
        'columns': 5,           # узлов по горизонтали
        'horizontal_step': 180, # шаг сетки по горизонтали (px)
        'vertical_step': 140,   # шаг сетки по вертикали (px)
        'initial_offset': 100   # отступ от левого верхнего угла (px)
    },

    # Порядок элементов на схеме (чем ниже в списке, тем выше на схеме)
    'layer_order': ['connections', 'devices'],  # варианты: 'connections', 'devices'

    # Стили устройств
    'device_style': {
        'fillColor': '#FAFAFA',
        'strokeColor': '#005073',
        'labelBackgroundColor': 'default',
        'verticalLabelPosition': 'center',
        'align': 'center',
        'verticalAlign': 'center',
        'aspect': 'fixed',
        'width': 50,
        'height': 50
    },

    # Стили соединений
    'connection_style': {
        'normal': {
            'single': 'endArrow=classic;startArrow=classic;html=1;rounded=0;',
            'lag': 'endArrow=classic;startArrow=classic;html=1;rounded=0;shape=link;'
        },
        'oneway': {
            'single': 'endArrow=classic;html=1;rounded=0;',
            'lag': 'endArrow=classic;html=1;rounded=0;shape=link;'
        }
    },

    # Отображение меток портов
    'port_labels': {
        'source': {
            'position': '-0.5',  # положение на линии (-1.0 у начала, 0 в середине, 1.0 у конца)
            'align': 'center'
        },
        'target': {
            'position': '0.5',
            'align': 'center'
        },
        # Максимальное число портов в метке перед сокращением "и еще X"
        'max_ports': 3
    }
}