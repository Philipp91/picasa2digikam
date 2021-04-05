#!/usr/bin/env python3
"""A script to import picasa.ini files into digiKam's SQLite database."""

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

import digikam_db
import migrator


def init_argparse() -> ArgumentParser:
    parser = ArgumentParser('Import picasa.ini files into a digiKam SQLite database.')
    parser.add_argument('--photos_dir', required=True, type=Path,
                        help='Path to a root directory with photos and picasa.ini files to be imported')
    parser.add_argument('--digikam_db', required=True, type=Path,
                        help='Path do digiKam\'s digikam4.db file.')
    parser.add_argument('--dry_run', action='store_true')
    parser.add_argument('--verbose', '-v', action='count', default=5,
                        help='Log verbosity. E.g. pass -vvvvvv to see debug output.')
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
    log_handler.setLevel(70 - (10 * args.verbose) if args.verbose > 0 else 0)

    logging.info('Inspecting existing digiKam database')
    db = digikam_db.DigikamDb(args.digikam_db)
    logging.info(db)

    logging.info('Traversing input directories')
    with db.conn:  # Transaction
        migrator.migrate_directories_under(input_root_dir=args.photos_dir, db=db, dry_run=args.dry_run)
    db.close()


if __name__ == '__main__':
    main()
