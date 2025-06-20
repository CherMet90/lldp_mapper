#### NetTopographer
**NetTopographer** — инструмент автоматического построения и визуализации топологии сети на основе LLDP-данных с устройств NetBox.
<br>

##### Требования
* **Python** — разработан и тестировался на версии **3.12.0**
* **Graphviz** — установленная CLI-утилита `dot` (для экспорта SVG/DOT)
* **NetBox** — необходимы корректные роли устройств и заполненные custom fields (`snmp_community`, `snmp_version`) для SNMP-опроса
* **Зависимости Python** — устанавливаются через:
```
bash
  pip install -r requirements.txt
```
* Для Windows: необходимо, чтобы путь к исполняемому файлу `dot.exe` был в переменной окружения `PATH`
<br>

##### Возможности
* Опрос сетевых устройств через SNMP, используя роли из NetBox.
* Сбор и агрегирование информации о связях (LLDP).
* Универсальная нормализация портов для корректного сопоставления разных вендоров
* Выделение двусторонних (bidirectional) и односторонних связей, экспорт только подтверждённых звеньев по желанию
* Экспорт схемы в DOT и SVG, а также в draw.io XML (с поддержкой Cisco-иконок и LAG-связей)
* Гибкая конфигурация ролей, нормализации и стиля схем через `config.py`.
* Кеширование информации о связях между устройствами.
* Управление экспортом и фильтрацией через аргументы командной строки.
<br>

##### Конфигурация
Все основные настройки хранятся в `config.py`:
- Список ролей устройств для опроса (`NETWORK_ROLES`)
- Словарь нормализации имен портов (`PORT_NAME_SUBSTITUTIONS`)
- Настройки стилей для Graphviz (`NODE_STYLES`, `DOT_GLOBAL_SETTINGS`)
- Имена кастомных полей NetBox (`NETBOX_CF`)
<br>

##### Примеры запуска
```
# Экспорт только в DOT/SVG:
python main.py --site my_site --export-dot

# Экспорт только в draw.io:
python main.py --site my_site --export-drawio

# Экспорт в оба формата:
python main.py --site my_site --export-dot --export-drawio

# С фильтрацией для обоих форматов:
python main.py --site my_site --export-dot --export-drawio --only-bidirectional

# Исключения (разрешить one-way для указанных ролей или имён):
python main.py --site <site_slug> --export-dot --export-drawio --only-bidirectional --only-bidirectional --allow-oneway aggregation-switch my-special-switch
```
<br>

##### Визуализация
Файлы схемы (SVG/DOT и .drawio XML) сохраняются в директорию `diagrams/`.
XML-файл можно напрямую Открывать в draw.io для редактирования и размещения на схеме с сохранением стилей.
<br>

##### FAQ
* Q: Почему некоторые устройства не отображаются на схеме?
A: Вы включили режим only-bidirectional и у устройства только односторонние связи.
Используйте `--allow-oneway` или проверьте настройки LLDP/SNMP на устройстве.

* Q: Как изменить цвет для своей роли?
A: Добавьте или модифицируйте стиль в `NODE_STYLES` в `config.py`.