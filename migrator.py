"""Migrates metadata of photos from .picasa.ini files to a digiKam SQLite database."""

import configparser
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from digikam_db import DigikamDb
import rect64

_PICASA_INI_FILE = '.picasa.ini'
_PICASA_TAG_NAME = 'Picasa'
_UNKNOWN_FACE_ID = 'ffffffffffffffff'
_FACE_TAG_REGION_PROPERTY = 'tagRegion'

ContactTags = Dict[str, Optional[int]]


def _is_photo_file(file: str) -> bool:
    file = file.lower()
    return file.endswith('.jpg') or file.endswith('.jpeg') or file.endswith('.raw') or file.endswith('.psd')


def migrate_directories_under(input_root_dir: Path, db: DigikamDb, dry_run: bool):
    """Traverses directory tree to find directories to migrate."""
    contact_tags_per_dir: Dict[Path, ContactTags] = {}
    for input_dir, subdirs, files in os.walk(input_root_dir):
        dir = Path(input_dir)
        if _PICASA_INI_FILE in files:
           contact_tags_per_dir[dir] = migrate_directory(dir, files, db, contact_tags_per_dir, dry_run=dry_run)
        elif any([_is_photo_file(file) for file in files]):
            logging.warning('Found photos but no %s in %s' % (_PICASA_INI_FILE, dir))


def migrate_directory(input_dir: Path, files: List[str], db: DigikamDb,
                      contact_tags_per_dir: Dict[Path, ContactTags],
                      dry_run: bool) -> ContactTags:
    """Migrates metadata of all photo files in the given directory."""
    logging.info('===========================================================================================')
    if input_dir.name == '.picasaoriginals':
        logging.info('Skipping %s' % input_dir)
        return {}
    logging.info('Now migrating %s' % input_dir)

    # Find digiKam album.
    album_id = db.find_album_by_dir(input_dir)
    album_images = db.get_album_images(album_id)

    # Read ini file.
    ini = configparser.ConfigParser()
    ini_file = input_dir / _PICASA_INI_FILE
    ini.read(ini_file, encoding='utf8')
    used_ini_sections = {'Picasa', 'Contacts', 'Contacts2'}

    # Create or look up digiKam tags for each Picasa album and contact/person.
    album_to_tag = _map_albums_to_tags(ini, db, used_ini_sections, dry_run=dry_run)
    self_contact_to_tag = _map_contacts_to_tags(ini['Contacts2'], db, dry_run=dry_run) if 'Contacts2' in ini else {}

    # Merge contacts declared in parent ini files.
    contact_to_tag = self_contact_to_tag.copy()
    for parent_dir in input_dir.parents:
        for contact_id, tag_id in contact_tags_per_dir.get(parent_dir, {}).items():
            if contact_id in contact_to_tag:
                assert contact_to_tag[contact_id] == tag_id
            else:
                contact_to_tag[contact_id] = tag_id

    # Migrate file by file.
    for filename in filter(_is_photo_file, files):
        if filename not in album_images:
            raise ValueError('digiKam does not know %s/%s' % (input_dir, filename))
        image_id = album_images[filename]
        if ini.has_section(filename):
            used_ini_sections.add(filename)
            ini_section = ini[filename]
            try:
                migrate_file(filename, image_id, ini_section, db, album_to_tag, contact_to_tag, dry_run=dry_run)
            except Exception as e:
                raise RuntimeError('Error when processing %s/%s' % (input_dir, filename)) from e

    # Make sure we actually read all the data from the ini file.
    unused_ini_sections = set(ini.sections()) - used_ini_sections
    unused_photo_sections = {section for section in unused_ini_sections if _is_photo_file(section)}
    if unused_photo_sections:
        logging.warning(('Some files have metadata in %s but are gone ' +
                         '(probably fine, they might have been deleted or moved elsewhere on purpose): %s')
                        % (ini_file, unused_photo_sections))
    unused_ini_sections -= unused_photo_sections
    if unused_ini_sections:
        logging.warning('Unused INI sections in %s: %s' % (ini_file, unused_ini_sections))

    return self_contact_to_tag  # For use in subdirectories

