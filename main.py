import argparse
import os

from custom_modules.netbox_connector import NetboxDevice
from custom_modules.error_handling import print_errors
from custom_modules.errors import Error
from custom_modules.log import logger

from topology import Topology
from device_collector import snmp_query_device
from config import NETWORK_ROLES, NETBOX_CF

def fetch_netbox_devices(site_slug):
    """Get network devices from NetBox for the given site"""
    NetboxDevice.create_connection()
    devices = NetboxDevice.get_netbox_objects(
        'dcim', 'devices', action='filter',
        site=site_slug, role=NETWORK_ROLES
    )
    logger.info(f"Found {len(devices) if devices else 0} network devices at site {site_slug}")
    return devices

def process_site(site_slug, topo=None):
    """Process all network devices at the site and build topology"""
    if topo is None:
        topo = Topology()

    nb_devices = fetch_netbox_devices(site_slug)
    if not nb_devices:
        raise Error(f'No devices at site {site_slug}')

    for nb_dev in nb_devices:
        try:
            cd = snmp_query_device(
                nb_dev,
                NETBOX_CF['SNMP_COMMUNITY'],
                NETBOX_CF['SNMP_VERSION']
            )
            topo.add_device(cd)

        except Error as e:
            logger.error(f"Error processing {nb_dev.name}: {str(e)}")
            continue
        except Exception as e:
            Error.store_error(nb_dev.name, str(e))
            logger.error(f"Unexpected error for {nb_dev.name}: {str(e)}")
            continue
        finally:
            print('-'*70)  # Разделитель устройств для читаемости лога

    return topo

def get_export_filename(site_slug, bidirectional=False, mixed=False):
    """Генерирует имя файла для экспорта топологии"""
    if bidirectional:
        suffix = "_bi_mixed" if mixed else "_bi"
    else:
        suffix = ""
    return f"topology_{site_slug}{suffix}.dot"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True)
    ap.add_argument('--export-dot', action='store_true', 
                    help="Export topology to DOT and SVG formats")
    ap.add_argument('--export-drawio', action='store_true',
                    help='Export topology to draw.io format with Cisco icons')
    ap.add_argument('--only-bidirectional', action='store_true', 
                  help='Include only devices with bidirectional connections')
    ap.add_argument(
        '--allow-oneway', nargs='*', default=[],
        help='Device names or roles for which one-way links are allowed even in '
         '--only-bidirectional mode'
    )
    args = ap.parse_args()

    # Инициализируем топологию с указанием площадки
    topo = Topology(args.site)

    # Загружаем кеш для указанной площадки
    topo.load_cache()

    # Обрабатываем устройства сайта
    process_site(args.site, topo)

    # вывод актуальной картины
    total_devices = len(topo.devices)
    total_links = len(topo.connections)
    logger.info(f'{total_devices} devices, {total_links} links total')

    # Ограничиваем вывод при большом количестве связей
    if total_links > 200:
        logger.info("Many connections found, skipping detailed output. Use --export for visualization.")
    else:
        topo.show()

    # Определяем, будет ли вообще какой-то экспорт
    export_requested = args.export_dot or args.export_drawio

    # Экспорт топологии
    if export_requested:
        # Создаем директорию при необходимости
        export_dir = 'diagrams'
        os.makedirs(export_dir, exist_ok=True)

        # Общая логика применения фильтров - выполняем один раз
        allow = set(args.allow_oneway)
        if args.only_bidirectional:
            topo_to_export = topo.get_bidirectional_topology(allow)
            has_allow = bool(allow)
        else:
            topo_to_export = topo
            has_allow = False

        # Экспорт в DOT/SVG
        if args.export_dot:
            fname = get_export_filename(args.site, bidirectional=args.only_bidirectional, mixed=has_allow)
            export_path = os.path.join(export_dir, fname)
            logger.info(f"Exporting topology to DOT/SVG: {export_path}")
            topo_to_export.export_to_dot_pretty(export_path)

        # Экспорт в draw.io
        if args.export_drawio:
            drawio_file = os.path.join(export_dir, 
                                    f"topology_{args.site}{'_bi' if args.only_bidirectional else ''}.drawio")
            logger.info(f"Exporting topology to draw.io: {drawio_file}")
            topo_to_export.export_to_drawio_cisco(drawio_file)

    topo.save_cache()                   # пишем обновлённый cache
    print_errors()

if __name__ == '__main__':
    main()