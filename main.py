#!/usr/bin/env python3
"""A script to import picasa.ini files into digiKam's SQLite database."""

import logging
import shutil
import sys
import time
from argparse import ArgumentParser
from pathlib import Path

import digikam_db
import migrator


def init_argparse() -> ArgumentParser:
    parser = ArgumentParser('Import picasa.ini files into a digiKam SQLite database.')
    parser.add_argument('--photos_dir', required=True, type=Path,
                        help='Path to a root directory with photos and picasa.ini files to be imported')
    parser.add_argument('--digikam_db', required=True, type=Path,
                        help='Filename of digiKam\'s digikam4.db file.')
    parser.add_argument('--contacts', required=False, type=Path,
                        help='Optional filename of Picasa''s contacts.xml file')
    parser.add_argument('--dry_run', action='store_true')
    parser.add_argument('--verbose', '-v', action='count', default=0,
                        help='Log verbosity. Pass -vv to see debug output.')
    return parser


def main() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    log_handler = logging.StreamHandler(sys.stdout)
    root_logger.setLevel(logging.DEBUG)
    log_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    root_logger.addHandler(log_handler)

    parser = init_argparse()
    args = parser.parse_args()
    log_handler.setLevel(30 - (10 * args.verbose))

    if not args.dry_run:
        backup_path = '%s.bak.%i' % (args.digikam_db, time.time())
        logging.info('Creating database backup at %s')
        shutil.copyfile(args.digikam_db, backup_path)

    logging.info('Inspecting existing digiKam database')
    db = digikam_db.DigikamDb(args.digikam_db)
    logging.info(db)

    logging.info('Traversing input directories')
    with db.conn:  # Transaction
        migrator.migrate_directories_under(input_root_dir=args.photos_dir, db=db, 
                                           dry_run=args.dry_run,
                                           contacts_file=args.contacts)
    db.close()

    logging.info('Done')


if __name__ == '__main__':
    main()