def migrate_file(filename: str, image_id: int, ini_section: configparser.SectionProxy, db: DigikamDb,
                 album_to_tag: Dict[str, int],  # Picasa ID -> digiKam Tag ID
                 contact_to_tag: Dict[str, Optional[int]],  # Picasa contact ID -> digiKam Tag ID
                 dry_run: bool):
    # Note: Picasa's rotate=rotate(N) means 0=normal, 1=90º, 2=180º, 3=270º clock-wise. This does *not* influence the
    # face coordinates, which are wrt. the image file stored on disk.
    used_ini_keys = {'backuphash', 'rotate'}
    if ini_section.getboolean('star'):
        used_ini_keys.add('star')
        if db.image_has_pick_tag(image_id):
            logging.warning(
                'Not applying star label to %s (%s) because it already has a Pick label' % (image_id, filename))
        else:
            logging.debug('Applying star label to %s (%s)' % (image_id, filename))
            if not dry_run:
                db.star_image(image_id)

    albums = ini_section.get('albums')
    if albums:
        used_ini_keys.add('albums')
        for album_id in albums.split(','):
            logging.debug('Adding album %s to image %s (%s)' % (album_id, image_id, filename))
            if not dry_run:
                db.add_image_tag(image_id, album_to_tag[album_id])

    faces = ini_section.get('faces')
    if faces:
        used_ini_keys.add('faces')
        if filename.lower().endswith('.psd'):
            # Note: digiKam doesn't seem to know the size of PSD files and thus also
            # can't place face tags on them.
            logging.warning('Skipping faces on %s because of PSD format' % filename)
        else:
            for face_data in faces.split(';'):
                migrate_face(image_id, filename, face_data, db, contact_to_tag, dry_run=dry_run)

    unused_ini_keys = set(ini_section.keys()) - used_ini_keys
    if unused_ini_keys:
        logging.warning('Unused INI keys for %s: %s' % (filename, unused_ini_keys))


def migrate_face(image_id: int, filename: str, face_data: str, db: DigikamDb, contact_to_tag: Dict[str, Optional[int]], dry_run: bool):
    face_data = face_data.split(',')
    assert len(face_data) == 2
    if face_data[1] == _UNKNOWN_FACE_ID:
        return
    contact_id = face_data[1]
    tag_id = contact_to_tag[contact_id]
    if tag_id is None:
        return  # Skip silently, as _map_contacts_to_tags() already warns about unmapped contacts.

    if db.image_has_tag(image_id, tag_id):
        logging.warning(
            'Not applying face %s (%s) to %s (%s) because it already has that face tag' % (tag_id, contact_id, image_id, filename))
        return

    # Convert the rectangle.
    image_size = db.get_image_size(image_id)
    picasa_rect = rect64.parse_rect64(face_data[0])
    digikam_rect = rect64.to_digikam_rect(image_size, picasa_rect)

    logging.debug('Adding face %s (%s) at %s to %s (%s)' % (tag_id, contact_id, digikam_rect, image_id, filename))
    if dry_run:
        return

    # Insert the tag into the digiKam database.
    # Skip if the person is already tagged anywhere on that photo in the digiKam database.
    if db.add_image_tag(image_id, tag_id):
        # A new tag was added, so we need to provide the coordinates.
        db.set_image_tag_property(image_id, tag_id, _FACE_TAG_REGION_PROPERTY, digikam_rect)


def _map_albums_to_tags(
        ini: configparser.ConfigParser, db: DigikamDb, used_ini_sections: Set[str], dry_run: bool
) -> Dict[str, int]:  # Picasa ID -> digiKam Tag ID
    picasa_tag = db.find_or_create_tag(parent_tag=0, name=_PICASA_TAG_NAME, dry_run=dry_run)
    result = {}
    for section_name in ini.sections():
        if section_name.startswith('.album:'):
            album_id = section_name[7:]
            section = ini[section_name]
            if not 'name' in section:
                logging.debug('Skipping unnamed album %s' % album_id)
                continue
            assert section['name']
            used_ini_sections.add(section_name)
            assert album_id == section['token']
            tag_id = db.find_or_create_tag(parent_tag=picasa_tag, name=section['name'], dry_run=dry_run)
            result[album_id] = tag_id
    return result


def _map_contacts_to_tags(
        contacts_section: configparser.SectionProxy, db: DigikamDb, dry_run: bool
) -> ContactTags:  # Picasa ID -> digiKam Tag ID
    result = {}
    for contact_id, value in contacts_section.items():
        person_name = value.split(';')[0]
        result[contact_id] = db.find_or_create_person_tag(person_name, dry_run=dry_run)
    return result
